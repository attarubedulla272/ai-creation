"""Media asset and processing-job response schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MediaAssetPublic(BaseModel):
    """Safe media metadata returned to its owner."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    name: str
    media_type: str
    content_type: str
    file_size: int
    duration_seconds: float | None
    metadata_json: dict[str, Any] | None
    created_at: datetime


class MediaUploadResponse(BaseModel):
    """Created asset and its asynchronous processing job."""

    asset: MediaAssetPublic
    job_id: UUID


class ProcessingJobPublic(BaseModel):
    """Owner-visible media processing progress."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    output_data: dict[str, Any] | None
    error_message: str | None
    retry_count: int
    max_retries: int
    cancellation_requested: bool
    created_at: datetime
    updated_at: datetime
