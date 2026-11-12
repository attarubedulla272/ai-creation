"""SEO metadata, release calendar, and thumbnail request/response schemas."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

PublicationStatus = Literal["draft", "ready", "scheduled", "published"]
DraftStatus = Literal["draft", "ready", "scheduled"]
PublicationPlatform = Literal["youtube", "instagram", "tiktok", "other"]
MetadataTerm = Annotated[str, Field(min_length=1, max_length=100)]


class ChapterInput(BaseModel):
    timestamp_seconds: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def require_chapter_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Chapter titles cannot be blank.")
        return normalized


class PublicationCreate(BaseModel):
    platform: PublicationPlatform = "youtube"
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[MetadataTerm] = Field(default_factory=list, max_length=50)
    hashtags: list[MetadataTerm] = Field(default_factory=list, max_length=50)
    primary_keywords: list[MetadataTerm] = Field(default_factory=list, max_length=20)
    secondary_keywords: list[MetadataTerm] = Field(default_factory=list, max_length=50)
    chapters: list[ChapterInput] = Field(default_factory=list, max_length=100)
    language: str | None = Field(default=None, max_length=35)
    category: str | None = Field(default=None, max_length=100)
    media_asset_id: UUID | None = None
    clip_candidate_id: UUID | None = None
    thumbnail_asset_id: UUID | None = None
    status: DraftStatus = "draft"
    scheduled_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def require_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Title cannot be blank.")
        return normalized

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("The planned publication date must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_publication(self) -> "PublicationCreate":
        _validate_metadata(self)
        if self.status == "scheduled" and self.scheduled_at is None:
            raise ValueError("A scheduled publication requires a planned publication date.")
        if self.status != "scheduled" and self.scheduled_at is not None:
            raise ValueError("A planned publication date is only valid for scheduled entries.")
        return self


class PublicationUpdate(BaseModel):
    platform: PublicationPlatform | None = None
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[MetadataTerm] | None = Field(default=None, max_length=50)
    hashtags: list[MetadataTerm] | None = Field(default=None, max_length=50)
    primary_keywords: list[MetadataTerm] | None = Field(default=None, max_length=20)
    secondary_keywords: list[MetadataTerm] | None = Field(default=None, max_length=50)
    chapters: list[ChapterInput] | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=35)
    category: str | None = Field(default=None, max_length=100)
    media_asset_id: UUID | None = None
    clip_candidate_id: UUID | None = None
    thumbnail_asset_id: UUID | None = None
    status: DraftStatus | None = None
    scheduled_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def require_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Title cannot be blank.")
        return normalized

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("The planned publication date must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_metadata(self) -> "PublicationUpdate":
        _validate_metadata(self)
        if self.status is not None and self.status != "scheduled" and self.scheduled_at is not None:
            raise ValueError("A planned publication date is only valid for scheduled entries.")
        return self


class PublicationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    platform: str
    title: str | None
    description: str | None
    status: PublicationStatus
    scheduled_at: datetime | None
    published_at: datetime | None
    external_id: str | None
    metadata_json: dict[str, Any] | None
    media_asset_id: UUID | None
    clip_candidate_id: UUID | None
    thumbnail_asset_id: UUID | None
    version: int
    youtube_status: str | None
    youtube_privacy_status: str | None
    youtube_url: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("scheduled_at", "published_at")
    def serialize_publication_dates(self, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class PublicationRevisionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    publication_id: UUID
    version: int
    snapshot: dict[str, Any]
    created_at: datetime


class ThumbnailRenderRequest(BaseModel):
    source_asset_id: UUID
    title: str = Field(min_length=1, max_length=200)
    aspect_ratio: Literal["16:9", "1:1", "9:16"] = "16:9"
    text_position: Literal["top", "center", "bottom"] = "bottom"
    font_size: int = Field(default=64, ge=18, le=140)
    text_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    crop_x: float = Field(default=0.5, ge=0, le=1)
    crop_y: float = Field(default=0.5, ge=0, le=1)


class ThumbnailRenderResponse(BaseModel):
    asset_id: UUID
    name: str
    width: int
    height: int
    content_type: str


class TitleSuggestionRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=160)
    keywords: list[MetadataTerm] = Field(default_factory=list, max_length=5)

    @field_validator("topic")
    @classmethod
    def require_topic(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Topic cannot be blank.")
        return normalized

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Keywords cannot contain blank values.")
        return normalized


class TitleSuggestionResponse(BaseModel):
    suggestions: list[str]
    method: Literal["local_templates"]


class YouTubeConnectionPublic(BaseModel):
    id: UUID
    channel_id: str
    channel_title: str
    channel_custom_url: str | None
    status: Literal["connected", "reauthorization_required"]
    analytics_enabled: bool


class YouTubeOAuthStartResponse(BaseModel):
    authorization_url: str


class YouTubeDisconnectResponse(BaseModel):
    disconnected: bool
    provider_revoked: bool
    warning: str | None


class YouTubeUploadRequest(BaseModel):
    connection_id: UUID
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    publish_at: datetime | None = None

    @field_validator("publish_at")
    @classmethod
    def require_publish_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("YouTube publish time must include a timezone.")
        return value


class YouTubeUploadJobPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: Literal["youtube_upload"]
    input_data: dict[str, Any] | None
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    output_data: dict[str, Any] | None
    error_message: str | None
    retry_count: int
    max_retries: int
    cancellation_requested: bool
    created_at: datetime
    updated_at: datetime


class YouTubeAnalyticsPublic(BaseModel):
    daily: dict[str, Any]
    traffic_sources: dict[str, Any]
    available_through: str | None


def _validate_metadata(payload: BaseModel) -> None:
    values = payload.model_dump(exclude_unset=True)
    for key in ("tags", "hashtags", "primary_keywords", "secondary_keywords"):
        items = values.get(key)
        if key in values:
            if items is None or any(not value.strip() for value in items):
                raise ValueError(
                    f"{key.replace('_', ' ').capitalize()} cannot contain blank values."
                )
            if key == "tags" and sum(len(value) for value in items) > 500:
                raise ValueError("YouTube tags must not exceed 500 characters in total.")
    chapters = values.get("chapters")
    if "chapters" in values:
        if chapters is None:
            raise ValueError("Chapters must be a list.")
        timestamps = [chapter["timestamp_seconds"] for chapter in chapters]
        if timestamps != sorted(set(timestamps)):
            raise ValueError("Chapter timestamps must be unique and in ascending order.")
