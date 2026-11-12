"""Typed project planning, character, environment, scene, and shot schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

VisualStyle = Literal[
    "realistic",
    "cinematic",
    "documentary",
    "2d_animation",
    "3d_animation",
    "anime",
    "cartoon",
    "map_animation",
    "product_commercial",
]
CameraMovement = Literal[
    "static",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "dolly_in",
    "dolly_out",
    "tracking",
    "orbit",
    "handheld",
    "crane",
    "drone",
]


class ProjectStoryUpdate(BaseModel):
    story_idea: str | None = Field(default=None, max_length=10_000)
    story_outline: str | None = Field(default=None, max_length=50_000)
    script_text: str | None = Field(default=None, max_length=100_000)
    visual_settings: dict[str, Any] | None = None


class ProjectStoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    story_idea: str | None
    story_outline: str | None
    script_text: str | None
    visual_settings: dict[str, Any] | None
    updated_at: datetime


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=10_000)
    identity_description: str | None = Field(default=None, max_length=10_000)
    outfit_settings: dict[str, Any] = Field(default_factory=dict)
    visual_traits: dict[str, Any] = Field(default_factory=dict)


class CharacterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=10_000)
    identity_description: str | None = Field(default=None, max_length=10_000)
    outfit_settings: dict[str, Any] | None = None
    visual_traits: dict[str, Any] | None = None


class CharacterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    identity_description: str | None
    outfit_settings: dict[str, Any] | None
    visual_traits: dict[str, Any] | None
    created_at: datetime


class CharacterReferenceCreate(BaseModel):
    media_asset_id: UUID
    reference_type: Literal["character_sheet", "face", "outfit", "pose", "other"] = (
        "character_sheet"
    )
    description: str | None = Field(default=None, max_length=4000)


class CharacterReferencePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    character_id: UUID
    media_asset_id: UUID | None
    reference_type: str
    description: str | None
    created_at: datetime


class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=10_000)
    visual_traits: dict[str, Any] = Field(default_factory=dict)
    reference_asset_id: UUID | None = None


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=10_000)
    visual_traits: dict[str, Any] | None = None
    reference_asset_id: UUID | None = None


class EnvironmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    description: str | None
    visual_traits: dict[str, Any] | None
    reference_asset_id: UUID | None
    created_at: datetime


class SceneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10_000)
    scene_prompt: str | None = Field(default=None, max_length=20_000)
    duration_seconds: float = Field(default=5, gt=0, le=600)
    order_index: int = Field(default=0, ge=0, le=10_000)
    visual_style: VisualStyle | None = None
    camera_movement: CameraMovement | None = None
    lighting: str | None = Field(default=None, max_length=120)
    color_palette: str | None = Field(default=None, max_length=160)
    environment_id: UUID | None = None
    character_ids: list[UUID] = Field(default_factory=list, max_length=50)
    first_frame_asset_id: UUID | None = None
    last_frame_asset_id: UUID | None = None
    continuity_notes: str | None = Field(default=None, max_length=10_000)


class SceneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10_000)
    scene_prompt: str | None = Field(default=None, max_length=20_000)
    duration_seconds: float | None = Field(default=None, gt=0, le=600)
    order_index: int | None = Field(default=None, ge=0, le=10_000)
    visual_style: VisualStyle | None = None
    camera_movement: CameraMovement | None = None
    lighting: str | None = Field(default=None, max_length=120)
    color_palette: str | None = Field(default=None, max_length=160)
    environment_id: UUID | None = None
    character_ids: list[UUID] | None = Field(default=None, max_length=50)
    first_frame_asset_id: UUID | None = None
    last_frame_asset_id: UUID | None = None
    continuity_notes: str | None = Field(default=None, max_length=10_000)


class SceneShotCreate(BaseModel):
    description: str = Field(min_length=1, max_length=10_000)
    shot_prompt: str | None = Field(default=None, max_length=20_000)
    order_index: int = Field(default=0, ge=0, le=10_000)
    duration_seconds: float | None = Field(default=None, gt=0, le=600)
    camera_movement: CameraMovement | None = None
    media_asset_id: UUID | None = None
    first_frame_asset_id: UUID | None = None
    last_frame_asset_id: UUID | None = None


class SceneShotUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=10_000)
    shot_prompt: str | None = Field(default=None, max_length=20_000)
    order_index: int | None = Field(default=None, ge=0, le=10_000)
    duration_seconds: float | None = Field(default=None, gt=0, le=600)
    camera_movement: CameraMovement | None = None
    media_asset_id: UUID | None = None
    first_frame_asset_id: UUID | None = None
    last_frame_asset_id: UUID | None = None


class SceneShotPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scene_id: UUID
    order_index: int
    description: str
    shot_prompt: str | None
    duration_seconds: float | None
    camera_movement: str | None
    media_asset_id: UUID | None
    first_frame_asset_id: UUID | None
    last_frame_asset_id: UUID | None


class ScenePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    order_index: int
    title: str
    description: str | None
    visual_style: str | None
    scene_prompt: str | None
    duration_seconds: float
    camera_movement: str | None
    lighting: str | None
    color_palette: str | None
    environment_id: UUID | None
    character_ids: list[str]
    first_frame_asset_id: UUID | None
    last_frame_asset_id: UUID | None
    generation_status: str
    generation_job_id: UUID | None
    generated_media_asset_id: UUID | None
    generated_preview_label: str | None
    generation_provider: str | None
    is_approved: bool
    continuity_notes: str | None
    shots: list[SceneShotPublic]
    created_at: datetime
    updated_at: datetime


class SceneGenerationJobPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    job_type: str
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    model_name: str | None
    model_version: str | None
    model_license: str | None
    commercial_use_permitted: bool | None
    generation_mode: str | None
    generation_settings: dict[str, Any] | None
    worker_job_id: str | None
    retry_count: int
    max_retries: int
    cancellation_requested: bool
    output_data: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class SceneApprovalUpdate(BaseModel):
    is_approved: bool


class SceneContinuityCheck(BaseModel):
    scene_id: UUID
    scene_title: str
    issues: list[str]


class SceneContinuityReport(BaseModel):
    project_id: UUID
    scenes: list[SceneContinuityCheck]
    issue_count: int


class StoryboardAssemblyResponse(BaseModel):
    timeline_id: UUID
    project_id: UUID
    video_asset_count: int
    message: str


class ContentProviderStatus(BaseModel):
    available: bool
    provider: str | None
    preview_only: bool
    self_hosted_worker_supported: bool


class SceneGenerationRequest(BaseModel):
    generation_mode: Literal["text_to_video", "image_to_video"] = "text_to_video"
    model_id: str = "operator-configured"
    settings: dict[str, Any] = Field(default_factory=dict)


class GenerationModelRegistryEntry(BaseModel):
    id: str
    model_name: str
    model_version: str
    repository: str | None
    model_license: str
    commercial_use_permitted: bool | None
    gpu_requirement: str
    supported_languages: list[str]
    generation_modes: list[Literal["text_to_video", "image_to_video"]]
    installation_instructions: str
    availability: Literal["mock", "operator_configured"]


class WorkerReferenceAsset(BaseModel):
    asset_id: UUID
    role: Literal["first_frame", "last_frame", "character_reference", "environment_reference"]
    download_url: str | None = None
    character_id: UUID | None = None


class SceneProviderRequest(BaseModel):
    project_id: UUID
    scene_id: UUID
    generation_mode: Literal["text_to_video", "image_to_video"] = "text_to_video"
    title: str
    prompt: str
    visual_style: str | None = None
    camera_movement: str | None = None
    lighting: str | None = None
    color_palette: str | None = None
    character_ids: list[str]
    environment_id: UUID | None = None
    first_frame_asset_id: UUID | None = None
    last_frame_asset_id: UUID | None = None
    model_id: str = "operator-configured"
    model_name: str
    model_version: str | None = None
    model_license: str
    commercial_use_permitted: bool | None = None
    generation_settings: dict[str, Any] = Field(default_factory=dict)
    reference_assets: list["WorkerReferenceAsset"] = Field(default_factory=list)
    settings_snapshot: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_prompt(self) -> "SceneProviderRequest":
        if not self.prompt.strip():
            raise ValueError("A scene prompt is required before requesting generation.")
        if self.generation_mode == "image_to_video" and self.first_frame_asset_id is None:
            raise ValueError("Image-to-video generation requires a first-frame reference image.")
        return self


class SceneWorkerJobStatus(BaseModel):
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int = Field(ge=0, le=100)
    output_metadata: dict[str, Any] = Field(default_factory=dict)
    preview_only: bool = False
    preview_label: str | None = None
    error_message: str | None = None
    output_available: bool = False
