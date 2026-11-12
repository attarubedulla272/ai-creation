"""Owner-scoped SEO metadata, release calendar, and local thumbnail endpoints."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from app.api.dependencies import CurrentUser, SessionDependency
from app.models.clip_candidate import ClipCandidate
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.models.publication import Publication, PublicationRevision
from app.schemas.media import MediaAssetPublic
from app.schemas.publishing import (
    PublicationCreate,
    PublicationPublic,
    PublicationRevisionPublic,
    PublicationUpdate,
    ThumbnailRenderRequest,
    ThumbnailRenderResponse,
    TitleSuggestionRequest,
    TitleSuggestionResponse,
)
from app.services.storage import LocalStorage

router = APIRouter(prefix="/publishing", tags=["SEO & publishing"])

THUMBNAIL_SIZES = {
    "16:9": (1280, 720),
    "1:1": (1080, 1080),
    "9:16": (1080, 1920),
}
def _storage(request: Request) -> LocalStorage:
    storage = request.app.state.storage
    if not isinstance(storage, LocalStorage):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local image rendering is not configured for this storage provider.",
        )
    return storage


async def _owned_project(
    project_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
) -> Project:
    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


async def _validate_associations(
    project_id: UUID,
    owner_id: UUID,
    media_asset_id: UUID | None,
    clip_candidate_id: UUID | None,
    thumbnail_asset_id: UUID | None,
    session: SessionDependency,
) -> None:
    if media_asset_id is not None:
        asset = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == media_asset_id,
                MediaAsset.owner_id == owner_id,
                MediaAsset.media_type == "video",
                (MediaAsset.project_id == project_id) | (MediaAsset.project_id.is_(None)),
            )
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="Video asset not found in this project.")
    if thumbnail_asset_id is not None:
        asset = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == thumbnail_asset_id,
                MediaAsset.owner_id == owner_id,
                MediaAsset.media_type == "image",
                (MediaAsset.project_id == project_id) | (MediaAsset.project_id.is_(None)),
            )
        )
        if asset is None:
            raise HTTPException(
                status_code=404, detail="Thumbnail image not found in this project."
            )
    if clip_candidate_id is not None:
        candidate = await session.scalar(
            select(ClipCandidate).where(
                ClipCandidate.id == clip_candidate_id,
                ClipCandidate.project_id == project_id,
            )
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="Clip not found in this project.")


def _snapshot(publication: Publication) -> dict[str, object]:
    scheduled_at = publication.scheduled_at
    if scheduled_at is not None and scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    return {
        "project_id": str(publication.project_id),
        "platform": publication.platform,
        "title": publication.title,
        "description": publication.description,
        **(publication.metadata_json or {}),
        "media_asset_id": str(publication.media_asset_id) if publication.media_asset_id else None,
        "clip_candidate_id": (
            str(publication.clip_candidate_id) if publication.clip_candidate_id else None
        ),
        "thumbnail_asset_id": (
            str(publication.thumbnail_asset_id) if publication.thumbnail_asset_id else None
        ),
        "status": publication.status,
        "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
    }


def _metadata_values(payload: PublicationCreate | PublicationUpdate) -> dict[str, object]:
    values = payload.model_dump(exclude_unset=True, mode="json")
    for key in (
        "platform",
        "title",
        "description",
        "media_asset_id",
        "clip_candidate_id",
        "thumbnail_asset_id",
        "status",
        "scheduled_at",
    ):
        values.pop(key, None)
    return values


def _validate_schedule(status_value: str, scheduled_at: datetime | None) -> None:
    if status_value == "scheduled":
        if scheduled_at is None:
            raise HTTPException(status_code=422, detail="A scheduled entry needs a planned date.")
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=UTC)
        if scheduled_at <= datetime.now(UTC):
            raise HTTPException(
                status_code=422, detail="The planned publication date must be in the future."
            )


async def _record_revision(publication: Publication, session: SessionDependency) -> None:
    publication.version += 1
    session.add(
        PublicationRevision(
            publication_id=publication.id,
            version=publication.version,
            snapshot=_snapshot(publication),
        )
    )


@router.get("/capabilities")
async def read_capabilities(request: Request, _user: CurrentUser) -> dict[str, object]:
    """Report only integrations that are actually configured."""

    available = request.app.state.youtube_client is not None
    return {
        "youtube": {
            "available": available,
            "reason": (
                "Google OAuth is configured; connect a channel to enable explicit uploads."
                if available
                else "Configure an approved Google OAuth client and secure token storage before connecting a channel."
            ),
            "official_docs": [
                "https://developers.google.com/youtube/data/guides/authentication",
                "https://developers.google.com/youtube/data/guides/uploading_a_video",
            ],
        },
        "analytics": {
            "available": available,
            "reason": (
                "Analytics access is granted separately per channel."
                if available
                else "No authorized YouTube Analytics connection is configured; metrics are not available."
            ),
            "official_docs": ["https://developers.google.com/youtube/analytics/metrics"],
        },
    }


@router.post("/title-suggestions", response_model=TitleSuggestionResponse)
async def suggest_titles(payload: TitleSuggestionRequest) -> TitleSuggestionResponse:
    """Create transparent, deterministic title drafts from user-supplied text."""

    topic = " ".join(payload.topic.split())
    keyword = next((item.strip() for item in payload.keywords if item.strip()), "")
    options = [
        f"{topic}: a practical guide",
        f"How to {topic[0].lower() + topic[1:]}" if topic else topic,
        f"{topic} | {keyword}" if keyword else f"What to know about {topic}",
    ]
    suggestions = list(dict.fromkeys(option[:100].strip() for option in options if option.strip()))
    return TitleSuggestionResponse(suggestions=suggestions, method="local_templates")


@router.post(
    "/projects/{project_id}/publications",
    response_model=PublicationPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_publication(
    project_id: UUID,
    payload: PublicationCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> Publication:
    await _owned_project(project_id, user.id, session)
    await _validate_associations(
        project_id,
        user.id,
        payload.media_asset_id,
        payload.clip_candidate_id,
        payload.thumbnail_asset_id,
        session,
    )
    _validate_schedule(payload.status, payload.scheduled_at)
    publication = Publication(
        owner_id=user.id,
        project_id=project_id,
        platform=payload.platform,
        title=payload.title.strip(),
        description=payload.description,
        status=payload.status,
        scheduled_at=payload.scheduled_at,
        metadata_json=payload.model_dump(
            include={
                "tags",
                "hashtags",
                "primary_keywords",
                "secondary_keywords",
                "chapters",
                "language",
                "category",
            },
            mode="json",
        ),
        media_asset_id=payload.media_asset_id,
        clip_candidate_id=payload.clip_candidate_id,
        thumbnail_asset_id=payload.thumbnail_asset_id,
    )
    session.add(publication)
    await session.flush()
    session.add(
        PublicationRevision(
            publication_id=publication.id,
            version=publication.version,
            snapshot=_snapshot(publication),
        )
    )
    await session.commit()
    await session.refresh(publication)
    return publication


@router.get(
    "/projects/{project_id}/publications",
    response_model=list[PublicationPublic],
)
async def list_project_publications(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[Publication]:
    await _owned_project(project_id, user.id, session)
    result = await session.scalars(
        select(Publication)
        .where(Publication.project_id == project_id, Publication.owner_id == user.id)
        .order_by(Publication.updated_at.desc(), Publication.id)
    )
    return list(result.all())


@router.get("/calendar", response_model=list[PublicationPublic])
async def list_calendar(
    user: CurrentUser,
    session: SessionDependency,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Publication]:
    if start is not None and start.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Calendar start must include a timezone.")
    if end is not None and end.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Calendar end must include a timezone.")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="Calendar start must not be after end.")
    statement = select(Publication).where(Publication.owner_id == user.id)
    if start is not None:
        statement = statement.where(Publication.scheduled_at >= start)
    if end is not None:
        statement = statement.where(Publication.scheduled_at <= end)
    result = await session.scalars(
        statement.order_by(Publication.scheduled_at, Publication.created_at, Publication.id)
    )
    return list(result.all())


@router.patch("/publications/{publication_id}", response_model=PublicationPublic)
async def update_publication(
    publication_id: UUID,
    payload: PublicationUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> Publication:
    publication = await session.scalar(
        select(Publication).where(
            Publication.id == publication_id,
            Publication.owner_id == user.id,
        )
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    active_uploads = await session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "youtube_upload",
            ProcessingJob.status.in_(("queued", "processing")),
        )
    )
    if any(
        (job.input_data or {}).get("publication_id") == str(publication.id)
        for job in active_uploads
    ):
        raise HTTPException(
            status_code=409,
            detail="Cancel the active YouTube upload before editing this release.",
        )

    values = payload.model_dump(exclude_unset=True)
    if any(values.get(key) is None for key in ("platform", "title", "status") if key in values):
        raise HTTPException(status_code=422, detail="Platform, title, and status cannot be null.")
    next_status = values.get("status", publication.status)
    if "status" in values and next_status != "scheduled" and "scheduled_at" not in values:
        values["scheduled_at"] = None
    next_scheduled_at = values.get("scheduled_at", publication.scheduled_at)
    if next_status != "scheduled" and "scheduled_at" in values and next_scheduled_at is not None:
        raise HTTPException(
            status_code=422,
            detail="A planned publication date is only valid for scheduled entries.",
        )
    _validate_schedule(next_status, next_scheduled_at)
    associations = {
        key: values.get(key, getattr(publication, key))
        for key in ("media_asset_id", "clip_candidate_id", "thumbnail_asset_id")
    }
    await _validate_associations(
        publication.project_id,
        user.id,
        associations["media_asset_id"],
        associations["clip_candidate_id"],
        associations["thumbnail_asset_id"],
        session,
    )

    old_snapshot = _snapshot(publication)
    metadata = dict(publication.metadata_json or {})
    for key, value in _metadata_values(payload).items():
        metadata[key] = value
    publication.metadata_json = metadata
    for key in (
        "platform",
        "title",
        "description",
        "status",
        "scheduled_at",
        "media_asset_id",
        "clip_candidate_id",
        "thumbnail_asset_id",
    ):
        if key in values:
            setattr(publication, key, values[key])
    if publication.title is not None:
        publication.title = publication.title.strip()
    if _snapshot(publication) != old_snapshot:
        await _record_revision(publication, session)
    await session.commit()
    await session.refresh(publication)
    return publication


@router.get(
    "/publications/{publication_id}/revisions",
    response_model=list[PublicationRevisionPublic],
)
async def list_publication_revisions(
    publication_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[PublicationRevision]:
    publication = await session.scalar(
        select(Publication).where(
            Publication.id == publication_id,
            Publication.owner_id == user.id,
        )
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    result = await session.scalars(
        select(PublicationRevision)
        .where(PublicationRevision.publication_id == publication_id)
        .order_by(PublicationRevision.version.desc())
    )
    return list(result.all())


def _render_thumbnail(
    source: str,
    payload: ThumbnailRenderRequest,
) -> tuple[bytes, int, int]:
    width, height = THUMBNAIL_SIZES[payload.aspect_ratio]
    with Image.open(source) as source_image:
        if source_image.width * source_image.height > 50_000_000:
            raise ValueError("Source image exceeds the thumbnail rendering pixel limit.")
        image = ImageOps.fit(
            source_image.convert("RGB"),
            (width, height),
            method=Image.Resampling.LANCZOS,
            centering=(payload.crop_x, payload.crop_y),
        )
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=payload.font_size)
    words = payload.title.split()
    lines: list[str] = []
    current = ""
    max_width = int(width * 0.88)
    for word in words:
        proposed = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), proposed, font=font, stroke_width=2)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = proposed
    if current:
        lines.append(current)
    lines = lines[:4]
    line_height = payload.font_size + 12
    text_height = len(lines) * line_height
    top = {
        "top": int(height * 0.08),
        "center": (height - text_height) // 2,
        "bottom": height - text_height - int(height * 0.08),
    }[payload.text_position]
    color = tuple(int(payload.text_color[index : index + 2], 16) for index in (1, 3, 5))
    for index, line in enumerate(lines):
        bounds = draw.textbbox((0, 0), line, font=font, stroke_width=2)
        x = (width - (bounds[2] - bounds[0])) // 2
        draw.text(
            (x, top + index * line_height),
            line,
            font=font,
            fill=color,
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), width, height


@router.post(
    "/projects/{project_id}/thumbnails",
    response_model=ThumbnailRenderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def render_thumbnail(
    project_id: UUID,
    payload: ThumbnailRenderRequest,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> ThumbnailRenderResponse:
    await _owned_project(project_id, user.id, session)
    source = await session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == payload.source_asset_id,
            MediaAsset.owner_id == user.id,
            MediaAsset.media_type == "image",
            (MediaAsset.project_id == project_id) | (MediaAsset.project_id.is_(None)),
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source image not found in this project.")

    storage = _storage(request)
    try:
        async with storage.local_file(source.storage_key) as source_path:
            if not await asyncio.to_thread(source_path.is_file):
                raise HTTPException(status_code=404, detail="Source image is unavailable.")
            image_data, width, height = await asyncio.to_thread(
                _render_thumbnail, str(source_path), payload
            )
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise HTTPException(
            status_code=422,
            detail="The selected image could not be decoded for thumbnail rendering.",
        ) from error

    asset_id = uuid4()
    storage_key = f"users/{user.id}/projects/{project_id}/thumbnails/{asset_id}.png"

    async def chunks():
        yield image_data

    file_size = await storage.save_stream(storage_key, chunks())
    asset = MediaAsset(
        id=asset_id,
        owner_id=user.id,
        project_id=project_id,
        name=f"Thumbnail - {payload.title[:120]}.png",
        storage_key=storage_key,
        media_type="image",
        content_type="image/png",
        file_size=file_size,
        metadata_json={
            "thumbnail": {
                "width": width,
                "height": height,
                "source_asset_id": str(source.id),
                "aspect_ratio": payload.aspect_ratio,
            }
        },
    )
    session.add(asset)
    await session.commit()
    return ThumbnailRenderResponse(
        asset_id=asset.id,
        name=asset.name,
        width=width,
        height=height,
        content_type=asset.content_type,
    )


@router.get("/assets/{asset_id}/thumbnail", response_model=MediaAssetPublic)
async def read_thumbnail_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> MediaAsset:
    asset = await session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.owner_id == user.id,
            MediaAsset.media_type == "image",
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Thumbnail image not found.")
    return asset
