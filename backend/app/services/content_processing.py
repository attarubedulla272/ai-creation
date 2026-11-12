"""Persisted job coordinator for an independent GPU scene-generation worker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.models.scene import Scene
from app.schemas.content import SceneProviderRequest, SceneWorkerJobStatus
from app.services.content_providers import SceneGenerationProvider
from app.services.content_worker_assets import create_worker_asset_url
from app.services.media_processing import probe_media
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


async def _fail_job(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
    scene_id: UUID | None,
    message: str,
) -> None:
    async with session_factory() as session:
        job = await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.id == job_id,
                ProcessingJob.status == "processing",
            )
        )
        if job is None:
            return
        job.status = "failed"
        job.error_message = message[:1000]
        if scene_id is not None:
            scene = await session.scalar(
                select(Scene).where(
                    Scene.id == scene_id,
                    Scene.generation_job_id == job_id,
                )
            )
            if scene is not None:
                scene.generation_status = "failed"
        await session.commit()


async def _download_generated_video(
    storage: StorageService,
    provider: SceneGenerationProvider,
    worker_job_id: str,
    job_id: UUID,
    owner_id: UUID,
    project_id: UUID,
) -> tuple[str, int, dict[str, Any]]:
    storage_key = f"users/{owner_id}/projects/{project_id}/generated/{job_id}.mp4"
    try:
        size = await storage.save_stream(storage_key, provider.download_output(worker_job_id))
        if size <= 0:
            raise RuntimeError("GPU worker returned an empty video.")
        async with storage.local_file(storage_key) as generated_path:
            probe = await probe_media(generated_path)
        if not probe.get("video_codec") or not probe.get("duration_seconds"):
            raise RuntimeError("GPU worker output does not contain a valid video stream.")
        return storage_key, size, probe
    except BaseException:
        await storage.delete(storage_key)
        raise


async def _apply_worker_status(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    provider: SceneGenerationProvider,
    job_id: UUID,
    owner_id: UUID,
    project_id: UUID,
    scene_id: UUID,
    worker_job_id: str,
    remote_status: SceneWorkerJobStatus,
) -> None:
    async with session_factory() as session:
        job = await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.id == job_id,
                ProcessingJob.owner_id == owner_id,
                ProcessingJob.status == "processing",
            )
        )
        scene = await session.scalar(
            select(Scene).where(
                Scene.id == scene_id,
                Scene.project_id == project_id,
                Scene.generation_job_id == job_id,
            )
        )
        if job is None:
            return
        if scene is None:
            job.status = "cancelled"
            job.error_message = "The scene was removed or its active generation changed."
            await session.commit()
            return

    if remote_status.status in {"queued", "processing"}:
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            scene = await session.get(Scene, scene_id)
            if job is None or scene is None or job.status != "processing":
                return
            job.progress = max(job.progress, min(99, remote_status.progress))
            scene.generation_status = remote_status.status
            await session.commit()
        return

    if remote_status.status == "failed":
        await _fail_job(
            session_factory,
            job_id,
            scene_id,
            remote_status.error_message or "GPU worker reported a generation failure.",
        )
        return
    if remote_status.status == "cancelled":
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            scene = await session.get(Scene, scene_id)
            if job is not None:
                job.status = "cancelled"
                job.cancellation_requested = False
                if scene is not None and scene.generation_job_id == job_id:
                    scene.generation_status = "cancelled"
                await session.commit()
        return

    prepared_video: tuple[str, int, dict[str, Any]] | None = None
    if not remote_status.preview_only:
        if not remote_status.output_available:
            await _fail_job(
                session_factory,
                job_id,
                scene_id,
                "GPU worker completed without providing a downloadable video.",
            )
            return
        prepared_video = await _download_generated_video(
            storage,
            provider,
            worker_job_id,
            job_id,
            owner_id,
            project_id,
        )

    try:
        async with session_factory() as session:
            job = await session.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.owner_id == owner_id,
                    ProcessingJob.status == "processing",
                )
            )
            scene = await session.scalar(
                select(Scene).where(
                    Scene.id == scene_id,
                    Scene.project_id == project_id,
                    Scene.generation_job_id == job_id,
                )
            )
            if job is None or scene is None:
                raise RuntimeError("Scene or job changed before output could be attached.")
            if job.cancellation_requested:
                job.status = "cancelled"
                job.cancellation_requested = False
                scene.generation_status = "cancelled"
                await session.commit()
                if prepared_video is not None:
                    await storage.delete(prepared_video[0])
                return
            media_asset_id: UUID | None = None
            if prepared_video is not None:
                storage_key, size, probe = prepared_video
                returned_version = remote_status.output_metadata.get("model_version")
                model_version = (
                    returned_version[:120]
                    if isinstance(returned_version, str) and returned_version
                    else job.model_version
                )
                asset = MediaAsset(
                    owner_id=owner_id,
                    project_id=project_id,
                    name=f"Generated scene {job_id}.mp4",
                    storage_key=storage_key,
                    media_type="video",
                    content_type="video/mp4",
                    file_size=size,
                    duration_seconds=probe["duration_seconds"],
                    metadata_json={
                        "probe": probe,
                        "generation_job_id": str(job_id),
                        "model_name": job.model_name,
                        "model_version": model_version,
                        "model_license": job.model_license,
                        "commercial_use_permitted": job.commercial_use_permitted,
                        "generation_mode": job.generation_mode,
                        "generation_settings": job.generation_settings or {},
                        "worker_output": remote_status.output_metadata,
                    },
                )
                session.add(asset)
                await session.flush()
                media_asset_id = asset.id
                scene.generated_media_asset_id = media_asset_id
            scene.generation_status = (
                "preview_generated" if remote_status.preview_only else "completed"
            )
            scene.generated_preview_label = remote_status.preview_label
            scene.generation_provider = provider.name
            scene.is_approved = False
            job.status = "completed"
            job.progress = 100
            returned_version = remote_status.output_metadata.get("model_version")
            if isinstance(returned_version, str) and returned_version:
                job.model_version = returned_version[:120]
            job.output_data = {
                "scene_id": str(scene_id),
                "provider": provider.name,
                "preview_only": remote_status.preview_only,
                "preview_label": remote_status.preview_label,
                "generated_preview_label": remote_status.preview_label,
                "media_asset_id": str(media_asset_id) if media_asset_id else None,
                "output_metadata": remote_status.output_metadata,
                "model_name": job.model_name,
                "model_version": job.model_version,
                "model_license": job.model_license,
                "commercial_use_permitted": job.commercial_use_permitted,
                "generation_mode": job.generation_mode,
                "generation_settings": job.generation_settings or {},
            }
            job.error_message = None
            await session.commit()
    except BaseException:
        if prepared_video is not None:
            await storage.delete(prepared_video[0])
        raise


async def _poll_processing_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    provider: SceneGenerationProvider | None,
) -> None:
    if provider is None:
        return
    async with session_factory() as session:
        jobs = await session.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.job_type == "scene_generation",
                ProcessingJob.status == "processing",
                ProcessingJob.worker_job_id.is_not(None),
            )
            .order_by(ProcessingJob.created_at, ProcessingJob.id)
            .limit(10)
        )
        job_data = [
            (
                job.id,
                job.owner_id,
                job.project_id,
                UUID(str((job.input_data or {})["scene_id"])),
                job.worker_job_id,
                job.cancellation_requested,
            )
            for job in jobs
            if job.project_id is not None and (job.input_data or {}).get("scene_id")
        ]

    for job_id, owner_id, project_id, scene_id, worker_job_id, cancel_requested in job_data:
        try:
            if cancel_requested:
                await provider.cancel_job(worker_job_id)
                remote = SceneWorkerJobStatus(status="cancelled", progress=0)
            else:
                remote = await provider.get_job_status(worker_job_id)
            await _apply_worker_status(
                session_factory,
                storage,
                provider,
                job_id,
                owner_id,
                project_id,
                scene_id,
                worker_job_id,
                remote,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not poll scene-generation worker job %s", job_id)
            await _fail_job(
                session_factory,
                job_id,
                scene_id,
                "Could not communicate with the configured GPU worker. You can retry this job.",
            )


async def _submit_queued_job(
    session_factory: async_sessionmaker[AsyncSession],
    provider: SceneGenerationProvider | None,
    settings: Settings,
) -> None:
    async with session_factory() as session:
        job = await session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.job_type == "scene_generation",
                ProcessingJob.status == "queued",
            )
            .order_by(ProcessingJob.created_at, ProcessingJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return
        job_id = job.id
        owner_id = job.owner_id
        project_id = job.project_id
        data = dict(job.input_data or {})
        job.status = "processing"
        job.progress = max(job.progress, 1)
        job.error_message = None
        await session.commit()

    raw_scene_id = data.get("scene_id")
    scene_id = UUID(raw_scene_id) if isinstance(raw_scene_id, str) else None
    try:
        if provider is None:
            raise RuntimeError("No GPU worker or development preview provider is configured.")
        if project_id is None:
            raise RuntimeError("Scene generation job has no project.")
        if scene_id is None:
            raise RuntimeError("Scene generation job has no associated scene.")
        request = SceneProviderRequest.model_validate(data["request"])
        async with session_factory() as session:
            project = await session.scalar(
                select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
            )
            scene = await session.scalar(
                select(Scene).where(
                    Scene.id == scene_id,
                    Scene.project_id == project_id,
                    Scene.generation_job_id == job_id,
                )
            )
            if project is None or scene is None:
                raise RuntimeError("The scene generation job references missing project data.")
        request = request.model_copy(
            update={
                "reference_assets": [
                    reference.model_copy(
                        update={
                            "download_url": create_worker_asset_url(
                                settings,
                                owner_id,
                                project_id,
                                reference.asset_id,
                            )
                        }
                    )
                    for reference in request.reference_assets
                ]
            }
        )
        worker_job_id = await provider.submit_scene(str(job_id), request)
        async with session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            scene = await session.get(Scene, scene_id)
            if job is None or scene is None or job.status != "processing":
                await provider.cancel_job(worker_job_id)
                return
            job.worker_job_id = worker_job_id
            job.progress = max(job.progress, 5)
            scene.generation_status = "processing"
            await session.commit()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Could not submit scene generation job %s", job_id)
        await _fail_job(
            session_factory,
            job_id,
            scene_id,
            str(error) or "Scene job submission failed.",
        )


async def run_content_worker(
    session_factory: async_sessionmaker[AsyncSession],
    provider_factory: Callable[[], SceneGenerationProvider | None],
    storage: StorageService,
    settings: Settings,
    poll_interval: float = 0.5,
) -> None:
    """Submit, poll, and persist jobs independently of the frontend process."""

    while True:
        try:
            provider = provider_factory()
            await _submit_queued_job(session_factory, provider, settings)
            await _poll_processing_jobs(session_factory, storage, provider)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Content generation worker iteration failed")
        await asyncio.sleep(poll_interval)
