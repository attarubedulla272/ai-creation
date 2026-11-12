"""Authenticated media upload, library, download, and job endpoints."""

from __future__ import annotations

import errno
import logging
import re
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.errors import APIError
from app.models.clip_candidate import ClipCandidate
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.schemas.media import MediaAssetPublic, MediaUploadResponse, ProcessingJobPublic
from app.services.storage import StorageService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/media", tags=["media"])

ALLOWED_MEDIA: dict[str, tuple[str, set[str]]] = {
    ".mp4": ("video", {"video/mp4"}),
    ".m4v": ("video", {"video/mp4", "video/x-m4v"}),
    ".mov": ("video", {"video/quicktime"}),
    ".mkv": ("video", {"video/x-matroska"}),
    ".webm": ("video", {"video/webm"}),
    ".avi": ("video", {"video/x-msvideo", "video/avi"}),
    ".mp3": ("audio", {"audio/mpeg", "audio/mp3"}),
    ".wav": ("audio", {"audio/wav", "audio/x-wav", "audio/wave"}),
    ".m4a": ("audio", {"audio/mp4", "audio/x-m4a"}),
    ".aac": ("audio", {"audio/aac", "audio/x-aac"}),
    ".ogg": ("audio", {"audio/ogg", "application/ogg"}),
    ".flac": ("audio", {"audio/flac", "audio/x-flac"}),
    ".png": ("image", {"image/png"}),
    ".jpg": ("image", {"image/jpeg"}),
    ".jpeg": ("image", {"image/jpeg"}),
    ".webp": ("image", {"image/webp"}),
    ".gif": ("image", {"image/gif"}),
}


def _safe_display_name(filename: str, extension: str) -> str:
    """Keep a printable basename for display, never for filesystem access."""

    basename = PurePosixPath(filename.replace("\\", "/")).name
    cleaned = "".join(
        character for character in basename if character.isprintable() and character not in "/\\"
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or f"upload{extension}")[:255]


def _matches_signature(extension: str, header: bytes) -> bool:
    if extension in {".mp4", ".m4v", ".mov", ".m4a"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if extension == ".avi":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI "
    if extension in {".mkv", ".webm"}:
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if extension in {".mp3"}:
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        )
    if extension in {".aac"}:
        return len(header) >= 2 and header[0] == 0xFF and header[1] & 0xF6 == 0xF0
    if extension == ".wav":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    if extension == ".ogg":
        return header.startswith(b"OggS")
    if extension == ".flac":
        return header.startswith(b"fLaC")
    if extension == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if extension == ".webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if extension == ".gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    return False


def _storage(request: Request) -> StorageService:
    return request.app.state.storage


async def _owned_asset(
    asset_id: UUID,
    user_id: UUID,
    session: SessionDependency,
) -> MediaAsset:
    asset = await session.scalar(
        select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.owner_id == user_id)
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found.")
    return asset


@router.post("", response_model=MediaUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
    file: Annotated[UploadFile, File(...)],
    project_id: UUID | None = None,
) -> MediaUploadResponse:
    """Validate, persist, and enqueue an uploaded media file."""

    filename = file.filename or ""
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    media_definition = ALLOWED_MEDIA.get(extension)
    if media_definition is None:
        raise APIError(415, "unsupported_media_type", "This file extension is not supported.")
    media_type, accepted_mimes = media_definition
    content_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if content_type not in accepted_mimes:
        raise APIError(
            415, "unsupported_media_type", "The MIME type does not match the file extension."
        )
    header = await file.read(32)
    await file.seek(0)
    if not _matches_signature(extension, header):
        raise APIError(
            415, "invalid_media_signature", "The uploaded file content does not match its type."
        )
    if file.size is not None and file.size > request.app.state.settings.max_upload_size_bytes:
        raise APIError(
            413,
            "file_too_large",
            "The uploaded file exceeds the configured size limit.",
        )
    if project_id is not None:
        project = await session.scalar(
            select(Project.id).where(Project.id == project_id, Project.owner_id == user.id)
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

    storage = _storage(request)
    asset_id = uuid4()
    storage_key = f"{user.id}/{asset_id}{extension}"
    saved = False

    async def upload_chunks():
        total = 0
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > request.app.state.settings.max_upload_size_bytes:
                raise APIError(
                    413, "file_too_large", "The uploaded file exceeds the configured size limit."
                )
            yield chunk

    try:
        file_size = await storage.save_stream(storage_key, upload_chunks())
        saved = True
        if file_size == 0:
            raise APIError(400, "empty_file", "Empty media files cannot be uploaded.")
        asset = MediaAsset(
            id=asset_id,
            owner_id=user.id,
            project_id=project_id,
            name=_safe_display_name(filename, extension),
            storage_key=storage_key,
            media_type=media_type,
            content_type=content_type,
            file_size=file_size,
        )
        job = ProcessingJob(
            owner_id=user.id,
            project_id=project_id,
            job_type="media_process",
            status="queued",
            input_data={"media_asset_id": str(asset_id)},
        )
        session.add_all([asset, job])
        await session.flush()
        asset.metadata_json = {"processing_job_id": str(job.id)}
        await session.commit()
        await session.refresh(asset)
        await session.refresh(job)
    except BaseException as error:
        await session.rollback()
        if saved:
            try:
                await storage.delete(storage_key)
            except OSError:
                logger.exception("Could not clean up failed media upload %s", asset_id)
        if isinstance(error, OSError) and error.errno == errno.ENOSPC:
            raise APIError(
                507,
                "insufficient_storage",
                "There is not enough disk space to store this upload.",
            ) from error
        raise

    return MediaUploadResponse(asset=asset, job_id=job.id)


@router.get("", response_model=list[MediaAssetPublic])
async def list_media(
    user: CurrentUser,
    session: SessionDependency,
    media_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[MediaAsset]:
    """List only media assets owned by the authenticated user."""

    if media_type is not None and media_type not in {"video", "audio", "image"}:
        raise APIError(422, "invalid_media_filter", "media_type must be video, audio, or image.")
    statement = select(MediaAsset).where(MediaAsset.owner_id == user.id)
    if media_type:
        statement = statement.where(MediaAsset.media_type == media_type)
    result = await session.scalars(
        statement.order_by(MediaAsset.created_at.desc(), MediaAsset.id).limit(limit)
    )
    return list(result.all())


@router.get("/jobs/{job_id}", response_model=ProcessingJobPublic)
async def read_media_job(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    """Read processing status only for jobs owned by the authenticated user."""

    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "media_process",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    return job


@router.post("/jobs/{job_id}/retry", response_model=ProcessingJobPublic)
async def retry_media_job(
    job_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    """Requeue a failed or cancelled media job while retries remain."""

    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "media_process",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried.")
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=409, detail="The media job has reached its retry limit.")
    asset_id_value = (job.input_data or {}).get("media_asset_id")
    try:
        asset_id = UUID(str(asset_id_value))
    except ValueError:
        raise HTTPException(
            status_code=409, detail="The original media asset is unavailable."
        ) from None
    asset = await session.scalar(
        select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.owner_id == user.id)
    )
    if asset is None or not await _storage(request).exists(asset.storage_key):
        raise HTTPException(status_code=409, detail="The original media file is unavailable.")
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    job.output_data = None
    job.cancellation_requested = False
    job.retry_count += 1
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=ProcessingJobPublic)
async def cancel_media_job(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    """Cancel a queued job or request cooperative cancellation while processing."""

    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "media_process",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    if job.status == "queued":
        job.status = "cancelled"
        job.cancellation_requested = True
        job.error_message = "Media processing was cancelled."
    elif job.status == "processing":
        job.cancellation_requested = True
    else:
        raise HTTPException(
            status_code=409, detail="Only queued or processing jobs can be cancelled."
        )
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/{asset_id}", response_model=MediaAssetPublic)
async def read_media(
    asset_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> MediaAsset:
    """Retrieve media metadata owned by the authenticated user."""

    return await _owned_asset(asset_id, user.id, session)


@router.get("/{asset_id}/download")
async def download_media(
    asset_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> StreamingResponse:
    """Download an original asset after checking user ownership."""

    asset = await _owned_asset(asset_id, user.id, session)
    storage = _storage(request)
    if not await storage.exists(asset.storage_key):
        raise HTTPException(status_code=404, detail="Media file is not available in storage.")
    return StreamingResponse(
        storage.open_stream(asset.storage_key),
        media_type=asset.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(asset.name, safe='')}"
        },
    )


@router.get("/{asset_id}/derivatives/{kind}")
async def download_derivative(
    asset_id: UUID,
    kind: str,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> StreamingResponse:
    """Download an allow-listed generated derivative for an owned asset."""

    asset = await _owned_asset(asset_id, user.id, session)
    derivatives = (asset.metadata_json or {}).get("derivatives", {})
    key = (
        derivatives.get(kind)
        if kind in {"thumbnail", "proxy", "extracted_audio", "waveform"}
        else None
    )
    if not isinstance(key, str):
        raise HTTPException(status_code=404, detail="Media derivative not found.")
    storage = _storage(request)
    if not await storage.exists(key):
        raise HTTPException(status_code=404, detail="Media derivative is not available in storage.")
    content_type = {
        "thumbnail": "image/jpeg",
        "proxy": "video/mp4",
        "extracted_audio": "audio/mp4",
        "waveform": "image/png",
    }[kind]
    filename = {
        "thumbnail": "thumbnail.jpg",
        "proxy": "proxy.mp4",
        "extracted_audio": "extracted-audio.m4a",
        "waveform": "waveform.png",
    }[kind]
    return StreamingResponse(
        storage.open_stream(key),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={quote(filename)}"},
    )


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    asset_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> None:
    """Delete an owned asset and its generated derivatives."""

    asset = await _owned_asset(asset_id, user.id, session)
    jobs = await session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "media_process",
            ProcessingJob.status.in_(("queued", "processing")),
        )
    )
    for job in jobs:
        if str((job.input_data or {}).get("media_asset_id")) == str(asset.id):
            raise HTTPException(status_code=409, detail="Media cannot be deleted while processing.")

    keys = [asset.storage_key]
    derivatives = (asset.metadata_json or {}).get("derivatives", {})
    if isinstance(derivatives, dict):
        keys.extend(value for value in derivatives.values() if isinstance(value, str))
    exported_candidates = await session.scalars(
        select(ClipCandidate).where(ClipCandidate.exported_media_asset_id == asset.id)
    )
    for candidate in exported_candidates:
        candidate.exported_media_asset_id = None
    await session.delete(asset)
    await session.commit()

    storage = _storage(request)
    for key in keys:
        try:
            await storage.delete(key)
        except OSError:
            logger.exception("Could not remove deleted media file %s", key)
            raise APIError(
                503,
                "storage_cleanup_failed",
                "The media record was deleted but one or more files could not be removed.",
            ) from None
