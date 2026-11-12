"""Safe SRT and WebVTT parsing and serialization for editor subtitle clips."""

from __future__ import annotations

import re
from typing import Literal

from app.schemas.timeline import TimelineSubtitleCue

SubtitleFormat = Literal["srt", "vtt"]
_TIMESTAMP = re.compile(
    r"^(?:(?P<hours>\d+):)?(?P<minutes>\d{2}):"
    r"(?P<seconds>\d{2})[,.](?P<milliseconds>\d{1,3})$"
)


def _parse_timestamp(value: str, cue_number: int) -> float:
    match = _TIMESTAMP.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Subtitle cue {cue_number} has an invalid timestamp: {value!r}.")
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    milliseconds = int(match.group("milliseconds").ljust(3, "0"))
    if minutes > 59 or seconds > 59:
        raise ValueError(f"Subtitle cue {cue_number} has an invalid timestamp: {value!r}.")
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def parse_subtitles(content: str, subtitle_format: SubtitleFormat) -> list[TimelineSubtitleCue]:
    """Parse UTF-8 SRT or WebVTT cues; reject malformed cue timestamps explicitly."""

    normalized = content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ValueError("The subtitle file contains no valid cues.")
    blocks = re.split(r"\n[ \t]*\n", normalized.strip("\n"))
    cues: list[TimelineSubtitleCue] = []
    for block_number, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        content_lines = [(index, line.strip()) for index, line in enumerate(lines) if line.strip()]
        if not content_lines or (
            subtitle_format == "vtt"
            and content_lines[0][1].startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))
        ):
            continue
        timing_entry = next(
            ((index, line) for index, line in content_lines if "-->" in line),
            None,
        )
        if timing_entry is None:
            raise ValueError(f"Subtitle block {block_number} is missing a timestamp range.")
        timing_index, timing_line = timing_entry
        start_text, separator, end_and_settings = timing_line.partition("-->")
        end_text = end_and_settings.strip().split(maxsplit=1)[0] if separator else ""
        start = _parse_timestamp(start_text, block_number)
        end = _parse_timestamp(end_text, block_number)
        text = "\n".join(lines[timing_index + 1 :]).strip("\r\n")
        if end <= start:
            raise ValueError(f"Subtitle cue {block_number} must end after it starts.")
        if not text.strip():
            raise ValueError(f"Subtitle cue {block_number} has no text.")
        if len(text) > 10_000:
            raise ValueError(f"Subtitle cue {block_number} exceeds the 10,000-character limit.")
        if end > 86_400:
            raise ValueError(f"Subtitle cue {block_number} exceeds the 24-hour timeline limit.")
        cues.append(TimelineSubtitleCue(start=start, duration=end - start, text=text))
    if not cues:
        raise ValueError("The subtitle file contains no valid cues.")
    return cues


def _format_timestamp(seconds: float, separator: str) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}{separator}{milliseconds:03}"


def export_subtitles(cues: list[TimelineSubtitleCue], subtitle_format: SubtitleFormat) -> str:
    """Serialize timeline subtitle cues to deterministic SRT or WebVTT text."""

    ordered = sorted(cues, key=lambda cue: cue.start)
    blocks = [
        "\n".join(
            [
                str(index),
                (
                    f"{_format_timestamp(cue.start, ',' if subtitle_format == 'srt' else '.')}"
                    f" --> "
                    f"{_format_timestamp(cue.start + cue.duration, ',' if subtitle_format == 'srt' else '.')}"
                ),
                cue.text,
            ]
        )
        for index, cue in enumerate(ordered, start=1)
    ]
    prefix = "" if subtitle_format == "srt" else "WEBVTT\n\n"
    return prefix + "\n\n".join(blocks) + "\n"
