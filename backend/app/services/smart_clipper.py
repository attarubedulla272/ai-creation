"""Local Smart Clipper analysis and FFmpeg export workers."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models.clip_candidate import ClipCandidate
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.models.transcript import Transcript, TranscriptSegment
from app.services.media_processing import probe_media
from app.services.storage import StorageService
from app.services.voice_providers import VoiceProviderRegistry

logger = logging.getLogger(__name__)


class SmartClipJobCancelled(Exception):
    """Raised when a user cancels a queued or processing clip export."""


HOOK_TERMS = ("imagine", "here's why", "the secret", "what if", "the truth", "most people")
INSIGHT_TERMS = ("because", "therefore", "the key", "in other words", "the reason", "lesson")
EMOTION_TERMS = ("love", "fear", "surprised", "amazing", "worried", "proud", "happy", "regret")
DEFAULT_RANKING_WEIGHTS = {
    "scene_changes": 0.8,
    "speech_activity": 1.0,
    "silence_boundaries": 0.8,
    "sentence_completeness": 1.2,
    "beginning_quality": 1.0,
    "ending_quality": 1.0,
    "interesting_opening": 1.4,
    "question_or_answer": 1.2,
    "key_insight": 1.3,
    "emotional_language": 0.8,
    "standalone_thought": 1.2,
    "pacing": 1.0,
}


def _fractional_score(text: str, terms: tuple[str, ...]) -> float:
    lowered = text.casefold()
    return float(any(term in lowered for term in terms))


def rank_transcript_window(
    segments: list[dict[str, Any]],
    preferences: dict[str, float] | None = None,
    *,
    clip_start: float | None = None,
    clip_end: float | None = None,
    scene_ranges: list[tuple[float, float]] | None = None,
    silence_ranges: list[tuple[float, float]] | None = None,
) -> tuple[float, dict[str, float], str]:
    """Score observable transcript and timing features with transparent heuristics."""

    text = " ".join(str(segment["text"]).strip() for segment in segments).strip()
    start = (
        float(segments[0]["start_seconds"])
        if clip_start is None and segments
        else max(0.0, float(clip_start or 0))
    )
    end = (
        float(segments[-1]["end_seconds"])
        if clip_end is None and segments
        else max(start, float(clip_end or start))
    )
    duration = max(0.0, end - start)
    spoken_duration = sum(
        max(
            0.0,
            min(end, float(segment["end_seconds"])) - max(start, float(segment["start_seconds"])),
        )
        for segment in segments
    )
    last_text = str(segments[-1]["text"]).strip() if segments else ""
    first_text = str(segments[0]["text"]).strip() if segments else ""
    end_marked = last_text.rstrip().endswith((".", "!", "?", "。", "！", "？"))
    start_is_fragment = first_text.casefold().startswith(("and ", "but ", "because ", "so ", "or "))
    relevant_scenes = scene_ranges or []
    scene_changes = sum(start < scene_start < end for scene_start, _ in relevant_scenes)
    silence_points = [
        point
        for silence_start, silence_end in (silence_ranges or [])
        for point in (silence_start, silence_end)
    ]
    clean_boundaries = sum(
        any(abs(boundary - clip_boundary) <= 1.25 for boundary in silence_points)
        for clip_boundary in (start, end)
    )
    factors = {
        "scene_changes": min(1.0, scene_changes / 2),
        "speech_activity": min(1.0, spoken_duration / duration) if duration else 0.0,
        "silence_boundaries": clean_boundaries / 2,
        "sentence_completeness": float(end_marked),
        "beginning_quality": float(bool(first_text) and not start_is_fragment),
        "ending_quality": float(end_marked),
        "interesting_opening": _fractional_score(text[:100], HOOK_TERMS),
        "question_or_answer": float(
            "?" in text
            or any(
                word in text.casefold() for word in ("the answer is", "so that means", "when you")
            )
        ),
        "key_insight": _fractional_score(text, INSIGHT_TERMS),
        "emotional_language": _fractional_score(text, EMOTION_TERMS),
        "standalone_thought": float(
            len(text.split()) >= 8 and text.rstrip().endswith((".", "!", "?"))
        ),
        "pacing": max(0.0, 1.0 - abs(duration - 35.0) / 70.0),
    }
    weights = dict(DEFAULT_RANKING_WEIGHTS)
    if preferences:
        for key in weights:
            value = preferences.get(key)
            if isinstance(value, (int, float)):
                weights[key] = max(0.0, min(3.0, float(value)))
    weight_total = sum(weights.values()) or 1.0
    score = round(100 * sum(factors[key] * weights[key] for key in weights) / weight_total, 1)
    explanations = [
        label
        for key, label in (
            ("scene_changes", "scene change"),
            ("speech_activity", "speech-dense window"),
            ("silence_boundaries", "near a detected silence boundary"),
            ("sentence_completeness", "sentence-ending punctuation"),
            ("beginning_quality", "does not begin with a common conjunction"),
            ("interesting_opening", "contains a configured opening phrase"),
            ("question_or_answer", "question or answer"),
            ("key_insight", "contains configured explanatory language"),
            ("standalone_thought", "complete transcript thought"),
        )
        if factors[key]
    ]
    explanation = (
        ", ".join(explanations)
        if explanations
        else "Heuristic transcript and timing score; no listed signal was detected."
    )
    return score, factors, explanation


def build_candidate_windows(
    segments: list[dict[str, Any]],
    scene_ranges: list[tuple[float, float]],
    silence_ranges: list[tuple[float, float]],
    minimum: float,
    maximum: float,
    source_duration: float,
    target_durations: list[int] | None = None,
) -> list[tuple[list[dict[str, Any]], float, float]]:
    """Build bounded, non-overlapping windows at sentence or detected boundaries."""

    if segments:
        units: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for segment in segments:
            current.append(segment)
            unit_text = " ".join(str(item["text"]).strip() for item in current)
            unit_duration = float(current[-1]["end_seconds"]) - float(current[0]["start_seconds"])
            if re.search(r'[.!?。！？]["\')\]]*$', unit_text) or unit_duration >= 15:
                units.append(current)
                current = []
        if current:
            units.append(current)

        candidates: list[tuple[list[dict[str, Any]], float, float]] = []
        targets = target_durations or [int(maximum)]
        for requested_target in targets:
            target = min(max(float(requested_target), minimum), maximum)
            first = 0
            while first < len(units):
                last = first
                while last < len(units):
                    start = float(units[first][0]["start_seconds"])
                    end = min(float(units[last][-1]["end_seconds"]), source_duration)
                    if end - start >= target:
                        break
                    last += 1
                if last >= len(units):
                    start = float(units[first][0]["start_seconds"])
                    end = min(float(units[-1][-1]["end_seconds"]), source_duration)
                    last = len(units) - 1
                start = float(units[first][0]["start_seconds"])
                end = min(float(units[last][-1]["end_seconds"]), source_duration)
                if minimum <= end - start <= maximum:
                    window = [segment for unit in units[first : last + 1] for segment in unit]
                    candidates.append((window, start, end))
                    first = last + 1
                elif end - start > maximum:
                    first += 1
                else:
                    break
        unique: dict[tuple[float, float], tuple[list[dict[str, Any]], float, float]] = {}
        for candidate in candidates:
            unique[(candidate[1], candidate[2])] = candidate
        return list(unique.values())

    candidates = []
    targets = target_durations or [int(maximum)]
    clean_points = sorted(
        point
        for silence_start, silence_end in silence_ranges
        for point in (silence_start, silence_end)
    )
    for target in targets:
        target = min(max(float(target), minimum), maximum)
        start = 0.0
        while start + minimum <= source_duration:
            proposed_end = min(start + target, source_duration)
            if proposed_end - start < minimum:
                break
            end_candidates = [
                point
                for point in clean_points
                if abs(point - proposed_end) <= 2 and point - start >= minimum
            ]
            end = (
                min(end_candidates, key=lambda point: abs(point - proposed_end))
                if end_candidates
                else proposed_end
            )
            end = min(end, start + maximum, source_duration)
            intersecting_scenes = [
                (scene_start, scene_end)
                for scene_start, scene_end in scene_ranges
                if scene_end > start and scene_start < end
            ]
            candidates.append(([], start, end))
            next_start = end
            nearby_scene_ends = [
                scene_end
                for _, scene_end in intersecting_scenes
                if abs(scene_end - end) <= 1.25 and scene_end < source_duration
            ]
            if nearby_scene_ends:
                next_start = nearby_scene_ends[-1]
            start = max(start + minimum, next_start)
    unique = {(start, end): ([], start, end) for _, start, end in candidates}
    return list(unique.values())


def align_transcript_to_scenes(
    segments: list[dict[str, Any]],
    scenes: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """Attach each transcript segment to the scene with the greatest time overlap."""

    aligned: list[dict[str, Any]] = []
    for segment in segments:
        start = float(segment["start_seconds"])
        end = float(segment["end_seconds"])
        overlaps = [
            (max(0.0, min(end, scene_end) - max(start, scene_start)), index)
            for index, (scene_start, scene_end) in enumerate(scenes)
        ]
        scene_index = max(overlaps)[1] if overlaps and max(overlaps)[0] > 0 else None
        aligned.append({**segment, "scene_index": scene_index})
    return aligned


def detect_scenes_sync(path: Path) -> list[tuple[float, float]]:
    """Use PySceneDetect's content detector to return timestamp boundaries."""

    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(path))
    try:
        manager = SceneManager()
        manager.add_detector(ContentDetector())
        manager.detect_scenes(video=video)
        return [
            (float(start.seconds), float(end.seconds)) for start, end in manager.get_scene_list()
        ]
    finally:
        video.close()


async def detect_silences(
    path: Path,
    duration_seconds: float,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> list[tuple[float, float]]:
    """Detect audio silences with FFmpeg's silencedetect filter."""

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required for silence detection.")
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        str(path),
        "-vn",
        "-af",
        "silencedetect=noise=-35dB:d=0.25",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    ranges: list[tuple[float, float]] = []
    pending_start: float | None = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 900
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RuntimeError("FFmpeg silence detection exceeded its 15-minute time limit.")
            try:
                line = await asyncio.wait_for(
                    process.stderr.readline(),
                    timeout=min(1, remaining),
                )
            except TimeoutError:
                if is_cancelled is not None and await is_cancelled():
                    raise SmartClipJobCancelled
                continue
            if not line:
                break
            message = line.decode("utf-8", errors="replace")
            start_match = re.search(r"silence_start:\s*(-?\d+(?:\.\d+)?)", message)
            if start_match:
                pending_start = max(0.0, float(start_match.group(1)))
            end_match = re.search(r"silence_end:\s*(-?\d+(?:\.\d+)?)", message)
            if end_match and pending_start is not None:
                silence_end = min(duration_seconds, float(end_match.group(1)))
                if silence_end > pending_start:
                    ranges.append((pending_start, silence_end))
                pending_start = None
            if is_cancelled is not None and await is_cancelled():
                raise SmartClipJobCancelled
        return_code = await asyncio.wait_for(
            process.wait(), timeout=max(0.01, deadline - loop.time())
        )
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if return_code:
        logger.warning("FFmpeg silence detection failed with exit status %s.", return_code)
        raise RuntimeError("FFmpeg could not analyze source audio for silences.")
    if pending_start is not None and duration_seconds > pending_start:
        ranges.append((pending_start, duration_seconds))
    return ranges


async def _run_command(arguments: list[str], timeout: float = 900) -> None:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode:
        logger.warning("Smart Clipper media command failed: %s", stderr[-1500:])
        raise RuntimeError("The media tool could not process this source.")


async def _run_command_with_progress(
    arguments: list[str],
    duration_seconds: float,
    progress: Callable[[int], Awaitable[None]],
    timeout: float = 3600,
) -> None:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(process.stderr.read())
    last_progress = -1
    try:
        while line := await asyncio.wait_for(process.stdout.readline(), timeout=timeout):
            key, separator, value = line.decode("utf-8", errors="replace").strip().partition("=")
            if key != "out_time_ms" or not separator:
                continue
            try:
                percent = min(95, int(int(value) / 1_000_000 / duration_seconds * 100))
            except ValueError:
                continue
            if percent >= last_progress + 3:
                last_progress = percent
                await progress(percent)
        return_code = await asyncio.wait_for(process.wait(), timeout=timeout)
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
        logger.warning("Smart Clipper export failed (exit %s): %s", return_code, stderr[-1500:])
        raise RuntimeError("FFmpeg could not render this clip.")


async def _progress(factory: async_sessionmaker[AsyncSession], job_id: UUID, amount: int) -> None:
    async with factory() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is not None and job.cancellation_requested:
            raise SmartClipJobCancelled
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == "processing")
            .values(progress=max(0, min(99, amount)))
        )
        await session.commit()


async def _get_transcript(
    factory: async_sessionmaker[AsyncSession],
    providers: VoiceProviderRegistry,
    asset: MediaAsset,
    project_id: UUID,
    source_path: Path,
    has_audio: bool,
) -> tuple[UUID | None, str]:
    async with factory() as session:
        transcript = await session.scalar(
            select(Transcript)
            .where(
                Transcript.project_id == project_id,
                Transcript.media_asset_id == asset.id,
                Transcript.status == "completed",
            )
            .order_by(Transcript.created_at.desc())
        )
        if transcript is not None:
            return transcript.id, "reused transcript"
    provider = providers.transcription
    if provider is None:
        return None, "unavailable"
    if not has_audio:
        return None, "no audio stream"
    with tempfile.TemporaryDirectory(prefix="ai-creator-clip-audio-") as directory:
        audio_path = Path(directory) / "source.wav"
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("FFmpeg is required to prepare audio for transcription.")
        await _run_command(
            [
                ffmpeg,
                "-nostdin",
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio_path),
            ]
        )
        result = await provider.transcribe(audio_path, None)
    if not result.segments:
        raise RuntimeError("The transcription provider returned no speech segments.")
    transcript = Transcript(
        project_id=project_id,
        media_asset_id=asset.id,
        language=result.language,
        status="completed",
    )
    transcript.segments = [
        TranscriptSegment(
            order_index=index,
            start_seconds=max(0.0, segment.start_seconds),
            end_seconds=max(segment.start_seconds, segment.end_seconds),
            text=segment.text.strip(),
            speaker_label=getattr(segment, "speaker_label", None),
        )
        for index, segment in enumerate(result.segments)
        if segment.text.strip()
    ]
    async with factory() as session:
        session.add(transcript)
        await session.commit()
        await session.refresh(transcript)
        return transcript.id, provider.name


async def _analyze_job(
    factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    providers: VoiceProviderRegistry,
    job_id: UUID,
    owner_id: UUID,
    data: dict[str, Any],
) -> None:
    project_id = UUID(str(data["project_id"]))
    asset_id = UUID(str(data["source_media_asset_id"]))
    async with factory() as session:
        asset = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == asset_id,
                MediaAsset.owner_id == owner_id,
                MediaAsset.project_id == project_id,
                MediaAsset.media_type == "video",
            )
        )
    if asset is None:
        raise RuntimeError("The source video is no longer available to this project.")

    await _progress(factory, job_id, 5)
    async with storage.local_file(asset.storage_key) as source_path:
        if not source_path.is_file():
            raise RuntimeError("The source video is missing from storage.")
        probe = await probe_media(source_path)
        if not probe.get("duration_seconds"):
            raise RuntimeError("FFprobe could not determine the source video duration.")
        async with factory() as session:
            persisted_asset = await session.get(MediaAsset, asset_id)
            if persisted_asset is None or persisted_asset.owner_id != owner_id:
                raise RuntimeError("The source video is no longer available to this project.")
            persisted_asset.duration_seconds = float(probe["duration_seconds"])
            persisted_asset.metadata_json = {
                **(persisted_asset.metadata_json or {}),
                "probe": probe,
            }
            await session.commit()
        scene_ranges = await asyncio.to_thread(detect_scenes_sync, source_path)
        if not scene_ranges:
            scene_ranges = [(0.0, float(probe["duration_seconds"]))]
        await _progress(factory, job_id, 25)
        has_audio = bool(probe.get("audio_streams"))

        async def analysis_cancelled() -> bool:
            async with factory() as session:
                job = await session.get(ProcessingJob, job_id)
                return job is None or job.status != "processing" or job.cancellation_requested

        silence_ranges = (
            await detect_silences(
                source_path,
                float(probe["duration_seconds"]),
                analysis_cancelled,
            )
            if has_audio
            else []
        )
        await _progress(factory, job_id, 36)
        transcript_id, transcript_provider = await _get_transcript(
            factory,
            providers,
            asset,
            project_id,
            source_path,
            has_audio,
        )
        await _progress(factory, job_id, 68)

    async with factory() as session:
        transcript = (
            await session.scalar(
                select(Transcript)
                .options(selectinload(Transcript.segments))
                .where(Transcript.id == transcript_id)
            )
            if transcript_id is not None
            else None
        )
        if transcript_id is not None and transcript is None:
            raise RuntimeError("The source transcript was removed during analysis.")
        segments = (
            [
                {
                    "start_seconds": segment.start_seconds,
                    "end_seconds": segment.end_seconds,
                    "text": segment.text,
                    "speaker_label": segment.speaker_label,
                }
                for segment in transcript.segments
            ]
            if transcript is not None
            else []
        )
        aligned = align_transcript_to_scenes(segments, scene_ranges)
        minimum = float(data.get("minimum_duration_seconds", 15))
        maximum = float(data.get("maximum_duration_seconds", 60))
        requested_targets = data.get("target_durations_seconds")
        target_durations = (
            [int(value) for value in requested_targets if value in {15, 30, 45, 60}]
            if isinstance(requested_targets, list)
            else None
        )
        candidate_windows = build_candidate_windows(
            aligned,
            scene_ranges,
            silence_ranges,
            minimum,
            maximum,
            float(probe["duration_seconds"]),
            target_durations,
        )

        candidates: list[ClipCandidate] = []
        preferences = data.get("ranking_preferences")
        if not isinstance(preferences, dict):
            preferences = None
        for window, start, end in candidate_windows:
            if end <= start:
                continue
            score, factors, explanation = rank_transcript_window(
                window,
                preferences,
                clip_start=start,
                clip_end=end,
                scene_ranges=scene_ranges,
                silence_ranges=silence_ranges,
            )
            caption_data = [
                {
                    "start_seconds": max(start, float(segment["start_seconds"])),
                    "end_seconds": min(end, float(segment["end_seconds"])),
                    "text": str(segment["text"]),
                    "speaker_label": segment.get("speaker_label"),
                    "highlighted_words": [],
                }
                for segment in window
            ]
            candidate = ClipCandidate(
                project_id=project_id,
                source_asset_id=asset_id,
                start_seconds=start,
                end_seconds=end,
                score=score,
                scoring_factors=factors,
                scene_ranges=[
                    {
                        "scene_index": scene_index,
                        "start_seconds": scene_start,
                        "end_seconds": scene_end,
                    }
                    for scene_index, (scene_start, scene_end) in enumerate(scene_ranges)
                    if scene_end > start and scene_start < end
                ],
                explanation=explanation,
                status="candidate",
                transcript_text=" ".join(str(segment["text"]).strip() for segment in window)
                or None,
                caption_data=caption_data or None,
                framing_data={"aspect_ratio": "9:16", "position_x": 0.5, "position_y": 0.5},
            )
            candidates.append(candidate)
        session.add_all(candidates)
        await session.flush()
        job = await session.get(ProcessingJob, job_id)
        if job is None:
            raise RuntimeError("The analysis job disappeared.")
        job.output_data = {
            "source_media_asset_id": str(asset_id),
            "probe": probe,
            "scene_changes": [
                {"start_seconds": start, "end_seconds": end} for start, end in scene_ranges
            ],
            "silence_ranges": [
                {"start_seconds": start, "end_seconds": end} for start, end in silence_ranges
            ],
            "transcript_id": str(transcript_id) if transcript_id else None,
            "candidate_ids": [str(candidate.id) for candidate in candidates],
            "transcript_provider": transcript_provider,
            "candidate_count": len(candidates),
            "analysis_mode": "transcript" if transcript_id else "scene_and_silence",
            "word_timestamps_available": False,
            "note": None
            if candidates
            else "No candidate windows meet the selected duration range.",
        }
        job.status = "completed"
        job.progress = 100
        await session.commit()


def _subtitle_timestamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    whole, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{whole:02},{ms:03}"


def _make_srt(captions: list[dict[str, Any]], start_seconds: float) -> str:
    lines: list[str] = []
    for index, caption in enumerate(captions, start=1):
        text = str(caption.get("text", "")).strip()
        start = float(caption.get("start_seconds", start_seconds)) - start_seconds
        end = float(caption.get("end_seconds", start_seconds)) - start_seconds
        if not text or start < 0 or end <= start:
            continue
        lines.extend(
            [
                str(index),
                f"{_subtitle_timestamp(start)} --> {_subtitle_timestamp(end)}",
                text.replace("-->", "—>"),
                "",
            ]
        )
    return "\n".join(lines)


def _render_caption_card(
    path: Path,
    width: int,
    height: int,
    text: str,
    options: dict[str, Any],
) -> int:
    """Render one styled segment-level caption to a transparent PNG card."""

    scale = height / 1080
    font_size = max(14, round(int(options.get("caption_font_size", 36)) * scale))
    font_candidates = (
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )
    font_path = next((candidate for candidate in font_candidates if candidate.is_file()), None)
    font = (
        ImageFont.truetype(str(font_path), font_size)
        if font_path
        else ImageFont.load_default(size=font_size)
    )
    image = Image.new("RGBA", (width, 8), (0, 0, 0, 0))
    measure = ImageDraw.Draw(image)
    padding_x = max(12, round(font_size * 0.6))
    padding_y = max(8, round(font_size * 0.3))
    max_text_width = round(width * 0.86) - padding_x * 2
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and measure.textlength(candidate, font=font) > max_text_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if not lines:
        lines = [text]
    line_height = font_size + max(4, round(font_size * 0.28))
    card_height = len(lines) * line_height + padding_y * 2
    if card_height > height // 3:
        raise RuntimeError(
            "A caption segment is too long to render; split it into smaller timed captions."
        )
    image = Image.new("RGBA", (width, card_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    theme = options.get("caption_theme", "boxed")
    background = str(options.get("caption_background_color", "#000000"))
    outline = str(options.get("caption_outline_color", "#000000"))
    foreground = str(options.get("caption_color", "#FFFFFF"))
    if theme == "boxed":
        background_rgb = tuple(bytes.fromhex(background.lstrip("#")))
        draw.rounded_rectangle(
            (round(width * 0.04), 0, round(width * 0.96), card_height - 1),
            radius=max(4, round(font_size * 0.25)),
            fill=(*background_rgb, 190),
        )
    stroke_width = max(1, round(font_size / 14)) if theme != "minimal" else 0
    stroke_rgb = tuple(bytes.fromhex(outline.lstrip("#")))
    foreground_rgb = tuple(bytes.fromhex(foreground.lstrip("#")))
    for index, caption_line in enumerate(lines):
        draw.text(
            (width / 2, padding_y + index * line_height),
            caption_line,
            font=font,
            anchor="mt",
            align="center",
            fill=(*foreground_rgb, 255),
            stroke_width=stroke_width,
            stroke_fill=(*stroke_rgb, 255),
        )
    image.save(path)
    return card_height


def _create_watermark_overlay(path: Path, width: int, height: int, text: str) -> None:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    font = ImageFont.load_default(size=max(18, round(width * 0.026)))
    draw = ImageDraw.Draw(image)
    bounds = draw.textbbox((0, 0), text, font=font, stroke_width=1)
    padding = max(10, round(width * 0.012))
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    left = max(0, width - text_width - padding * 3)
    top = max(0, height - text_height - padding * 3)
    draw.rounded_rectangle(
        (left, top, width - padding, height - padding),
        radius=padding,
        fill=(0, 0, 0, 120),
    )
    draw.text(
        (left + padding, top + padding),
        text,
        font=font,
        fill=(255, 255, 255, 230),
        stroke_width=1,
        stroke_fill=(0, 0, 0, 180),
    )
    image.save(path)


async def _render_candidate(
    source_path: Path,
    output_path: Path,
    candidate: ClipCandidate,
    options: dict[str, Any],
    on_progress: Callable[[int], Awaitable[None]] | None = None,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required to export Smart Clipper videos.")
    start = max(0.0, candidate.start_seconds)
    duration = candidate.end_seconds - start
    if duration <= 0 or duration > 600:
        raise RuntimeError("The clip has invalid boundaries.")
    ratio = options.get("aspect_ratio", "9:16")
    dimensions = {
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "16:9": (1920, 1080),
    }
    if ratio not in dimensions:
        raise RuntimeError("Unsupported output aspect ratio.")
    width, height = dimensions[ratio]
    resolution = options.get("resolution", "1080p")
    if resolution not in {"720p", "1080p"}:
        raise RuntimeError("Unsupported output resolution.")
    if resolution == "720p":
        width = round(width * 2 / 3)
        height = round(height * 2 / 3)
    framing = candidate.framing_data or {}
    x = max(0.0, min(1.0, float(framing.get("position_x", 0.5))))
    y = max(0.0, min(1.0, float(framing.get("position_y", 0.5))))
    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}:(iw-ow)*{x:.4f}:(ih-oh)*{y:.4f}",
        "setsar=1",
    ]
    with tempfile.TemporaryDirectory(prefix="ai-creator-caption-") as directory:
        captions_enabled = bool(options.get("captions"))
        caption_data = candidate.caption_data or []
        if captions_enabled and not caption_data:
            raise RuntimeError("Caption export was selected, but this clip has no timed captions.")
        command = [
            ffmpeg,
            "-nostdin",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(source_path),
        ]
        next_input = 1
        subtitle_input: int | None = None
        caption_overlays: list[tuple[int, float, float, int]] = []
        if captions_enabled:
            subtitle_path = Path(directory) / "captions.srt"
            subtitle_path.write_text(_make_srt(caption_data, start), encoding="utf-8")
            command.extend(["-i", str(subtitle_path)])
            subtitle_input = next_input
            next_input += 1
            for index, caption in enumerate(caption_data):
                text = str(caption.get("text", "")).strip()
                caption_start = float(caption.get("start_seconds", start)) - start
                caption_end = float(caption.get("end_seconds", start)) - start
                if not text or caption_end <= caption_start:
                    continue
                caption_path = Path(directory) / f"caption-{index}.png"
                card_height = _render_caption_card(
                    caption_path,
                    width,
                    height,
                    text,
                    options,
                )
                command.extend(
                    [
                        "-loop",
                        "1",
                        "-framerate",
                        "30",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        str(caption_path),
                    ]
                )
                caption_overlays.append((next_input, caption_start, caption_end, card_height))
                next_input += 1
        watermark = options.get("watermark")
        watermark_input: int | None = None
        if isinstance(watermark, str) and watermark.strip():
            watermark_path = Path(directory) / "watermark.png"
            _create_watermark_overlay(watermark_path, width, height, watermark.strip()[:100])
            command.extend(["-loop", "1", "-framerate", "30", "-i", str(watermark_path)])
            watermark_input = next_input
        if watermark_input is not None or caption_overlays:
            graph = [f"[0:v]{','.join(filters)}[base]"]
            current_label = "base"
            if watermark_input is not None:
                graph.append(
                    f"[{current_label}][{watermark_input}:v]overlay=0:0:shortest=1[watermarked]"
                )
                current_label = "watermarked"
            position = options.get("caption_position", "bottom")
            for index, (input_index, caption_start, caption_end, card_height) in enumerate(
                caption_overlays
            ):
                if position == "top":
                    y = "main_h*0.08"
                elif position == "center":
                    y = "(main_h-overlay_h)/2"
                else:
                    y = "main_h-overlay_h-main_h*0.08"
                output_label = f"captioned{index}"
                graph.append(
                    f"[{current_label}][{input_index}:v]overlay=x=0:y={y}:"
                    f"eof_action=pass:shortest=0:"
                    f"enable='between(t,{caption_start:.3f},{caption_end:.3f})'"
                    f"[{output_label}]"
                )
                current_label = output_label
            command.extend(
                [
                    "-filter_complex",
                    ";".join(graph),
                    "-map",
                    f"[{current_label}]",
                ]
            )
        else:
            command.extend(["-vf", ",".join(filters), "-map", "0:v:0"])
        command.extend(["-map", "0:a?"])
        if subtitle_input is not None:
            command.extend(["-map", f"{subtitle_input}:s:0?"])
        command.extend(
            [
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "21",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
            ]
        )
        if subtitle_input is not None:
            command.extend(["-c:s", "mov_text"])
        command.extend(["-movflags", "+faststart"])
        if on_progress is not None:
            command.extend(["-progress", "pipe:1", "-nostats"])
        command.append(str(output_path))
        if on_progress is not None:
            await _run_command_with_progress(command, duration, on_progress)
        else:
            await _run_command(command, timeout=3600)


async def _export_job(
    factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    job_id: UUID,
    owner_id: UUID,
    data: dict[str, Any],
) -> None:
    candidate_ids = [UUID(str(value)) for value in data.get("candidate_ids", [])]
    options = data.get("options", {})
    if not candidate_ids:
        raise RuntimeError("The export job has no approved clips.")
    generated_keys: list[str] = []
    created_asset_ids: list[UUID] = []
    try:
        for index, candidate_id in enumerate(candidate_ids):
            async with factory() as session:
                job = await session.get(ProcessingJob, job_id)
                candidate = await session.scalar(
                    select(ClipCandidate)
                    .join(Project, Project.id == ClipCandidate.project_id)
                    .where(ClipCandidate.id == candidate_id, Project.owner_id == owner_id)
                )
                if job is None or job.status != "processing":
                    raise SmartClipJobCancelled
                if job.cancellation_requested:
                    raise SmartClipJobCancelled
                if candidate is None or candidate.status != "approved":
                    raise RuntimeError("One of the selected clips is no longer approved.")
                source = await session.get(MediaAsset, candidate.source_asset_id)
                if (
                    source is None
                    or source.owner_id != owner_id
                    or source.project_id != candidate.project_id
                ):
                    raise RuntimeError("A selected clip source is no longer accessible.")
                source_key = source.storage_key
                project_id = candidate.project_id
                candidate_snapshot = candidate
            with tempfile.TemporaryDirectory(prefix="ai-creator-clip-export-") as directory:
                output_path = Path(directory) / f"{candidate_id}.mp4"
                async with storage.local_file(source_key) as source_path:
                    if not source_path.is_file():
                        raise RuntimeError("The source video is missing from storage.")

                    async def report_render_progress(
                        percent: int, candidate_index: int = index
                    ) -> None:
                        fraction = (candidate_index + percent / 100) / len(candidate_ids)
                        await _progress(factory, job_id, 5 + int(fraction * 85))

                    await _render_candidate(
                        source_path,
                        output_path,
                        candidate_snapshot,
                        options,
                        report_render_progress,
                    )
                storage_key = (
                    f"users/{owner_id}/projects/{project_id}/clips/{job_id}-{candidate_id}.mp4"
                )

                async def chunks(path: Path = output_path):
                    with path.open("rb") as file:
                        while chunk := await asyncio.to_thread(file.read, 1024 * 1024):
                            yield chunk

                size = await storage.save_stream(storage_key, chunks())
            generated_keys.append(storage_key)
            async with factory() as session:
                asset = MediaAsset(
                    owner_id=owner_id,
                    project_id=project_id,
                    name=f"Short clip {candidate_id}.mp4",
                    storage_key=storage_key,
                    media_type="video",
                    content_type="video/mp4",
                    file_size=size,
                    duration_seconds=candidate_snapshot.end_seconds
                    - candidate_snapshot.start_seconds,
                    metadata_json={
                        "origin": "smart_clipper_export",
                        "clip_candidate_id": str(candidate_id),
                        "processing_job_id": str(job_id),
                        "aspect_ratio": options.get("aspect_ratio", "9:16"),
                        "captions": bool(options.get("captions")),
                        "caption_style": {
                            "position": options.get("caption_position", "bottom"),
                            "theme": options.get("caption_theme", "boxed"),
                            "font_size": options.get("caption_font_size", 36),
                            "color": options.get("caption_color", "#FFFFFF"),
                            "background_color": options.get("caption_background_color", "#000000"),
                            "outline_color": options.get("caption_outline_color", "#000000"),
                            "burned_in": bool(options.get("captions")),
                            "note": "A styled caption overlay is burned into the image; an additional selectable subtitle track is included.",
                        },
                    },
                )
                session.add(asset)
                await session.flush()
                created_asset_ids.append(asset.id)
                persisted_candidate = await session.get(ClipCandidate, candidate_id)
                job = await session.get(ProcessingJob, job_id)
                if persisted_candidate is not None:
                    persisted_candidate.exported_media_asset_id = asset.id
                if job is not None:
                    job.progress = int((index + 1) / len(candidate_ids) * 95)
                    job.output_data = {
                        "completed": index + 1,
                        "total": len(candidate_ids),
                        "media_asset_ids": [str(value) for value in created_asset_ids],
                    }
                await session.commit()
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None and job.status == "processing":
                job.status = "completed"
                job.progress = 100
                job.output_data = {
                    "completed": len(created_asset_ids),
                    "total": len(candidate_ids),
                    "media_asset_ids": [str(value) for value in created_asset_ids],
                }
                await session.commit()
    except BaseException:
        await _cleanup_exports(factory, storage, generated_keys, created_asset_ids)
        raise


async def _cleanup_exports(
    factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    keys: list[str],
    asset_ids: list[UUID],
) -> None:
    for key in keys:
        await storage.delete(key)
    if asset_ids:
        async with factory() as session:
            assets = await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))
            for asset in assets:
                await session.delete(asset)
            candidates = await session.scalars(
                select(ClipCandidate).where(ClipCandidate.exported_media_asset_id.in_(asset_ids))
            )
            for candidate in candidates:
                candidate.exported_media_asset_id = None
            await session.commit()


async def _process_job(
    factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    providers: VoiceProviderRegistry,
    job_id: UUID,
    owner_id: UUID,
    job_type: str,
    data: dict[str, Any],
) -> None:
    try:
        if job_type == "smart_clip_analysis":
            await _analyze_job(factory, storage, providers, job_id, owner_id, data)
        elif job_type == "smart_clip_export":
            await _export_job(factory, storage, job_id, owner_id, data)
        else:
            raise RuntimeError("Unsupported Smart Clipper job.")
    except SmartClipJobCancelled:
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "cancelled"
                job.cancellation_requested = False
                await session.commit()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Smart Clipper job %s failed", job_id)
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None and job.status == "processing":
                job.status = "failed"
                job.error_message = str(error)[:1000]
                await session.commit()


async def run_smart_clipper_worker(
    factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    providers: VoiceProviderRegistry,
    poll_interval: float = 0.5,
) -> None:
    """Claim analysis and batch-export jobs using the existing persisted job table."""

    while True:
        async with factory() as session:
            job = await session.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.job_type.in_(("smart_clip_analysis", "smart_clip_export")),
                    ProcessingJob.status == "queued",
                )
                .order_by(ProcessingJob.created_at, ProcessingJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                await session.rollback()
            else:
                job.status = "processing"
                job.progress = 1
                job_id = job.id
                owner_id = job.owner_id
                job_type = job.job_type
                data = dict(job.input_data or {})
                await session.commit()
                await _process_job(factory, storage, providers, job_id, owner_id, job_type, data)
        await asyncio.sleep(poll_interval)
