"""Asynchronous transcription and user-supplied dubbing audio assembly."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.transcript import Transcript, TranscriptSegment
from app.models.dubbing_project import DubbingProject
from app.services.storage import StorageService
from app.services.voice_providers import (
    MlxAudioPlusWorkerTranscriptionProvider,
    VoiceProviderRegistry,
)

logger = logging.getLogger(__name__)


async def _save_file(storage: StorageService, key: str, path: Path) -> int:
    async def chunks() -> AsyncIterable[bytes]:
        with path.open("rb") as file:
            while chunk := await asyncio.to_thread(file.read, 1024 * 1024):
                yield chunk

    return await storage.save_stream(key, chunks())


async def _run_ffmpeg(arguments: list[str], timeout: float = 600) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("FFmpeg is required to assemble supplied dubbing audio.")
    process = await asyncio.create_subprocess_exec(
        executable,
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("Dubbing audio export exceeded its time limit.") from None
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        logger.warning(
            "FFmpeg dubbing assembly failed (exit %s): %s", process.returncode, stderr[-2000:]
        )
        raise RuntimeError("FFmpeg could not assemble the supplied audio segments.")


async def _transcribe_job(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    providers: VoiceProviderRegistry,
    job_id: UUID,
    owner_id: UUID,
    data: dict[str, Any],
) -> None:
    provider = providers.transcription
    if provider is None:
        raise RuntimeError("No compatible local transcription provider is installed.")
    source_key = data.get("source_storage_key")
    project_id = data.get("project_id")
    media_asset_id = data.get("media_asset_id")
    if not all(isinstance(value, str) for value in (source_key, project_id, media_asset_id)):
        raise RuntimeError("The transcription job is missing its source references.")
    language = data.get("language")
    if not isinstance(language, str):
        language = None

    await _set_job_progress(session_factory, job_id, 5)
    started = time.perf_counter()

    async def report_worker_progress(progress: int) -> None:
        await _set_job_progress(
            session_factory,
            job_id,
            5 + round(progress * 0.9),
        )

    async with storage.local_file(source_key) as source_path:
        if isinstance(provider, MlxAudioPlusWorkerTranscriptionProvider):
            result = await provider.transcribe(
                source_path,
                language,
                on_progress=report_worker_progress,
            )
        else:
            result = await provider.transcribe(source_path, language)
    elapsed_seconds = time.perf_counter() - started
    if not result.segments:
        raise RuntimeError("No speech segments were recognized in the supplied audio.")

    async with session_factory() as session:
        transcript = Transcript(
            project_id=UUID(project_id),
            media_asset_id=UUID(media_asset_id),
            language=result.language,
            status="completed",
        )
        transcript.segments = [
            TranscriptSegment(
                order_index=index,
                start_seconds=max(0.0, segment.start_seconds),
                end_seconds=max(segment.start_seconds, segment.end_seconds),
                text=segment.text.strip(),
            )
            for index, segment in enumerate(result.segments)
            if segment.text.strip()
        ]
        session.add(transcript)
        await session.flush()
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.owner_id == owner_id)
            .values(
                status="completed",
                progress=100,
                output_data={
                    "transcript_id": str(transcript.id),
                    "provider": provider.name,
                    "elapsed_seconds": elapsed_seconds,
                    "metrics": result.metrics or {},
                },
                error_message=None,
            )
        )
        await session.commit()


async def _translate_job(
    session_factory: async_sessionmaker[AsyncSession],
    providers: VoiceProviderRegistry,
    job_id: UUID,
    owner_id: UUID,
    data: dict[str, Any],
) -> None:
    provider = providers.translation
    if provider is None:
        raise RuntimeError("The optional local translation worker is not configured.")
    project_id = data.get("dubbing_project_id")
    segment_ids = data.get("segment_ids")
    source_language = data.get("source_language")
    target_language = data.get("target_language")
    glossary = data.get("glossary", [])
    if (
        not isinstance(project_id, str)
        or not isinstance(segment_ids, list)
        or not segment_ids
        or not all(isinstance(item, str) for item in segment_ids)
        or not isinstance(source_language, str)
        or not isinstance(target_language, str)
        or not isinstance(glossary, list)
    ):
        raise RuntimeError("The translation job input is invalid.")

    project_uuid = UUID(project_id)
    selected_ids = set(segment_ids)
    async with session_factory() as session:
        project = await session.scalar(
            select(DubbingProject)
            .where(DubbingProject.id == project_uuid, DubbingProject.owner_id == owner_id)
            .with_for_update()
        )
        if project is None or project.target_language != target_language:
            raise RuntimeError("The translation job references an unavailable dubbing project.")
        segments = [dict(item) for item in project.segments_data]
        selected = [
            item
            for item in segments
            if str(item.get("id")) in selected_ids and item.get("translation_status") == "queued"
        ]
        if len(selected) != len(selected_ids):
            raise RuntimeError(
                "The translation job contains stale or duplicate segment references."
            )

    completed: list[str] = []
    model_records: dict[tuple[str, str], dict[str, str]] = {}
    failures: list[str] = []
    total = len(selected)
    try:
        for index, item in enumerate(selected):
            segment_id = str(item["id"])
            try:
                result = await provider.translate(
                    str(item["source_text"]),
                    source_language,
                    target_language,
                    glossary,
                )
                if not result.text.strip():
                    raise RuntimeError("The translation provider returned empty text.")
                async with session_factory() as session:
                    project = await session.scalar(
                        select(DubbingProject)
                        .where(
                            DubbingProject.id == project_uuid, DubbingProject.owner_id == owner_id
                        )
                        .with_for_update()
                    )
                    if project is None:
                        raise RuntimeError("The dubbing project was removed during translation.")
                    current_segments = [dict(value) for value in project.segments_data]
                    current = next(
                        (value for value in current_segments if str(value.get("id")) == segment_id),
                        None,
                    )
                    if (
                        current is None
                        or current.get("source_text") != item.get("source_text")
                        or current.get("translation_status") != "queued"
                    ):
                        raise RuntimeError(
                            "The source segment changed or was edited while translation was running."
                        )
                    current.update(
                        translated_text=result.text,
                        translation_status="completed",
                        translation_provider=result.provider,
                        translation_model=result.model,
                        translation_model_version=result.model_version,
                        translation_model_license=result.model_license,
                        translation_error=None,
                        translation_approved=False,
                        segment_approved=False,
                    )
                    project.segments_data = current_segments
                    await session.commit()
                completed.append(segment_id)
                model_records[(result.model, result.model_version)] = {
                    "model": result.model,
                    "version": result.model_version,
                    "license": result.model_license,
                }
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Translation failed for dubbing segment %s", segment_id)
                failures.append(segment_id)
                async with session_factory() as session:
                    project = await session.scalar(
                        select(DubbingProject)
                        .where(
                            DubbingProject.id == project_uuid, DubbingProject.owner_id == owner_id
                        )
                        .with_for_update()
                    )
                    if project is not None:
                        current_segments = [dict(value) for value in project.segments_data]
                        current = next(
                            (
                                value
                                for value in current_segments
                                if str(value.get("id")) == segment_id
                            ),
                            None,
                        )
                        if (
                            current is not None
                            and current.get("source_text") == item.get("source_text")
                            and current.get("translation_status") == "queued"
                        ):
                            current.update(
                                translation_status="failed",
                                translation_error="Translation failed; retry this segment.",
                                translation_approved=False,
                            )
                            project.segments_data = current_segments
                            await session.commit()
            await _set_job_progress(session_factory, job_id, 10 + round((index + 1) * 85 / total))
    except asyncio.CancelledError:
        async with session_factory() as session:
            project = await session.scalar(
                select(DubbingProject)
                .where(DubbingProject.id == project_uuid, DubbingProject.owner_id == owner_id)
                .with_for_update()
            )
            if project is not None:
                current_segments = [dict(value) for value in project.segments_data]
                for current in current_segments:
                    if (
                        str(current.get("id")) in selected_ids
                        and current.get("translation_status") == "queued"
                    ):
                        current.update(
                            translation_status="cancelled",
                            translation_error="Translation was cancelled.",
                        )
                project.segments_data = current_segments
                await session.commit()
        raise

    if failures:
        raise RuntimeError("Some translations failed. Retry the failed segments.")
    async with session_factory() as session:
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.owner_id == owner_id)
            .values(
                status="completed",
                progress=100,
                output_data={
                    "dubbing_project_id": project_id,
                    "completed_segment_ids": completed,
                    "provider": provider.name,
                    "models": list(model_records.values()),
                },
                error_message=None,
            )
        )
        await session.commit()


async def _export_dubbing_job(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    job_id: UUID,
    owner_id: UUID,
    data: dict[str, Any],
) -> None:
    segments = data.get("segments")
    project_id = data.get("project_id")
    dubbing_project_id = data.get("dubbing_project_id")
    if not isinstance(segments, list) or not segments:
        raise RuntimeError("The export contains no user-supplied audio segments.")
    if not isinstance(project_id, str) or not isinstance(dubbing_project_id, str):
        raise TypeError("The export job is missing project references.")
    if any(
        not isinstance(segment, dict)
        or not isinstance(segment.get("audio_duration_seconds"), (int, float))
        or float(segment["audio_duration_seconds"]) <= 0
        for segment in segments
    ):
        raise RuntimeError("The export requires measured durations for every audio segment.")
    end_time = max(
        float(segment["start_seconds"])
        + float(segment["audio_duration_seconds"]) / float(segment["speech_rate"])
        for segment in segments
    )
    if end_time <= 0 or end_time > 86_400:
        raise RuntimeError("The dubbing project has an invalid duration.")
    output_key = f"{owner_id}/{uuid4()}.m4a"
    source_video_key = data.get("source_video_storage_key")
    output_video_key = f"{owner_id}/{uuid4()}.mp4" if source_video_key else None

    try:
        with tempfile.TemporaryDirectory(prefix="creator-dubbing-") as directory:
            temporary = Path(directory)
            inputs: list[Path] = []
            filters: list[str] = []
            labels: list[str] = []
            for index, segment in enumerate(segments):
                if not isinstance(segment, dict) or not isinstance(segment.get("storage_key"), str):
                    raise TypeError("An audio segment has no valid media reference.")
                source = temporary / f"segment-{index}.media"
                with source.open("xb") as target:
                    async for chunk in storage.open_stream(segment["storage_key"]):
                        await asyncio.to_thread(target.write, chunk)
                inputs.append(source)
                start = max(0.0, float(segment["start_seconds"]))
                rate = min(2.0, max(0.5, float(segment["speech_rate"])))
                delay_ms = round(start * 1000)
                label = f"voice{index}"
                filters.append(
                    f"[{index}:a]atempo={rate:.3f},adelay={delay_ms}|{delay_ms},"
                    f"asetpts=N/SR/TB[{label}]"
                )
                labels.append(f"[{label}]")

            output_path = temporary / "dubbed-audio.m4a"
            mix_filter = (
                f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
                "asetpts=N/SR/TB[out]"
            )
            filter_graph = ";".join(
                [
                    *filters,
                    mix_filter,
                ]
            )
            arguments = ["-hide_banner", "-loglevel", "error", "-y"]
            for path in inputs:
                arguments.extend(["-i", str(path)])
            arguments.extend(
                [
                    "-filter_complex",
                    filter_graph,
                    "-map",
                    "[out]",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]
            )
            await _run_ffmpeg(arguments)
            file_size = await _save_file(storage, output_key, output_path)
            video_output_path: Path | None = None
            video_file_size: int | None = None
            if isinstance(source_video_key, str) and output_video_key is not None:
                source_video_path = temporary / "source-video.media"
                with source_video_path.open("xb") as target:
                    async for chunk in storage.open_stream(source_video_key):
                        await asyncio.to_thread(target.write, chunk)
                video_output_path = temporary / "dubbed-video.mp4"
                await _run_ffmpeg(
                    [
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(source_video_path),
                        "-i",
                        str(output_path),
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-map_metadata",
                        "0",
                        "-movflags",
                        "+faststart",
                        str(video_output_path),
                    ]
                )
                video_file_size = await _save_file(storage, output_video_key, video_output_path)

        async with session_factory() as session:
            job = await session.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.id == job_id, ProcessingJob.owner_id == owner_id
                )
            )
            if job is None:
                raise RuntimeError("The dubbing export job was removed before completion.")
            asset = MediaAsset(
                owner_id=owner_id,
                project_id=UUID(project_id),
                name="user-assembled-dub.m4a",
                storage_key=output_key,
                media_type="audio",
                content_type="audio/mp4",
                file_size=file_size,
                duration_seconds=end_time,
                metadata_json={
                    "origin": "user_supplied_dubbing_segments",
                    "dubbing_project_id": dubbing_project_id,
                    "timing_conflicts": data.get("timing_conflicts", []),
                },
            )
            session.add(asset)
            video_asset = None
            if (
                video_output_path is not None
                and video_file_size is not None
                and output_video_key is not None
            ):
                video_asset = MediaAsset(
                    owner_id=owner_id,
                    project_id=UUID(project_id),
                    name="dubbed-video.mp4",
                    storage_key=output_video_key,
                    media_type="video",
                    content_type="video/mp4",
                    file_size=video_file_size,
                    duration_seconds=None,
                    metadata_json={
                        "origin": "user_supplied_dubbing_segments",
                        "dubbing_project_id": dubbing_project_id,
                        "source_video_asset_id": data.get("source_video_asset_id"),
                        "video_stream_copied": True,
                        "timing_conflicts": data.get("timing_conflicts", []),
                    },
                )
                session.add(video_asset)
            await session.flush()
            job.status = "completed"
            job.progress = 100
            job.output_data = {
                "media_asset_id": str(asset.id),
                "video_asset_id": str(video_asset.id) if video_asset else None,
                "origin": "user_supplied_audio",
                "timing_conflicts": data.get("timing_conflicts", []),
            }
            job.error_message = None
            await session.commit()
    except BaseException:
        await storage.delete(output_key)
        if output_video_key is not None:
            await storage.delete(output_video_key)
        raise


async def _set_job_progress(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
    progress: int,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == "processing")
            .values(progress=progress)
        )
        await session.commit()


async def _process_job(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    providers: VoiceProviderRegistry,
    job_id: UUID,
    owner_id: UUID,
    job_type: str,
    data: dict[str, Any],
) -> None:
    async def execute_job() -> None:
        if job_type == "voice_transcription":
            await _transcribe_job(session_factory, storage, providers, job_id, owner_id, data)
        elif job_type == "voice_translation":
            await _translate_job(session_factory, providers, job_id, owner_id, data)
        elif job_type == "voice_dubbing_export":
            await _export_dubbing_job(session_factory, storage, job_id, owner_id, data)
        else:
            raise RuntimeError("The voice worker received an unsupported job type.")

    async def cancellation_requested() -> bool:
        async with session_factory() as session:
            result = await session.scalar(
                select(ProcessingJob.cancellation_requested).where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.owner_id == owner_id,
                    ProcessingJob.status == "processing",
                )
            )
        return bool(result)

    async def mark_cancelled() -> None:
        async with session_factory() as session:
            await session.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.owner_id == owner_id,
                    ProcessingJob.status == "processing",
                )
                .values(
                    status="cancelled",
                    progress=0,
                    error_message="Voice processing was cancelled.",
                )
            )
            await session.commit()

    operation = asyncio.create_task(execute_job())
    try:
        while not operation.done():
            done, _ = await asyncio.wait({operation}, timeout=0.25)
            if done:
                break
            if await cancellation_requested():
                operation.cancel()
                try:
                    await operation
                except asyncio.CancelledError:
                    pass
                await mark_cancelled()
                return
        await operation
    except asyncio.CancelledError:
        operation.cancel()
        try:
            await operation
        except asyncio.CancelledError:
            pass
        await mark_cancelled()
        raise
    except Exception:
        logger.exception("Voice processing job %s failed", job_id)
        async with session_factory() as session:
            await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id, ProcessingJob.status == "processing")
                .values(
                    status="failed",
                    progress=0,
                    error_message="Voice processing failed. Verify the input and installed local tools.",
                )
            )
            await session.commit()


async def run_voice_worker(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    providers: VoiceProviderRegistry,
    poll_interval: float = 0.5,
) -> None:
    """Claim and execute queued voice jobs without blocking API requests."""

    while True:
        async with session_factory() as session:
            job = await session.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.job_type.in_(
                        ("voice_transcription", "voice_translation", "voice_dubbing_export")
                    ),
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
                await _process_job(
                    session_factory,
                    storage,
                    providers,
                    job_id,
                    owner_id,
                    job_type,
                    data,
                )
        if job is None:
            await asyncio.sleep(poll_interval)
