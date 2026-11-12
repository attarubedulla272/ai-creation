"""Typed timeline persistence and export request schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimelineKeyframeData(BaseModel):
    """Linear or held property value at a clip-relative time."""

    time: float = Field(ge=0, le=86_400)
    property: Literal["x", "y", "scale", "opacity", "volume"]
    value: float = Field(ge=-2, le=4)
    interpolation: Literal["linear", "hold"] = "linear"

    @model_validator(mode="after")
    def validate_property_value(self) -> "TimelineKeyframeData":
        limits = {
            "x": (0, 1),
            "y": (0, 1),
            "scale": (0.05, 4),
            "opacity": (0, 1),
            "volume": (0, 2),
        }
        minimum, maximum = limits[self.property]
        if not minimum <= self.value <= maximum:
            raise ValueError(f"{self.property} keyframes must be between {minimum} and {maximum}.")
        return self


class TimelineEffectData(BaseModel):
    """Ordered, enabled visual filter applied to one timeline clip."""

    id: UUID
    type: Literal["brightness", "contrast", "saturation", "grayscale", "blur"]
    enabled: bool = True
    value: float = Field(ge=-1, le=50)

    @model_validator(mode="after")
    def validate_effect_value(self) -> "TimelineEffectData":
        limits = {
            "brightness": (-1, 1),
            "contrast": (0, 3),
            "saturation": (0, 3),
            "grayscale": (0, 1),
            "blur": (0, 20),
        }
        minimum, maximum = limits[self.type]
        if not minimum <= self.value <= maximum:
            raise ValueError(f"{self.type} effect value must be between {minimum} and {maximum}.")
        return self


class TimelineTextStyleData(BaseModel):
    """Serializable text appearance shared by canvas preview and FFmpeg export."""

    font_family: Literal["sans-serif", "serif", "monospace"] = "sans-serif"
    font_size: int = Field(default=48, ge=10, le=300)
    font_weight: Literal["normal", "bold"] = "bold"
    font_style: Literal["normal", "italic"] = "normal"
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    background_color: str = Field(default="#11111B", pattern=r"^#[0-9A-Fa-f]{6}$")
    background_opacity: float = Field(default=0, ge=0, le=1)
    outline_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_width: int = Field(default=2, ge=0, le=20)
    shadow_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    shadow_blur: int = Field(default=0, ge=0, le=20)
    alignment: Literal["left", "center", "right"] = "center"
    vertical_alignment: Literal["top", "middle", "bottom"] = "middle"
    width: float = Field(default=0.84, ge=0.1, le=1)


class TimelineSubtitleCue(BaseModel):
    """Parsed subtitle cue returned by the import endpoint."""

    start: float = Field(ge=0, le=86_400)
    duration: float = Field(gt=0, le=86_400)
    text: str = Field(min_length=1, max_length=10_000)


class TimelineClipData(BaseModel):
    """Timeline placement and source in/out range for one media asset."""

    id: UUID
    media_asset_id: UUID | None = None
    start: float = Field(ge=0, le=86_400)
    duration: float = Field(gt=0, le=86_400)
    source_start: float = Field(default=0, ge=0, le=86_400)
    source_end: float | None = Field(default=None, gt=0, le=86_400)
    text: str | None = Field(default=None, max_length=10_000)
    text_style: TimelineTextStyleData = Field(default_factory=TimelineTextStyleData)
    z_index: int = Field(default=0, ge=-1_000, le=1_000)
    label: str | None = Field(default=None, max_length=255)
    position_x: float = Field(default=0.5, ge=0, le=1)
    position_y: float = Field(default=0.5, ge=0, le=1)
    scale: float = Field(default=1, ge=0.05, le=4)
    opacity: float = Field(default=1, ge=0, le=1)
    volume: float = Field(default=1, ge=0, le=2)
    fade_in: float = Field(default=0, ge=0, le=86_400)
    fade_out: float = Field(default=0, ge=0, le=86_400)
    transition_in: Literal["none", "fade", "cross_dissolve", "wipe_left", "wipe_right"] = "none"
    transition_out: Literal["none", "fade", "cross_dissolve", "wipe_left", "wipe_right"] = "none"
    transition_in_version: Literal[0, 1] = 0
    transition_in_duration: float = Field(default=0.5, gt=0, le=10)
    transition_out_duration: float = Field(default=0.5, gt=0, le=10)
    brightness: float = Field(default=0, ge=-1, le=1)
    contrast: float = Field(default=1, ge=0, le=3)
    saturation: float = Field(default=1, ge=0, le=3)
    effects: list[TimelineEffectData] = Field(default_factory=list, max_length=20)
    keyframes: list[TimelineKeyframeData] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_source_range(self) -> "TimelineClipData":
        if self.text is not None and not self.text.strip():
            raise ValueError("Text clips cannot contain only whitespace.")
        if self.source_end is not None and self.source_end <= self.source_start:
            raise ValueError("source_end must be after source_start.")
        if self.source_end is not None and self.duration > self.source_end - self.source_start:
            raise ValueError("Clip duration cannot exceed its source trim range.")
        if self.fade_in > self.duration or self.fade_out > self.duration:
            raise ValueError("Clip fade duration cannot exceed the clip duration.")
        if self.transition_in != "none" and self.transition_in_duration > self.duration:
            raise ValueError("Clip transition duration cannot exceed the clip duration.")
        if self.transition_out != "none" and self.transition_out_duration > self.duration:
            raise ValueError("Clip transition duration cannot exceed the clip duration.")
        effect_ids = [effect.id for effect in self.effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise ValueError("Effect IDs must be unique within a clip.")
        property_times: set[tuple[str, float]] = set()
        for keyframe in self.keyframes:
            if keyframe.time > self.duration:
                raise ValueError("Keyframe time cannot exceed the clip duration.")
            identity = (keyframe.property, keyframe.time)
            if identity in property_times:
                raise ValueError("A clip cannot contain duplicate property keyframes at one time.")
            property_times.add(identity)
        return self


class TimelineTrackData(BaseModel):
    """One typed, ordered editor track."""

    id: UUID
    name: str = Field(min_length=1, max_length=120)
    type: Literal["video", "overlay", "audio", "subtitle"]
    muted: bool = False
    solo: bool = False
    locked: bool = False
    volume: float = Field(default=1, ge=0, le=2)
    clips: list[TimelineClipData] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_cross_dissolve_handles(self) -> "TimelineTrackData":
        clips = sorted(self.clips, key=lambda clip: (clip.start, str(clip.id)))
        for index, clip in enumerate(clips):
            if clip.effects and self.type not in {"video", "overlay"}:
                raise ValueError("Visual effects are supported only on video and overlay clips.")
            if clip.text is not None and self.type not in {"overlay", "subtitle"}:
                raise ValueError("Text clips must be placed on overlay or subtitle tracks.")
            if clip.text is not None and clip.media_asset_id is not None:
                raise ValueError("Text clips cannot reference a media asset.")
            if self.type == "subtitle" and clip.text is None:
                raise ValueError("Subtitle tracks require text clips.")
            if clip.transition_in != "cross_dissolve" or clip.transition_in_version == 0:
                continue
            if self.type != "video":
                raise ValueError("Cross dissolve is supported only between video clips.")
            if index == 0:
                raise ValueError("Cross dissolve requires an adjacent preceding video clip.")
            previous = clips[index - 1]
            overlap = previous.start + previous.duration - clip.start
            if previous.media_asset_id is None or clip.media_asset_id is None:
                raise ValueError("Cross dissolve requires two video media clips.")
            if overlap + 0.001 < clip.transition_in_duration:
                raise ValueError(
                    "Cross dissolve duration must fit within the overlap with the preceding clip."
                )
        return self


class TimelineData(BaseModel):
    """Versioned structured timeline document."""

    version: Literal[1] = 1
    name: str = Field(default="Main timeline", min_length=1, max_length=160)
    frame_rate: float = Field(default=24, ge=1, le=120)
    width: int = Field(default=1920, ge=16, le=7680)
    height: int = Field(default=1080, ge=16, le=7680)
    tracks: list[TimelineTrackData] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def limit_total_clips(self) -> "TimelineData":
        if sum(len(track.clips) for track in self.tracks) > 500:
            raise ValueError("A timeline cannot contain more than 500 clips.")
        return self


class TimelineResponse(BaseModel):
    """Persisted timeline for an owner-accessible project."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    duration_seconds: float
    frame_rate: float
    width: int
    height: int
    timeline_data: TimelineData
    updated_at: datetime


class TimelineExportRequest(BaseModel):
    """Requested clip sequence and optional simple audio bed."""

    selected_clip_ids: list[UUID] = Field(default_factory=list, max_length=500)
    preset: Literal["720p", "1080p", "4k"] | None = None


class TimelineTextValidationRequest(BaseModel):
    """Timeline and resolution to validate with the actual text export renderer."""

    timeline: TimelineData
    preset: Literal["720p", "1080p", "4k"] | None = None


class TimelineTextValidationIssue(BaseModel):
    """One actionable text-rendering problem or warning."""

    clip_id: UUID
    track_name: str
    severity: Literal["error", "warning"]
    code: Literal["font", "layout", "empty_text", "subtitle_duration", "unsupported_style"]
    message: str
    recommendation: str
    alternatives: list[str] = Field(default_factory=list)


class TimelineTextValidationResponse(BaseModel):
    """Blocking and advisory results for active text clips."""

    issues: list[TimelineTextValidationIssue] = Field(default_factory=list)


class TimelineTextFitRequest(BaseModel):
    """Request a non-persistent, reviewable text-fit proposal."""

    timeline: TimelineData
    clip_id: UUID
    operation: Literal["fit_width", "shrink", "split"]
    preset: Literal["720p", "1080p", "4k"] | None = None
    minimum_font_size: int = Field(default=18, ge=10, le=300)


class TimelineTextFitResponse(BaseModel):
    """Proposed timeline edits; the client applies them only after review."""

    timeline: TimelineData
    warnings: list[str] = Field(default_factory=list)


class TimelineExportResponse(BaseModel):
    """Queued timeline render status."""

    job_id: UUID
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    download_url: str | None = None
    error_message: str | None = None


class TimelineExportJobPublic(BaseModel):
    """Export job status visible to its owner."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    error_message: str | None
    output_data: dict[str, object] | None
    retry_count: int
    max_retries: int
    cancellation_requested: bool
