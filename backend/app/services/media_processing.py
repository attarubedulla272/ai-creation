"""FFprobe/FFmpeg processing and a lightweight persisted media-job worker."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import shutil
import tempfile
from collections.abc import AsyncIterable, Awaitable, Callable
from contextlib import suppress
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.services.storage import StorageService

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int], Awaitable[None]]
CancellationCheck = Callable[[], Awaitable[bool]]


class MediaJobCancelled(Exception):
    """Raised when an owner requests cancellation of a media job."""


async def probe_media(
    path: Path,
    is_cancelled: CancellationCheck | None = None,
) -> dict[str, Any]:
    """Read media duration, streams, codecs, dimensions, and frame rate."""

    executable = shutil.which("ffprobe")
    if executable is None:
        raise RuntimeError("FFprobe is not installed or is not on PATH.")
    process = await asyncio.create_subprocess_exec(
        executable,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        if is_cancelled is None:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        else:
            communication = asyncio.create_task(process.communicate())
            deadline = asyncio.get_running_loop().time() + 120
            while not communication.done():
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise RuntimeError("FFprobe exceeded its 120-second time limit.")
                await asyncio.wait({communication}, timeout=min(1, remaining))
                if await is_cancelled():
                    raise MediaJobCancelled
            stdout, stderr = communication.result()
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        if "communication" in locals():
            with suppress(Exception, asyncio.CancelledError):
                await communication
        raise
    if process.returncode:
        logger.warning("FFprobe rejected media (exit %s): %s", process.returncode, stderr[:1000])
        raise RuntimeError("FFprobe could not read this media file.")

    result = json.loads(stdout)
    format_data = result.get("format", {})
    streams = result.get("streams", [])
    duration = _positive_float(format_data.get("duration"))
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    video = video_streams[0] if video_streams else {}
    frame_rate = _frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    return {
        "duration_seconds": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": frame_rate,
        "video_codec": video.get("codec_name"),
        "audio_streams": [
            {"codec": stream.get("codec_name"), "channels": stream.get("channels")}
            for stream in audio_streams
        ],
        "format_name": format_data.get("format_name"),
    }


def _positive_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or value in {"0/0", "N/A"}:
        return None
    try:
        rate = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


async def _run_ffmpeg(
    arguments: list[str],
    duration: float | None,
    on_progress: ProgressCallback,
    is_cancelled: CancellationCheck | None = None,
) -> None:
    """Run FFmpeg without a shell and parse its machine-readable progress output."""

    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("FFmpeg is not installed or is not on PATH.")
    process = await asyncio.create_subprocess_exec(
        executable,
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(process.stderr.read())
    last_progress = -1
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 7200
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RuntimeError("FFmpeg exceeded its two-hour time limit.")
            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=min(1, remaining) if is_cancelled is not None else remaining,
                )
            except TimeoutError:
                if loop.time() >= deadline:
                    raise RuntimeError("FFmpeg exceeded its two-hour time limit.")
                if is_cancelled is not None and await is_cancelled():
                    raise MediaJobCancelled
                continue
            if not line:
                break
            if is_cancelled is not None and line.startswith(b"progress=") and await is_cancelled():
                raise MediaJobCancelled
            key, separator, value = line.decode("utf-8", errors="replace").strip().partition("=")
            if separator and key == "out_time_ms" and duration:
                try:
                    percent = min(94, int(int(value) / 1_000_000 / duration * 100))
                except ValueError:
                    continue
                if percent >= last_progress + 5:
                    last_progress = percent
                    await on_progress(percent)
        return_code = await asyncio.wait_for(process.wait(), timeout=7200)
        stderr = await stderr_task
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        stderr_task.cancel()
        with suppress(asyncio.CancelledError):
            await stderr_task
        raise
    if return_code:
        logger.warning("FFmpeg failed (exit %s): %s", return_code, stderr[-2000:])
        raise RuntimeError("FFmpeg could not process this media file.")


async def _create_derivatives(
    *,
    asset_id: UUID,
    owner_id: UUID,
    media_type: str,
    source: Path,
    output_directory: Path,
    probe: dict[str, Any],
    progress: ProgressCallback,
    is_cancelled: CancellationCheck,
) -> dict[str, tuple[str, Path]]:
    derivatives: dict[str, tuple[str, Path]] = {}
    duration = probe["duration_seconds"]
    prefix = f"{owner_id}/{asset_id}"

    if media_type in {"video", "image"}:
        thumbnail_key = f"{prefix}.thumbnail.jpg"
        thumbnail = output_directory / "thumbnail.jpg"
        seek_seconds = min(2, max(0, (duration or 0) * 0.1))
        await _run_ffmpeg(
            [
                "-y",
                "-ss",
                f"{seek_seconds:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(640,iw)':-2",
                "-q:v",
                "3",
                "-progress",
                "pipe:1",
                "-nostats",
                str(thumbnail),
            ],
            duration,
            progress,
            is_cancelled,
        )
        derivatives["thumbnail"] = (thumbnail_key, thumbnail)

    if media_type == "video":
        proxy_key = f"{prefix}.proxy.mp4"
        proxy = output_directory / "proxy.mp4"
        await _run_ffmpeg(
            [
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                "scale='min(1280,iw)':-2",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "30",
                "-threads",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-nostats",
                str(proxy),
            ],
            duration,
            progress,
            is_cancelled,
        )
        derivatives["proxy"] = (proxy_key, proxy)

    if media_type == "video" and probe["audio_streams"]:
        audio_key = f"{prefix}.audio.m4a"
        audio = output_directory / "extracted-audio.m4a"
        await _run_ffmpeg(
            [
                "-y",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-progress",
                "pipe:1",
                "-nostats",
                str(audio),
            ],
            duration,
            progress,
            is_cancelled,
        )
        derivatives["extracted_audio"] = (audio_key, audio)

    if media_type == "audio" or (media_type == "video" and probe["audio_streams"]):
        waveform_key = f"{prefix}.waveform.png"
        waveform = output_directory / "waveform.png"
        waveform_input = source
        waveform_args = [
            "-y",
            "-i",
            str(waveform_input),
            "-filter_complex",
            "showwavespic=s=1200x240:colors=0x8B5CF6",
            "-frames:v",
            "1",
            "-update",
            "1",
            "-an",
            "-progress",
            "pipe:1",
            "-nostats",
            str(waveform),
        ]
        if media_type == "video":
            waveform_args[3:3] = ["-map", "0:a:0"]
        await _run_ffmpeg(waveform_args, duration, progress, is_cancelled)
        derivatives["waveform"] = (waveform_key, waveform)

    return derivatives


async def _read_file_chunks(
    path: Path,
    is_cancelled: CancellationCheck | None = None,
) -> AsyncIterable[bytes]:
    handle = await asyncio.to_thread(path.open, "rb")
    try:
        while chunk := await asyncio.to_thread(handle.read, 1024 * 1024):
            if is_cancelled is not None and await is_cancelled():
                raise MediaJobCancelled
            yield chunk
    finally:
        await asyncio.to_thread(handle.close)


async def _set_job_progress(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
    progress: int,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == "processing")
            .values(
                progress=case(
                    (ProcessingJob.progress < progress, progress),
                    else_=ProcessingJob.progress,
                )
            )
        )
        await session.commit()


async def _process_job(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    job_id: UUID,
) -> None:
    generated_keys: list[str] = []

    async def is_cancelled() -> bool:
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            return job is None or job.status != "processing" or job.cancellation_requested

    try:
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                return
            asset_id = UUID(str(job.input_data["media_asset_id"]))
            asset = await session.get(MediaAsset, asset_id)
            if asset is None:
                raise RuntimeError("The uploaded media asset no longer exists.")
            source_key = asset.storage_key
            owner_id = asset.owner_id
            media_type = asset.media_type

        asset_id = UUID(str(asset_id))
        async with storage.local_file(source_key) as source:
            if not source.is_file():
                raise RuntimeError("The uploaded media file is missing from storage.")
            await _set_job_progress(session_factory, job_id, 5)
            probe = await probe_media(source, is_cancelled)
            if await is_cancelled():
                raise MediaJobCancelled
            await _set_job_progress(session_factory, job_id, 15)

            async def report_progress(value: int) -> None:
                if await is_cancelled():
                    raise MediaJobCancelled
                await _set_job_progress(
                    session_factory,
                    job_id,
                    max(15, min(90, 15 + int(value * 0.75))),
                )

            with tempfile.TemporaryDirectory(prefix="ai-creator-media-") as temporary_directory:
                generated = await _create_derivatives(
                    asset_id=asset_id,
                    owner_id=owner_id,
                    media_type=media_type,
                    source=source,
                    output_directory=Path(temporary_directory),
                    probe=probe,
                    progress=report_progress,
                    is_cancelled=is_cancelled,
                )
                derivatives = {kind: key for kind, (key, _) in generated.items()}
                for key, path in generated.values():
                    if await is_cancelled():
                        raise MediaJobCancelled
                    await storage.save_stream(key, _read_file_chunks(path, is_cancelled))
                    generated_keys.append(key)
        if await is_cancelled():
            raise MediaJobCancelled
        async with session_factory() as session:
            asset = await session.get(MediaAsset, asset_id)
            if asset is None:
                raise RuntimeError("The uploaded media asset no longer exists.")
            asset.duration_seconds = probe["duration_seconds"]
            asset.metadata_json = {
                "probe": probe,
                "derivatives": derivatives,
                "processing_job_id": str(job_id),
            }
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                raise RuntimeError("The processing job no longer exists.")
            job.status = "completed"
            job.progress = 100
            job.output_data = {"media_asset_id": str(asset_id), "derivatives": derivatives}
            job.error_message = None
            await session.commit()
        logger.info("Media processing completed for asset %s (%s)", asset_id, media_type)
    except MediaJobCancelled:
        await _cleanup_generated(storage, generated_keys)
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "cancelled"
                job.error_message = "Media processing was cancelled."
                await session.commit()
    except asyncio.CancelledError:
        await _cleanup_generated(storage, generated_keys)
        try:
            async with session_factory() as session:
                job = await session.get(ProcessingJob, job_id)
                if job is not None:
                    job.status = "failed"
                    job.error_message = "Media processing was interrupted during shutdown."
                    await session.commit()
        except Exception:
            logger.exception("Could not mark interrupted media job %s as failed", job_id)
        raise
    except Exception as error:
        logger.exception("Media processing job %s failed", job_id)
        await _cleanup_generated(storage, generated_keys)
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "failed"
                if isinstance(error, OSError) and error.errno == errno.ENOSPC:
                    job.error_message = "Insufficient disk space to process this media file."
                elif isinstance(error, RuntimeError) and "FFprobe could not read" in str(error):
                    job.error_message = (
                        "The media file is invalid or uses an unsupported container or codec."
                    )
                elif isinstance(error, RuntimeError) and "FFmpeg could not process" in str(error):
                    job.error_message = (
                        "FFmpeg could not process this media file. It may be corrupt or use an "
                        "unsupported codec."
                    )
                elif isinstance(error, RuntimeError) and "two-hour time limit" in str(error):
                    job.error_message = "Media processing exceeded its two-hour time limit."
                else:
                    job.error_message = (
                        "Media processing failed. Verify the file and FFmpeg installation."
                    )
                await session.commit()


async def _cleanup_generated(storage: StorageService, keys: list[str]) -> None:
    for key in keys:
        try:
            await storage.delete(key)
        except OSError:
            logger.exception("Could not clean generated media file %s", key)


async def run_media_worker(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
) -> None:
    """Claim queued media jobs one at a time and persist their progress."""

    while True:
        try:
            async with session_factory() as session:
                job_id = await session.scalar(
                    select(ProcessingJob.id)
                    .where(
                        ProcessingJob.status == "queued", ProcessingJob.job_type == "media_process"
                    )
                    .order_by(ProcessingJob.created_at, ProcessingJob.id)
                    .limit(1)
                )
                if job_id is not None:
                    result = await session.execute(
                        update(ProcessingJob)
                        .where(ProcessingJob.id == job_id, ProcessingJob.status == "queued")
                        .values(status="processing", progress=1)
                    )
                    await session.commit()
                    if result.rowcount == 1:
                        await _process_job(session_factory, storage, job_id)
                        continue
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Media worker iteration failed")
            await asyncio.sleep(2)
