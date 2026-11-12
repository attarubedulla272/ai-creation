"""Request and response models for voice workflows."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VoiceConsentCreate(BaseModel):
    accepted: Literal[True]
    authorization_basis: Literal["self_attestation", "authorized_person"]
    consent_text_version: str = "voice-consent-v1"
    evidence_reference: str | None = Field(default=None, max_length=512)


class VoiceConsentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    authorization_basis: str
    consent_text_version: str
    granted_at: datetime
    revoked_at: datetime | None


class VoiceProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    language: str | None = Field(default=None, max_length=32)
    consent_id: UUID
    reference_asset_id: UUID | None = None


class VoiceProfilePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    language: str | None
    status: str
    reference_asset_id: UUID | None
    consent_id: UUID
    created_at: datetime


class TranscriptionCreate(BaseModel):
    project_id: UUID
    media_asset_id: UUID
    language: str | None = Field(default=None, min_length=2, max_length=32)


class VoiceJobPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    output_data: dict[str, Any] | None
    error_message: str | None
    retry_count: int
    max_retries: int
    created_at: datetime
    updated_at: datetime


class TranscriptSegmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_index: int
    start_seconds: float
    end_seconds: float
    text: str
    speaker_label: str | None
    translated_text: str | None
    voice_profile_id: UUID | None
    speech_rate: float


class TranscriptPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    media_asset_id: UUID | None
    language: str | None
    status: str
    segments: list[TranscriptSegmentPublic]
    created_at: datetime


class TranscriptSegmentUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=10000)
    speaker_label: str | None = Field(default=None, max_length=120)
    translated_text: str | None = Field(default=None, max_length=10000)


class TranscriptRevisionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transcript_id: UUID
    revision_number: int
    snapshot: list[dict[str, Any]]
    created_at: datetime


class DubbingProjectCreate(BaseModel):
    transcript_id: UUID
    target_language: str = Field(min_length=2, max_length=32)


class DubbingGlossaryTerm(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    translation: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=500)


class DubbingSegmentPublic(BaseModel):
    id: UUID
    source_segment_id: UUID
    order_index: int
    start_seconds: float
    end_seconds: float
    source_text: str
    translated_text: str
    speaker_label: str | None
    voice_profile_id: UUID | None
    speech_rate: float
    audio_asset_id: UUID | None
    audio_source: Literal["user_supplied"] | None
    original_start_seconds: float
    original_end_seconds: float
    audio_duration_seconds: float | None
    translation_approved: bool
    translation_status: Literal[
        "not_translated", "queued", "completed", "failed", "cancelled", "manual"
    ] = "not_translated"
    translation_provider: str | None = None
    translation_model: str | None = None
    translation_model_version: str | None = None
    translation_error: str | None = None
    segment_approved: bool
    timing_conflict: bool
    processing_status: Literal["not_generated", "user_audio_attached"]
    generated_audio_path: str | None


class DubbingProjectPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    transcript_id: UUID
    target_language: str
    status: str
    segments_data: list[dict[str, Any]]
    glossary: list[DubbingGlossaryTerm]
    created_at: datetime


class DubbingSegmentUpdate(BaseModel):
    id: UUID
    translated_text: str | None = Field(default=None, max_length=10000)
    voice_profile_id: UUID | None = None
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    speech_rate: float | None = Field(default=None, ge=0.5, le=2.0)
    audio_asset_id: UUID | None = None
    translation_approved: bool | None = None
    segment_approved: bool | None = None


class DubbingProjectUpdate(BaseModel):
    segments: list[DubbingSegmentUpdate]
    glossary: list[DubbingGlossaryTerm] | None = None


class TranslationQueueRequest(BaseModel):
    regenerate_existing: bool = False


class DubbingExportRequest(BaseModel):
    source_video_asset_id: UUID | None = None


class SpeechPreviewRequest(BaseModel):
    voice_profile_id: UUID
    text: str = Field(min_length=1, max_length=3000)
    language: str = Field(min_length=2, max_length=32)
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)
