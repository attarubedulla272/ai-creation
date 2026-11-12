"""Separate FFmpeg worker for editor timeline exports."""

from __future__ import annotations

import asyncio
import errno
import logging
import shutil
import tempfile
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import UUID

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.processing_job import ProcessingJob
from app.services.storage import StorageService

logger = logging.getLogger(__name__)
CancellationCheck = Callable[[], Awaitable[bool]]


class TimelineExportCancelled(Exception):
    """Raised when an owner requests cancellation of a timeline export."""


class TimelineTextRenderError(RuntimeError):
    """Raised for text rendering limitations that can be corrected by the editor user."""


@dataclass(frozen=True)
class TextRenderLayout:
    """Resolved layout facts shared by preflight validation and raster export."""

    line_count: int
    max_lines: int
    used_fallback_font: bool
    available_font_families: tuple[str, ...]


async def _stage_object(
    storage: StorageService,
    key: str,
    destination: Path,
    is_cancelled: CancellationCheck | None = None,
) -> None:
    """Stage an object through the storage interface without trusting user paths."""

    with destination.open("xb") as file:
        async for chunk in storage.open_stream(key):
            if is_cancelled is not None and await is_cancelled():
                raise TimelineExportCancelled
            await asyncio.to_thread(file.write, chunk)


async def _save_file(
    storage: StorageService,
    key: str,
    path: Path,
    is_cancelled: CancellationCheck | None = None,
) -> int:
    async def chunks() -> AsyncIterable[bytes]:
        with path.open("rb") as file:
            while chunk := await asyncio.to_thread(file.read, 1024 * 1024):
                if is_cancelled is not None and await is_cancelled():
                    raise TimelineExportCancelled
                yield chunk

    return await storage.save_stream(key, chunks())


async def _run_ffmpeg(
    arguments: list[str],
    timeout: float = 7200,
    is_cancelled: CancellationCheck | None = None,
    progress: Callable[[int], Awaitable[None]] | None = None,
    duration: float | None = None,
) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("FFmpeg is not installed or is not on PATH.")
    progress_arguments = [*arguments[:-1], "-progress", "pipe:1", "-nostats", arguments[-1]]
    process = await asyncio.create_subprocess_exec(
        executable,
        *progress_arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(process.stderr.read())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RuntimeError("Timeline export exceeded its two-hour time limit.")
            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=min(1, remaining) if is_cancelled is not None else remaining,
                )
            except TimeoutError:
                if loop.time() >= deadline:
                    raise RuntimeError("Timeline export exceeded its two-hour time limit.")
                if is_cancelled is not None:
                    if await is_cancelled():
                        raise TimelineExportCancelled
                else:
                    raise RuntimeError("Timeline export exceeded its two-hour time limit.")
                continue
            if not line:
                break
            if is_cancelled is not None and line.startswith(b"progress=") and await is_cancelled():
                raise TimelineExportCancelled
            if progress is not None and duration and line.startswith(b"out_time_ms="):
                try:
                    position = int(line.partition(b"=")[2]) / 1_000_000
                except ValueError:
                    continue
                await progress(min(89, max(5, int(position / duration * 85))))
        try:
            return_code = await asyncio.wait_for(
                process.wait(),
                timeout=max(0.01, deadline - loop.time()),
            )
        except TimeoutError:
            raise RuntimeError("Timeline export exceeded its two-hour time limit.") from None
        stderr = await stderr_task
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        stderr_task.cancel()
        try:
            await stderr_task
        except asyncio.CancelledError:
            pass
        raise
    if return_code:
        logger.warning("FFmpeg timeline export failed (exit %s): %s", return_code, stderr[-2000:])
        raise RuntimeError(
            "FFmpeg could not render this timeline. Check the source media and trim points."
        )


async def _set_job_progress(
    session_factory: async_sessionmaker[AsyncSession], job_id: UUID, progress: int
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == "processing")
            .values(progress=progress)
        )
        await session.commit()


def _number(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".") or "0"


def _escape_expression(value: str) -> str:
    return value.replace(",", r"\,")


def _keyframed_expression(
    clip: dict[str, Any],
    property_name: str,
    default: float,
    time_variable: str = "t",
) -> str:
    keyframes = sorted(
        (
            keyframe
            for keyframe in clip.get("keyframes", [])
            if isinstance(keyframe, dict) and keyframe.get("property") == property_name
        ),
        key=lambda keyframe: float(keyframe["time"]),
    )
    if not keyframes:
        return _number(default)

    start = float(clip["start"])
    expression = _number(float(keyframes[-1]["value"]))
    for left, right in reversed(list(pairwise(keyframes))):
        left_time = float(left["time"])
        right_time = float(right["time"])
        left_value = float(left["value"])
        right_value = float(right["value"])
        if left.get("interpolation", "linear") == "hold":
            segment = _number(left_value)
        else:
            segment = (
                f"{_number(left_value)}+({_number(right_value - left_value)})"
                f"*({time_variable}-{_number(start + left_time)})/"
                f"{_number(right_time - left_time)}"
            )
        expression = f"if(lt({time_variable},{_number(start + right_time)}),{segment},{expression})"
    first_time = float(keyframes[0]["time"])
    if first_time > 0:
        expression = (
            f"if(lt({time_variable},{_number(start + first_time)}),{_number(default)},{expression})"
        )
    else:
        expression = f"if(lt({time_variable},{_number(start)}),{_number(default)},{expression})"
    return expression


def _filter_value(expression: str) -> str:
    return f"'{_escape_expression(expression)}'"


def _transition_type(clip: dict[str, Any], direction: str) -> tuple[str, float]:
    name = str(clip.get(f"transition_{direction}", "none"))
    if name == "none":
        fade = float(clip.get(f"fade_{direction}", 0))
        return ("fade" if fade else "none"), fade
    return name, float(clip.get(f"transition_{direction}_duration", 0.5))


def _alpha_expression(
    clip: dict[str, Any],
    opacity_expression: str,
    start: float,
    end: float,
    *,
    fade_to_black: bool = False,
    include_clip_fades: bool = False,
) -> str:
    alpha = f"({opacity_expression})"
    for direction in ("in", "out"):
        transition, duration = _transition_type(clip, direction)
        if duration <= 0:
            continue
        if transition == "fade" and fade_to_black:
            continue
        if direction == "in":
            if transition in {"fade", "cross_dissolve"}:
                factor = f"min(1,max(0,(T-{_number(start)})/{_number(duration)}))"
            elif transition in {"wipe_left", "wipe_right"}:
                reveal = (
                    f"lt(X,(T-{_number(start)})/{_number(duration)}*W)"
                    if transition == "wipe_left"
                    else f"gt(X,W-(T-{_number(start)})/{_number(duration)}*W)"
                )
                factor = f"if(lt(T,{_number(start + duration)}),if({reveal},1,0),1)"
            else:
                continue
        else:
            transition_start = end - duration
            if transition in {"fade", "cross_dissolve"}:
                factor = f"min(1,max(0,({_number(end)}-T)/{_number(duration)}))"
            elif transition in {"wipe_left", "wipe_right"}:
                remain = (
                    f"gt(X,(T-{_number(transition_start)})/{_number(duration)}*W)"
                    if transition == "wipe_left"
                    else f"lt(X,W-(T-{_number(transition_start)})/{_number(duration)}*W)"
                )
                factor = (
                    f"if(lt(T,{_number(transition_start)}),1,"
                    f"if(lt(T,{_number(end)}),if({remain},1,0),0))"
                )
            else:
                continue
        alpha += f"*({factor})"
    if include_clip_fades:
        for direction in ("in", "out"):
            duration = float(clip.get(f"fade_{direction}", 0))
            if duration <= 0:
                continue
            fade_expression = (
                f"min(1,max(0,(T-{_number(start)})/{_number(duration)}))"
                if direction == "in"
                else f"min(1,max(0,({_number(end)}-T)/{_number(duration)}))"
            )
            alpha += f"*({fade_expression})"
    return f"alpha(X,Y)*{alpha}"


def _needs_dynamic_alpha(
    clip: dict[str, Any],
    *,
    fade_to_black: bool = False,
    include_clip_fades: bool = False,
) -> bool:
    if include_clip_fades and any(float(clip.get(f"fade_{direction}", 0)) > 0 for direction in ("in", "out")):
        return True
    if any(
        isinstance(keyframe, dict) and keyframe.get("property") == "opacity"
        for keyframe in clip.get("keyframes", [])
    ):
        return True
    return any(
        _transition_type(clip, direction)[1] > 0
        and not (fade_to_black and _transition_type(clip, direction)[0] == "fade")
        for direction in ("in", "out")
    )


def _effect_filters(clip: dict[str, Any]) -> list[str]:
    filters: list[str] = []
    for effect in clip.get("effects", []):
        if not isinstance(effect, dict):
            raise TypeError("The timeline contains an invalid visual effect.")
        if not effect.get("enabled", True):
            continue
        effect_type = effect.get("type")
        value = float(effect["value"])
        if effect_type == "brightness":
            filters.append(f"eq=brightness={_number(value)}")
        elif effect_type == "contrast":
            filters.append(f"eq=contrast={_number(value)}")
        elif effect_type == "saturation":
            filters.append(f"eq=saturation={_number(value)}")
        elif effect_type == "grayscale":
            filters.append(f"hue=s={_number(1 - value)}")
        elif effect_type == "blur":
            if value > 0:
                filters.append(
                    "boxblur="
                    f"lr='min({_number(value)},min(w,h)/2-1)':lp=1:"
                    f"cr='min({_number(value)},min(w,h)/4-1)':cp=1"
                )
        else:
            raise RuntimeError(f"Unsupported visual effect type: {effect_type!r}.")
    return filters


def _visual_fade_filters(clip: dict[str, Any], start: float, end: float) -> list[str]:
    filters: list[str] = []
    for direction in ("in", "out"):
        transition, transition_duration = _transition_type(clip, direction)
        legacy_duration = float(clip.get(f"fade_{direction}", 0))
        duration = max(
            legacy_duration,
            transition_duration
            if transition == "fade" and clip.get(f"transition_{direction}") != "none"
            else 0,
        )
        if duration <= 0:
            continue
        if direction == "in":
            filters.append(f"fade=t=in:st={_number(start)}:d={_number(duration)}:color=black")
        else:
            filters.append(
                f"fade=t=out:st={_number(end - duration)}:d={_number(duration)}:color=black"
            )
    return filters


def _font_supports_text(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, text: str) -> bool:
    missing = font.getmask("\U0010ffff")
    missing_glyph = (missing.size, bytes(missing))
    return all(
        character.isspace()
        or (glyph := font.getmask(character)).size != missing_glyph[0]
        or bytes(glyph) != missing_glyph[1]
        for character in text
    )


def _render_subtitle_image(
    text: str,
    destination: Path | None,
    width: int,
    height: int,
    style: dict[str, Any] | None = None,
) -> TextRenderLayout:
    appearance = style or {}
    font_size = max(10, min(300, int(appearance.get("font_size", max(18, round(height * 0.045))))))
    family = str(appearance.get("font_family", "sans-serif"))
    weight = str(appearance.get("font_weight", "normal"))
    font_style = str(appearance.get("font_style", "normal"))
    font_files = {
        ("sans-serif", "normal", "normal"): [
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ],
        ("sans-serif", "bold", "normal"): [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ],
        ("sans-serif", "normal", "italic"): [
            "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
            "C:/Windows/Fonts/ariali.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf",
        ],
        ("sans-serif", "bold", "italic"): [
            "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
            "C:/Windows/Fonts/arialbi.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-BoldItalic.ttf",
        ],
        ("serif", "normal", "normal"): [
            "/System/Library/Fonts/Supplemental/Georgia.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ],
        ("serif", "bold", "normal"): [
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
            "C:/Windows/Fonts/georgiab.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        ],
        ("serif", "normal", "italic"): [
            "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
            "C:/Windows/Fonts/georgiai.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        ],
        ("serif", "bold", "italic"): [
            "/System/Library/Fonts/Supplemental/Georgia Bold Italic.ttf",
            "C:/Windows/Fonts/georgiaz.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf",
        ],
        ("monospace", "normal", "normal"): [
            "/System/Library/Fonts/Menlo.ttc",
            "C:/Windows/Fonts/consola.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ],
        ("monospace", "bold", "normal"): [
            "/System/Library/Fonts/Menlo.ttc",
            "C:/Windows/Fonts/consolab.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        ],
        ("monospace", "normal", "italic"): [
            "/usr/share/fonts/Menlo.ttc",
            "C:/Windows/Fonts/consolai.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf",
        ],
        ("monospace", "bold", "italic"): [
            "/System/Library/Fonts/Menlo.ttc",
            "C:/Windows/Fonts/consolaz.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-BoldOblique.ttf",
        ],
    }
    unicode_fallbacks = [
        "C:/Windows/Fonts/ARIALUNI.TTF",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansTelugu-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansMalayalam-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    def find_available_font_families() -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    candidate_family
                    for (candidate_family, _, _), paths in font_files.items()
                    if any(Path(path).is_file() for path in paths)
                }
            )
        )

    requested_candidates = font_files.get((family, weight, font_style), [])
    candidates = [
        *requested_candidates,
        *unicode_fallbacks,
        *font_files[("sans-serif", "normal", "normal")],
    ]
    font = None
    used_fallback_font = False
    for candidate in dict.fromkeys(candidates):
        path = Path(candidate)
        if not path.is_file():
            continue
        candidate_font = ImageFont.truetype(str(path), font_size)
        if _font_supports_text(candidate_font, text):
            font = candidate_font
            used_fallback_font = candidate not in requested_candidates
            break
    available_font_families: tuple[str, ...] = ()
    if font is None:
        available_font_families = find_available_font_families()
        default_font = ImageFont.load_default(size=font_size)
        if not _font_supports_text(default_font, text):
            alternatives = ", ".join(available_font_families) or "none"
            raise TimelineTextRenderError(
                "No installed Unicode font can render every character in this text overlay. "
                f"Available font families on this worker: {alternatives}."
            )
        font = default_font
        used_fallback_font = True
    elif used_fallback_font:
        available_font_families = find_available_font_families()
    padding = max(4, round(font_size * 0.2))
    max_text_width = max(
        font_size, round(width * float(appearance.get("width", 0.84)) - 2 * padding)
    )
    draw_context = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split() or [""]:
            pieces = [word]
            if draw_context.textlength(word, font=font) > max_text_width:
                pieces = []
                piece = ""
                for character in word:
                    candidate = f"{piece}{character}"
                    if piece and draw_context.textlength(candidate, font=font) > max_text_width:
                        pieces.append(piece)
                        piece = character
                    else:
                        piece = candidate
                if piece:
                    pieces.append(piece)
            for piece in pieces:
                candidate = f"{line} {piece}".strip()
                if line and draw_context.textlength(candidate, font=font) > max_text_width:
                    lines.append(line)
                    line = piece
                else:
                    line = candidate
        lines.append(line)
    line_height = font_size + max(3, round(font_size * 0.2))
    max_lines = max(1, min(12, height // max(1, line_height)))
    if len(lines) > max_lines:
        raise TimelineTextRenderError(
            f"Text overlay wraps to {len(lines)} lines, exceeding the {max_lines}-line "
            "limit at this resolution. Reduce the font size or split the text into multiple clips."
        )
    layout = TextRenderLayout(
        len(lines), max_lines, used_fallback_font, available_font_families
    )
    if destination is None:
        return layout
    text_height = max(line_height, len(lines) * line_height)
    text_width = min(
        max_text_width,
        max(
            (round(draw_context.textlength(line, font=font)) for line in lines),
            default=0,
        ),
    )
    image_width = round(width * float(appearance.get("width", 0.84)))
    image = Image.new("RGBA", (image_width, text_height + padding * 2))
    draw = ImageDraw.Draw(image)
    alignment = str(appearance.get("alignment", "center"))
    box_width = min(image_width, text_width + padding * 2)
    box_x = (
        0
        if alignment == "left"
        else (image_width - box_width if alignment == "right" else (image_width - box_width) // 2)
    )
    background_opacity = float(appearance.get("background_opacity", 0))
    if background_opacity > 0:
        background_color = ImageColor.getrgb(str(appearance.get("background_color", "#11111B")))
        draw.rectangle(
            (box_x, 0, box_x + box_width - 1, image.height - 1),
            fill=(*background_color, round(background_opacity * 255)),
        )
    outline_width = int(appearance.get("outline_width", 2))
    text_color = ImageColor.getrgb(str(appearance.get("color", "#FFFFFF")))
    outline_color = ImageColor.getrgb(str(appearance.get("outline_color", "#000000")))
    text_x = (
        box_x + padding
        if alignment == "left"
        else (
            box_x + box_width - padding - text_width
            if alignment == "right"
            else box_x + (box_width - text_width) // 2
        )
    )
    shadow = Image.new("RGBA", image.size)
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_color = ImageColor.getrgb(str(appearance.get("shadow_color", "#000000")))
    shadow_blur = int(appearance.get("shadow_blur", 0))
    if shadow_blur > 0:
        shadow_draw.multiline_text(
            (text_x + max(1, shadow_blur // 2), padding + max(1, shadow_blur // 2)),
            "\n".join(lines),
            font=font,
            fill=(*shadow_color, 220),
            spacing=max(3, round(font_size * 0.2)),
            stroke_width=outline_width,
            stroke_fill=(*shadow_color, 220),
        )
        image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(shadow_blur)))
        draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text(
            (text_x, padding + index * line_height),
            line,
            font=font,
            fill=(*text_color, 255),
            stroke_width=outline_width,
            stroke_fill=(*outline_color, 255),
        )
    image.save(destination)
    return layout


def _build_video_filters(
    clip: dict[str, Any],
    input_index: int,
    track_type: str,
    width: int,
    height: int,
    frame_rate: float,
    current: str,
    output: str,
) -> list[str]:
    start = float(clip["start"])
    end = start + float(clip["duration"])
    if track_type == "subtitle":
        scale_expr = _keyframed_expression(clip, "scale", float(clip.get("scale", 1)))
        opacity_expr = _keyframed_expression(
            clip,
            "opacity",
            float(clip.get("opacity", 1)),
            time_variable="T",
        )
        x_expr = _keyframed_expression(clip, "x", float(clip.get("position_x", 0.5)))
        y_expr = _keyframed_expression(clip, "y", float(clip.get("position_y", 0.88)))
        filters = [
            f"[{input_index}:v:0]setpts=PTS-STARTPTS+{_number(start)}/TB",
            f"scale=w='iw*({scale_expr})':h='ih*({scale_expr})':eval=frame",
            "format=rgba",
        ]
        if _needs_dynamic_alpha(clip, include_clip_fades=True):
            filters.append(
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a={_filter_value(_alpha_expression(clip, opacity_expr, start, end, include_clip_fades=True))}:"
                "interpolation=nearest"
            )
        elif float(clip.get("opacity", 1)) != 1:
            filters.append(f"colorchannelmixer=aa={_number(float(clip['opacity']))}")
        filters.append("format=rgba")
        clip_label = f"clip{output}"
        x = _filter_value(f"(W-w)*({x_expr})")
        y = _filter_value(f"(H-h)*({y_expr})")
        return [
            ",".join(filters) + f"[{clip_label}];[{current}][{clip_label}]overlay=x={x}:y={y}:"
            f"eof_action=pass:shortest=0:enable='between(t,{_number(start)},{_number(end)})'"
            f"[{output}]"
        ]

    scale_expr = _keyframed_expression(clip, "scale", float(clip.get("scale", 1)))
    opacity_expr = _keyframed_expression(
        clip,
        "opacity",
        float(clip.get("opacity", 1)),
        time_variable="T",
    )
    x_expr = _keyframed_expression(clip, "x", float(clip.get("position_x", 0.5)))
    y_expr = _keyframed_expression(clip, "y", float(clip.get("position_y", 0.5)))
    filters = [f"[{input_index}:v:0]setpts=PTS-STARTPTS+{_number(start)}/TB"]
    if track_type == "video":
        filters.append(
            f"scale={width}:{height}:force_original_aspect_ratio=decrease"
            f",pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    else:
        filters.append(f"scale=w='iw*({scale_expr})':h='ih*({scale_expr})':eval=frame")
    filters.append("setsar=1")
    brightness = float(clip.get("brightness", 0))
    contrast = float(clip.get("contrast", 1))
    saturation = float(clip.get("saturation", 1))
    if brightness != 0 or contrast != 1 or saturation != 1:
        filters.append(
            f"eq=brightness={_number(brightness)}:"
            f"contrast={_number(contrast)}:saturation={_number(saturation)}"
        )
    filters.extend(_effect_filters(clip))
    if track_type in {"video", "overlay"}:
        filters.extend(_visual_fade_filters(clip, start, end))
    filters.append("format=rgba")
    if track_type == "video":
        filters.append(f"scale=w='iw*({scale_expr})':h='ih*({scale_expr})':eval=frame")
    if _needs_dynamic_alpha(clip, fade_to_black=track_type in {"video", "overlay"}):
        opacity = _filter_value(
            _alpha_expression(
                clip,
                opacity_expr,
                start,
                end,
                fade_to_black=track_type in {"video", "overlay"},
            )
        )
        filters.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a={opacity}:interpolation=nearest")
    elif float(clip.get("opacity", 1)) != 1:
        filters.append(f"colorchannelmixer=aa={_number(float(clip['opacity']))}")
    filters.append("format=rgba")
    clip_label = f"clip{output}"
    graph = ",".join(filters) + f"[{clip_label}]"
    x = _filter_value(f"(W-w)*({x_expr})")
    y = _filter_value(f"(H-h)*({y_expr})")
    graph += (
        f";[{current}][{clip_label}]overlay=x={x}:y={y}:"
        f"eof_action=pass:shortest=0:enable='between(t,{_number(start)},{_number(end)})'"
        f"[{output}]"
    )
    return [graph]


def _build_audio_filter(
    clip: dict[str, Any],
    input_index: int,
    track_volume: float,
    output: str,
) -> str:
    duration = float(clip["duration"])
    start = float(clip["start"])
    local_clip = {**clip, "start": 0}
    volume_expr = _keyframed_expression(
        local_clip,
        "volume",
        float(clip.get("volume", 1)),
    )
    filters = [
        f"[{input_index}:a:0]atrim=duration={_number(duration)}",
        "asetpts=PTS-STARTPTS",
        f"volume={_filter_value(f'({track_volume})*({volume_expr})')}:eval=frame",
    ]
    _, fade_in_duration = _transition_type(clip, "in")
    _, fade_out_duration = _transition_type(clip, "out")
    if 0 < fade_in_duration <= duration:
        filters.append(f"afade=t=in:st=0:d={_number(fade_in_duration)}")
    if 0 < fade_out_duration <= duration:
        filters.append(
            f"afade=t=out:st={_number(duration - fade_out_duration)}:d={_number(fade_out_duration)}"
        )
    filters.append(f"adelay={round(start * 1000)}:all=1")
    return ",".join(filters) + f"[{output}]"


async def _render_job(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    job_id: UUID,
    owner_id: UUID,
    data: dict[str, Any],
) -> None:
    output_key = f"{owner_id}/{job_id}.mp4"

    async def is_cancelled() -> bool:
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            return job is None or job.status != "processing" or job.cancellation_requested

    try:
        tracks = data.get("tracks")
        if not isinstance(tracks, list) or not tracks:
            raise RuntimeError("The export job has no timeline tracks.")
        frame_rate = min(120, max(1, float(data["frame_rate"])))
        width = min(7680, max(16, int(data["width"])))
        height = min(7680, max(16, int(data["height"])))
        duration = min(86_400, max(0, float(data["duration"])))
        if duration <= 0:
            raise RuntimeError("The timeline has no renderable duration.")

        with tempfile.TemporaryDirectory(prefix="creator-timeline-") as directory:
            temporary = Path(directory)
            inputs: list[str] = []
            input_count = 0
            graph: list[str] = [
                (
                    f"color=c=black:s={width}x{height}:r={_number(frame_rate)}:"
                    f"d={_number(duration)},format=rgba[base]"
                )
            ]
            staged: dict[str, Path] = {}
            clips_to_render: list[tuple[int, dict[str, Any], dict[str, Any], int]] = []
            for track_order, track in enumerate(tracks):
                if not isinstance(track, dict) or track.get("muted"):
                    continue
                clips = track.get("clips")
                if not isinstance(clips, list):
                    raise TypeError("The timeline contains an invalid track.")
                for clip in clips:
                    if not isinstance(clip, dict):
                        raise TypeError("The timeline contains invalid clip data.")
                    start = max(0, float(clip["start"]))
                    clip_duration = float(clip["duration"])
                    if clip_duration <= 0 or start + clip_duration > duration + 0.001:
                        raise RuntimeError("A timeline clip has an invalid duration or position.")
                    key = clip.get("storage_key")
                    if key is not None:
                        if not isinstance(key, str):
                            raise TypeError("A timeline clip has an invalid media reference.")
                        if key not in staged:
                            source = temporary / f"source-{len(staged)}.media"
                            await _stage_object(storage, key, source, is_cancelled)
                            staged[key] = source
                        source = staged[key]
                        input_index = input_count
                        media_type = clip.get("media_type")
                        if media_type == "image":
                            inputs.extend(
                                [
                                    "-loop",
                                    "1",
                                    "-framerate",
                                    _number(frame_rate),
                                    "-t",
                                    _number(clip_duration),
                                    "-i",
                                    str(source),
                                ]
                            )
                        else:
                            source_start = max(0, float(clip.get("source_start", 0)))
                            inputs.extend(
                                [
                                    "-ss",
                                    _number(source_start),
                                    "-t",
                                    _number(clip_duration),
                                    "-i",
                                    str(source),
                                ]
                            )
                        input_count += 1
                    else:
                        input_index = -1
                    clips_to_render.append((track_order, track, clip, input_index))

            next_video_label = "base"
            audio_labels: list[str] = []
            rendered_clip_count = 0
            for track_order, track, clip, input_index in sorted(
                clips_to_render,
                key=lambda item: (
                    item[0],
                    int(item[2].get("z_index", 0)),
                    float(item[2]["start"]),
                    str(item[2].get("id", "")),
                ),
            ):
                track_type = str(track.get("type"))
                if track_type not in {"video", "overlay", "audio", "subtitle"}:
                    raise RuntimeError("The timeline contains an unsupported track type.")
                is_text_clip = (
                    track_type in {"overlay", "subtitle"} and clip.get("text") is not None
                )
                if is_text_clip:
                    if not clip.get("text"):
                        continue
                    if input_index < 0:
                        source = temporary / f"text-{input_count}.png"
                        _render_subtitle_image(
                            str(clip["text"]),
                            source,
                            width,
                            height,
                            clip.get("text_style"),
                        )
                        input_index = input_count
                        inputs.extend(
                            [
                                "-loop",
                                "1",
                                "-framerate",
                                _number(frame_rate),
                                "-t",
                                _number(float(clip["duration"])),
                                "-i",
                                str(source),
                            ]
                        )
                        input_count += 1
                    next_label = f"video{rendered_clip_count}"
                    graph.extend(
                        _build_video_filters(
                            clip,
                            input_index,
                            "subtitle",
                            width,
                            height,
                            frame_rate,
                            next_video_label,
                            next_label,
                        )
                    )
                    next_video_label = next_label
                    rendered_clip_count += 1
                    continue
                if input_index < 0:
                    continue
                if track_type in {"video", "overlay"}:
                    clip_label = f"video{rendered_clip_count}"
                    graph.extend(
                        _build_video_filters(
                            clip,
                            input_index,
                            track_type,
                            width,
                            height,
                            frame_rate,
                            next_video_label,
                            clip_label,
                        )
                    )
                    next_video_label = clip_label
                if (
                    track_type in {"video", "overlay", "audio"}
                    and clip.get("has_audio")
                    and not track.get("audio_muted", False)
                    and float(track.get("volume", 1)) > 0
                ):
                    audio_label = f"audio{len(audio_labels)}"
                    graph.append(
                        _build_audio_filter(
                            clip,
                            input_index,
                            float(track.get("volume", 1)),
                            audio_label,
                        )
                    )
                    audio_labels.append(audio_label)
                if track_type in {"video", "overlay"}:
                    rendered_clip_count += 1

            if rendered_clip_count == 0:
                raise RuntimeError("The timeline contains no visible video or text clips.")
            if audio_labels:
                graph.append(
                    f"{''.join(f'[{label}]' for label in audio_labels)}"
                    f"amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0,"
                    f"apad=whole_dur={_number(duration)},atrim=duration={_number(duration)}[aout]"
                )
            video_filter = ";".join(graph)
            rendered = temporary / "rendered.mp4"
            arguments = [
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                *inputs,
                "-filter_complex",
                video_filter,
                "-map",
                f"[{next_video_label}]",
            ]
            if audio_labels:
                arguments.extend(["-map", "[aout]"])
            arguments.extend(
                [
                    "-t",
                    _number(duration),
                    "-r",
                    _number(frame_rate),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-threads",
                    "2",
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
            if audio_labels:
                arguments.extend(["-c:a", "aac", "-b:a", "192k"])
            arguments.extend(["-movflags", "+faststart", str(rendered)])

            async def report_progress(value: int) -> None:
                await _set_job_progress(session_factory, job_id, value)

            await _run_ffmpeg(
                arguments,
                is_cancelled=is_cancelled,
                progress=report_progress,
                duration=duration,
            )

            if await is_cancelled():
                raise TimelineExportCancelled
            await _set_job_progress(session_factory, job_id, 90)
            output_size_bytes = await _save_file(storage, output_key, rendered, is_cancelled)

        if await is_cancelled():
            raise TimelineExportCancelled
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None and job.status == "processing":
                job.status = "completed"
                job.progress = 100
                job.output_data = {
                    "storage_key": output_key,
                    "duration_seconds": duration,
                    "width": width,
                    "height": height,
                    "preset": data.get("preset", "timeline"),
                    "file_size_bytes": output_size_bytes,
                }
                await session.commit()
    except TimelineExportCancelled:
        try:
            await storage.delete(output_key)
        except OSError:
            logger.exception("Could not clean cancelled timeline export %s", job_id)
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "cancelled"
                job.error_message = "Timeline export was cancelled."
                await session.commit()
    except asyncio.CancelledError:
        try:
            await storage.delete(output_key)
        except OSError:
            logger.exception("Could not clean cancelled timeline export %s", job_id)
        async with session_factory() as session:
            await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id, ProcessingJob.status == "processing")
                .values(status="queued", progress=0, error_message=None)
            )
            await session.commit()
        raise
    except Exception as error:
        logger.exception("Timeline export job %s failed", job_id)
        try:
            await storage.delete(output_key)
        except OSError:
            logger.exception("Could not clean failed timeline export %s", job_id)
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None and job.status == "processing":
                job.status = "failed"
                if isinstance(error, TimelineTextRenderError):
                    job.error_message = str(error)
                elif isinstance(error, OSError) and error.errno == errno.ENOSPC:
                    job.error_message = "Insufficient disk space to render this export."
                else:
                    job.error_message = (
                        "Timeline export failed. Check source media, codec support, "
                        "and available disk space."
                    )
                await session.commit()


async def run_timeline_export_worker(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    poll_interval: float = 1.5,
) -> None:
    """Claim and render queued timeline exports without blocking API requests."""

    while True:
        async with session_factory() as session:
            job = await session.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.job_type == "timeline_export",
                    ProcessingJob.status == "queued",
                )
                .order_by(ProcessingJob.created_at, ProcessingJob.id)
                .limit(1)
            )
            if job is None:
                job_id = None
                owner_id = None
                data = None
            else:
                result = await session.execute(
                    update(ProcessingJob)
                    .where(ProcessingJob.id == job.id, ProcessingJob.status == "queued")
                    .values(status="processing", progress=1)
                )
                if result.rowcount != 1:
                    job_id = None
                    owner_id = None
                    data = None
                else:
                    job_id = job.id
                    owner_id = job.owner_id
                    data = job.input_data or {}
                    await session.commit()
        if job_id is None or owner_id is None or data is None:
            await asyncio.sleep(poll_interval)
            continue
        await _render_job(session_factory, storage, job_id, owner_id, data)
