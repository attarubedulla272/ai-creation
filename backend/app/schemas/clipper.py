"""Smart Clipper request and response schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClipAnalysisCreate(BaseModel):
    project_id: UUID
    source_media_asset_id: UUID
    minimum_duration_seconds: float = Field(default=15, ge=3, le=180)
    maximum_duration_seconds: float = Field(default=60, ge=5, le=180)
    target_durations_seconds: list[Literal[15, 30, 45, 60]] | None = Field(
        default=None, min_length=1, max_length=4
    )
    ranking_preferences: dict[str, float] = Field(default_factory=dict, max_length=12)

    @model_validator(mode="after")
    def validate_duration_range(self) -> "ClipAnalysisCreate":
        if self.minimum_duration_seconds > self.maximum_duration_seconds:
            raise ValueError("Minimum clip duration must not exceed maximum duration.")
        if self.target_durations_seconds and len(set(self.target_durations_seconds)) != len(
            self.target_durations_seconds
        ):
            raise ValueError("Target clip durations must be unique.")
        if any(not 0 <= weight <= 3 for weight in self.ranking_preferences.values()):
            raise ValueError("Ranking preference weights must be between 0 and 3.")
        return self


class ClipCandidateUpdate(BaseModel):
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)


class ClipCaption(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=1000)
    speaker_label: str | None = Field(default=None, max_length=120)
    highlighted_words: list[str] = Field(default_factory=list, max_length=40)


class ClipCaptionsUpdate(BaseModel):
    captions: list[ClipCaption] = Field(max_length=500)


class ClipFramingUpdate(BaseModel):
    aspect_ratio: Literal["9:16", "1:1", "4:5", "16:9"] = "9:16"
    position_x: float = Field(default=0.5, ge=0, le=1)
    position_y: float = Field(default=0.5, ge=0, le=1)


class ClipRankingUpdate(BaseModel):
    preferences: dict[str, float] = Field(max_length=12)

    @model_validator(mode="after")
    def validate_weights(self) -> "ClipRankingUpdate":
        if any(not 0 <= weight <= 3 for weight in self.preferences.values()):
            raise ValueError("Ranking preference weights must be between 0 and 3.")
        return self


class ClipExportCreate(BaseModel):
    candidate_ids: list[UUID] = Field(min_length=1, max_length=50)
    aspect_ratio: Literal["9:16", "1:1", "4:5", "16:9"] = "9:16"
    resolution: Literal["720p", "1080p"] = "1080p"
    captions: bool = False
    caption_position: Literal["top", "center", "bottom"] = "bottom"
    caption_theme: Literal["boxed", "outline", "minimal"] = "boxed"
    caption_font_size: int = Field(default=36, ge=18, le=48)
    caption_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    caption_background_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    caption_outline_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    animated_highlighting: bool = False
    watermark: str | None = Field(default=None, max_length=100)


class ClipCandidatePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    source_asset_id: UUID | None
    title: str | None
    start_seconds: float
    end_seconds: float
    score: float | None
    scoring_factors: dict[str, Any] | None
    scene_ranges: list[dict[str, Any]] | None
    explanation: str | None
    status: str
    transcript_text: str | None
    caption_data: list[dict[str, Any]] | None
    framing_data: dict[str, Any] | None
    exported_media_asset_id: UUID | None
    created_at: datetime


class ClipJobPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    job_type: str
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    error_message: str | None
    retry_count: int
    max_retries: int
    created_at: datetime
    updated_at: datetime
