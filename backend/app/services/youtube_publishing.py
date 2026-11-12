"""Persisted YouTube resumable-upload worker."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.publication import Publication
from app.models.youtube import YouTubeConnection
from app.services.storage import StorageService
from app.services.youtube_api import (
    YouTubeApiClient,
    YouTubeApiError,
    YouTubeOAuthNotConfigured,
    YouTubeUploadAborted,
)

logger = logging.getLogger(__name__)


class YouTubeUploadCancelled(Exception):
    """Raised when an owner cancels an active YouTube upload."""


async def _progress(
    factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
    progress: int,
) -> None:
    async with factory() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is not None and job.status == "processing":
            job.progress = max(1, min(99, progress))
            await session.commit()


async def _cancelled(
    factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> bool:
    async with factory() as session:
        job = await session.get(ProcessingJob, job_id)
        return job is None or job.status != "processing" or job.cancellation_requested


def _publication_metadata(publication: Publication) -> dict[str, Any]:
    metadata = publication.metadata_json or {}
    description = publication.description or ""
    additions: list[str] = []
    hashtags = metadata.get("hashtags")
    if isinstance(hashtags, list):
        additions.extend(f"#{tag.lstrip('#')}" for tag in hashtags if isinstance(tag, str))
    chapters = metadata.get("chapters")
    if isinstance(chapters, list):
        chapter_lines = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            timestamp = chapter.get("timestamp_seconds")
            title = chapter.get("title")
            if not isinstance(timestamp, int) or not isinstance(title, str):
                continue
            hours, remainder = divmod(timestamp, 3600)
            minutes, seconds = divmod(remainder, 60)
            timecode = (
                f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"
            )
            chapter_lines.append(f"{timecode} {title}")
        if chapter_lines:
            additions.extend(["", *chapter_lines])
    if additions:
        description = f"{description.rstrip()}\n\n" if description else ""
        description += "\n".join(additions).lstrip("\n")

    tags = metadata.get("tags")
    language = metadata.get("language")
    category = metadata.get("category")
    return {
        "title": (publication.title or "").strip(),
        "description": description,
        "tags": [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else [],
        "category": category if isinstance(category, str) else None,
        "language": language if isinstance(language, str) else None,
    }


async def _get_upload_asset(
    session: AsyncSession,
    publication: Publication,
    owner_id: UUID,
) -> MediaAsset:
    asset_id = publication.media_asset_id
    if publication.clip_candidate_id is not None:
        from app.models.clip_candidate import ClipCandidate

        candidate = await session.scalar(
            select(ClipCandidate).where(
                ClipCandidate.id == publication.clip_candidate_id,
                ClipCandidate.project_id == publication.project_id,
            )
        )
        if candidate is None:
            raise RuntimeError("The linked clip candidate is no longer available.")
        if candidate.exported_media_asset_id is not None:
            asset_id = candidate.exported_media_asset_id

    if asset_id is None:
        raise RuntimeError("Select an exported video before starting a YouTube upload.")
    asset = await session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.owner_id == owner_id,
            or_(
                MediaAsset.project_id == publication.project_id,
                MediaAsset.project_id.is_(None),
            ),
            MediaAsset.media_type == "video",
        )
    )
    if asset is None:
        raise RuntimeError("The publication video is not available in this owned project.")
    return asset


async def _process_upload(
    factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    client: YouTubeApiClient,
    job_id: UUID,
    owner_id: UUID,
    data: dict[str, Any],
) -> None:
    async with factory() as session:
        publication_id = UUID(str(data["publication_id"]))
        connection_id = UUID(str(data["connection_id"]))
        publication = await session.scalar(
            select(Publication).where(
                Publication.id == publication_id,
                Publication.owner_id == owner_id,
            )
        )
        connection = await session.scalar(
            select(YouTubeConnection).where(
                YouTubeConnection.id == connection_id,
                YouTubeConnection.owner_id == owner_id,
            )
        )
        if publication is None or connection is None:
            raise RuntimeError("The publication or connected YouTube channel is unavailable.")
        if publication.external_id:
            raise RuntimeError("This publication already has a confirmed YouTube video.")
        asset = await _get_upload_asset(session, publication, owner_id)
        thumbnail = None
        if publication.thumbnail_asset_id is not None:
            thumbnail = await session.scalar(
                select(MediaAsset).where(
                    MediaAsset.id == publication.thumbnail_asset_id,
                    MediaAsset.owner_id == owner_id,
                    or_(
                        MediaAsset.project_id == publication.project_id,
                        MediaAsset.project_id.is_(None),
                    ),
                    MediaAsset.media_type == "image",
                )
            )
            if thumbnail is None:
                raise RuntimeError("The selected thumbnail is no longer available.")
        metadata = _publication_metadata(publication)
        if not metadata["title"]:
            raise RuntimeError("Add a YouTube title before uploading.")
        if len(metadata["description"]) > 5000:
            raise RuntimeError(
                "The description and chapter text exceed YouTube's 5,000-character limit."
            )
        if sum(len(tag) for tag in metadata["tags"] if isinstance(tag, str)) > 500:
            raise RuntimeError("YouTube tags exceed the 500-character total limit.")
        try:
            refresh_token = client.cipher.decrypt(connection.refresh_token_encrypted)
        except YouTubeOAuthNotConfigured as error:
            connection.status = "reauthorization_required"
            connection.last_error = "Token decryption failed; reconnect the channel."
            await session.commit()
            raise RuntimeError(
                "YouTube credentials cannot be decrypted; reconnect the channel."
            ) from error
        connection_status = connection.status
        asset_key = asset.storage_key
        asset_content_type = asset.content_type
        thumbnail_key = thumbnail.storage_key if thumbnail else None
        thumbnail_content_type = thumbnail.content_type if thumbnail else None
        privacy_status = str(data["privacy_status"])
        publish_at = (
            datetime.fromisoformat(str(data["publish_at"]))
            if data.get("publish_at")
            else None
        )

    if connection_status != "connected":
        raise RuntimeError("Reconnect this YouTube channel before uploading.")
    try:
        token_data = await client.refresh_access_token(refresh_token)
    except YouTubeApiError as error:
        if error.reason == "invalid_grant":
            async with factory() as session:
                connection = await session.get(YouTubeConnection, connection_id)
                if connection is not None and connection.owner_id == owner_id:
                    connection.status = "reauthorization_required"
                    connection.last_error = "Google authorization expired or was revoked."
                    await session.commit()
        raise
    access_token = str(token_data["access_token"])

    async with storage.local_file(asset_key) as source_path:
        if not source_path.is_file():
            raise RuntimeError("The selected video file is missing from local storage.")
        if not asset_content_type.startswith("video/"):
            raise RuntimeError("The selected media is not a supported video file.")

        async def report_progress(value: int) -> None:
            await _progress(factory, job_id, value)

        async def check_cancelled() -> bool:
            return await _cancelled(factory, job_id)

        result = await client.upload_video(
            access_token=access_token,
            file_path=source_path,
            content_type=asset_content_type,
            metadata=metadata,
            privacy_status=privacy_status,
            publish_at=publish_at,
            progress=report_progress,
            cancelled=check_cancelled,
        )
    video_id = result["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    async with factory() as session:
        job = await session.get(ProcessingJob, job_id)
        publication = await session.scalar(
            select(Publication).where(
                Publication.id == publication_id,
                Publication.owner_id == owner_id,
            )
        )
        if job is None or publication is None or job.status != "processing":
            raise YouTubeUploadCancelled
        publication.external_id = video_id
        publication.youtube_url = video_url
        publication.youtube_privacy_status = privacy_status
        publication.youtube_status = "youtube_scheduled" if publish_at else "uploaded"
        await session.commit()

    output: dict[str, Any] = {
        "youtube_video_id": video_id,
        "youtube_url": video_url,
        "privacy_status": privacy_status,
        "status": "youtube_scheduled" if publish_at else "uploaded",
        "publication_title": metadata["title"],
    }
    if thumbnail_key is not None and thumbnail_content_type is not None:
        try:
            async with storage.local_file(thumbnail_key) as thumbnail_path:
                await client.upload_thumbnail(
                    access_token=access_token,
                    video_id=video_id,
                    file_path=thumbnail_path,
                    content_type=thumbnail_content_type,
                )
            output["thumbnail_uploaded"] = True
        except (OSError, YouTubeApiError) as error:
            logger.warning("YouTube thumbnail upload failed for job %s: %s", job_id, error)
            output["thumbnail_uploaded"] = False
            output["thumbnail_warning"] = (
                str(error)[:255]
                if isinstance(error, YouTubeApiError)
                else "The thumbnail file could not be read from local storage."
            )

    async with factory() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is not None:
            job.status = "completed"
            job.progress = 100
            job.output_data = output
            job.error_message = None
            await session.commit()


async def _process_job(
    factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    client: YouTubeApiClient,
    job_id: UUID,
    owner_id: UUID,
    data: dict[str, Any],
) -> None:
    try:
        await _process_upload(factory, storage, client, job_id, owner_id, data)
    except (YouTubeUploadCancelled, YouTubeUploadAborted):
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "cancelled"
                job.error_message = "YouTube upload was cancelled."
                job.cancellation_requested = False
                publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.id == publication_id,
                        Publication.owner_id == job.owner_id,
                    )
                )
                if publication is not None and publication.external_id is None:
                    publication.youtube_status = "upload_cancelled"
                await session.commit()
    except asyncio.CancelledError:
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None and job.status == "processing":
                job.status = "failed"
                job.error_message = (
                    "The YouTube worker stopped before upload confirmation. "
                    "Retry only after checking the channel for a possibly completed upload."
                )
                publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.id == publication_id,
                        Publication.owner_id == job.owner_id,
                    )
                )
                if publication is not None and publication.external_id is None:
                    publication.youtube_status = "upload_failed"
                await session.commit()
        raise
    except YouTubeApiError as error:
        logger.warning(
            "YouTube upload job %s failed: status=%s reason=%s",
            job_id,
            error.status_code,
            error.reason,
        )
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None and job.status == "processing":
                if error.retryable and job.retry_count < job.max_retries:
                    job.retry_count += 1
                    job.status = "queued"
                    job.progress = 0
                    job.error_message = str(error)[:1000]
                else:
                    job.status = "failed"
                    job.error_message = str(error)[:1000]
                    if error.reason == "invalid_grant":
                        connection_id = UUID(
                            str((job.input_data or {}).get("connection_id", ""))
                        )
                        connection = await session.scalar(
                            select(YouTubeConnection).where(
                                YouTubeConnection.id == connection_id,
                                YouTubeConnection.owner_id == job.owner_id,
                            )
                        )
                        if connection is not None:
                            connection.status = "reauthorization_required"
                            connection.last_error = "Google authorization expired or was revoked."
                    publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
                    publication = await session.scalar(
                        select(Publication).where(
                            Publication.id == publication_id,
                            Publication.owner_id == job.owner_id,
                        )
                    )
                    if publication is not None and publication.external_id is None:
                        publication.youtube_status = "upload_failed"
                await session.commit()
    except OSError:
        logger.exception("YouTube upload job %s could not read local media storage", job_id)
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None and job.status == "processing":
                job.status = "failed"
                job.error_message = "A local video or thumbnail file could not be read from storage."
                publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.id == publication_id,
                        Publication.owner_id == job.owner_id,
                    )
                )
                if publication is not None and publication.external_id is None:
                    publication.youtube_status = "upload_failed"
                await session.commit()
    except Exception:
        logger.exception("YouTube upload job %s failed", job_id)
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None and job.status == "processing":
                job.status = "failed"
                job.error_message = (
                    "The YouTube upload failed due to an internal processing error. "
                    "Retry the upload or contact support."
                )
                publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
                publication = await session.scalar(
                    select(Publication).where(
                        Publication.id == publication_id,
                        Publication.owner_id == job.owner_id,
                    )
                )
                if publication is not None and publication.external_id is None:
                    publication.youtube_status = "upload_failed"
                await session.commit()


async def _fail_stalled_jobs(
    factory: async_sessionmaker[AsyncSession],
    stale_before: datetime,
) -> None:
    async with factory() as session:
        jobs = await session.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.job_type == "youtube_upload",
                ProcessingJob.status == "processing",
                ProcessingJob.updated_at < stale_before,
            )
            .with_for_update(skip_locked=True)
        )
        for job in jobs:
            job.status = "failed"
            job.error_message = (
                "The YouTube worker stopped before upload confirmation. "
                "Retry only after checking the channel for a possibly completed upload."
            )
            publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
            publication = await session.scalar(
                select(Publication).where(
                    Publication.id == publication_id,
                    Publication.owner_id == job.owner_id,
                )
            )
            if publication is not None and publication.external_id is None:
                publication.youtube_status = "upload_failed"
        await session.commit()


async def run_youtube_upload_worker(
    factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
    client: YouTubeApiClient,
    poll_interval: float = 0.5,
) -> None:
    """Claim YouTube upload jobs from the shared processing-job table."""

    loop = asyncio.get_running_loop()
    next_stall_recovery = 0.0
    while True:
        if loop.time() >= next_stall_recovery:
            await _fail_stalled_jobs(
                factory,
                datetime.now(UTC) - timedelta(minutes=10),
            )
            next_stall_recovery = loop.time() + 60
        async with factory() as session:
            job = await session.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.job_type == "youtube_upload",
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
                job.progress = max(1, job.progress)
                job_id = job.id
                owner_id = job.owner_id
                data = dict(job.input_data or {})
                await session.commit()
                await _process_job(factory, storage, client, job_id, owner_id, data)
        await asyncio.sleep(poll_interval)
