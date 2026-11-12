"""Owner-scoped Script-to-Film planning and isolated scene generation routes."""

from __future__ import annotations

from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.errors import APIError
from app.models.character import Character, CharacterReference
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.models.scene import EnvironmentReference, Scene, SceneShot
from app.models.timeline import Timeline
from app.schemas.content import (
    CharacterCreate,
    CharacterPublic,
    CharacterReferenceCreate,
    CharacterReferencePublic,
    CharacterUpdate,
    ContentProviderStatus,
    EnvironmentCreate,
    EnvironmentPublic,
    EnvironmentUpdate,
    GenerationModelRegistryEntry,
    ProjectStoryPublic,
    ProjectStoryUpdate,
    SceneApprovalUpdate,
    SceneContinuityCheck,
    SceneContinuityReport,
    SceneCreate,
    SceneGenerationJobPublic,
    SceneGenerationRequest,
    SceneProviderRequest,
    ScenePublic,
    SceneShotCreate,
    SceneShotPublic,
    SceneShotUpdate,
    SceneUpdate,
    StoryboardAssemblyResponse,
    WorkerReferenceAsset,
)
from app.schemas.timeline import TimelineData, TimelineTrackData
from app.services.content_providers import (
    MOCK_MODEL_ID,
    OPERATOR_MODEL_ID,
    SceneGenerationProvider,
    generation_model_registry,
)

router = APIRouter(prefix="/projects", tags=["content studio"])
jobs_router = APIRouter(prefix="/content/jobs", tags=["content generation"])
registry_router = APIRouter(prefix="/content", tags=["content generation"])
DEFAULT_SCENE_GENERATION_REQUEST = SceneGenerationRequest()

IMAGE_OR_VIDEO = {"image", "video"}
VISUAL_STYLES = {
    "realistic",
    "cinematic",
    "documentary",
    "2d_animation",
    "3d_animation",
    "anime",
    "cartoon",
    "map_animation",
    "product_commercial",
}


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


async def _owned_scene(
    project_id: UUID,
    scene_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
) -> Scene:
    scene = await session.scalar(
        select(Scene)
        .join(Project, Project.id == Scene.project_id)
        .options(selectinload(Scene.shots))
        .where(
            Scene.id == scene_id,
            Scene.project_id == project_id,
            Project.owner_id == owner_id,
        )
    )
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found.")
    return scene


async def _owned_character(
    project_id: UUID,
    character_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
) -> Character:
    character = await session.scalar(
        select(Character)
        .join(Project, Project.id == Character.project_id)
        .where(
            Character.id == character_id,
            Character.project_id == project_id,
            Project.owner_id == owner_id,
        )
    )
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    return character


async def _validate_reference_asset(
    asset_id: UUID | None,
    owner_id: UUID,
    session: SessionDependency,
    allowed_types: set[str] = IMAGE_OR_VIDEO,
    project_id: UUID | None = None,
) -> MediaAsset | None:
    if asset_id is None:
        return None
    filters = [
        MediaAsset.id == asset_id,
        MediaAsset.owner_id == owner_id,
        MediaAsset.media_type.in_(allowed_types),
    ]
    if project_id is not None:
        filters.append(or_(MediaAsset.project_id == project_id, MediaAsset.project_id.is_(None)))
    asset = await session.scalar(select(MediaAsset).where(*filters))
    if asset is None:
        raise HTTPException(
            status_code=404,
            detail=f"Owned {'/'.join(sorted(allowed_types))} reference not found.",
        )
    return asset


async def _validate_scene_references(
    project_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
    *,
    environment_id: UUID | None,
    character_ids: list[UUID],
    first_frame_asset_id: UUID | None,
    last_frame_asset_id: UUID | None,
) -> None:
    if environment_id is not None:
        environment = await session.scalar(
            select(EnvironmentReference).where(
                EnvironmentReference.id == environment_id,
                EnvironmentReference.project_id == project_id,
            )
        )
        if environment is None:
            raise HTTPException(
                status_code=404, detail="Environment reference not found in this project."
            )
    if character_ids:
        characters = await session.scalars(
            select(Character.id).where(
                Character.project_id == project_id,
                Character.id.in_(set(character_ids)),
            )
        )
        if set(characters.all()) != set(character_ids):
            raise HTTPException(
                status_code=404, detail="One or more characters are not in this project."
            )
    await _validate_reference_asset(
        first_frame_asset_id, owner_id, session, {"image"}, project_id=project_id
    )
    await _validate_reference_asset(
        last_frame_asset_id, owner_id, session, {"image"}, project_id=project_id
    )


@router.get("/{project_id}/content", response_model=ProjectStoryPublic)
async def read_project_story(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> Project:
    return await _owned_project(project_id, user.id, session)


@router.put("/{project_id}/content", response_model=ProjectStoryPublic)
async def update_project_story(
    project_id: UUID,
    payload: ProjectStoryUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> Project:
    project = await _owned_project(project_id, user.id, session)
    values = payload.model_dump(exclude_unset=True)
    visual_settings = values.get("visual_settings")
    if visual_settings is not None:
        style = visual_settings.get("visual_style")
        if style is not None and style not in VISUAL_STYLES:
            raise APIError(
                422, "invalid_visual_style", "Choose one of the supported visual styles."
            )
        values["visual_settings"] = dict(visual_settings)
    for field, value in values.items():
        setattr(project, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("/{project_id}/characters", response_model=list[CharacterPublic])
async def list_characters(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[Character]:
    await _owned_project(project_id, user.id, session)
    result = await session.scalars(
        select(Character)
        .where(Character.project_id == project_id)
        .order_by(Character.created_at, Character.id)
    )
    return list(result.all())


@router.post(
    "/{project_id}/characters",
    response_model=CharacterPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_character(
    project_id: UUID,
    payload: CharacterCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> Character:
    await _owned_project(project_id, user.id, session)
    character = Character(
        project_id=project_id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        identity_description=payload.identity_description,
        outfit_settings=payload.outfit_settings,
        visual_traits=payload.visual_traits,
    )
    session.add(character)
    await session.commit()
    await session.refresh(character)
    return character


@router.patch("/{project_id}/characters/{character_id}", response_model=CharacterPublic)
async def update_character(
    project_id: UUID,
    character_id: UUID,
    payload: CharacterUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> Character:
    character = await _owned_character(project_id, character_id, user.id, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(character, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    await session.refresh(character)
    return character


@router.delete(
    "/{project_id}/characters/{character_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_character(
    project_id: UUID,
    character_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> None:
    character = await _owned_character(project_id, character_id, user.id, session)
    await session.delete(character)
    await session.commit()


@router.get(
    "/{project_id}/characters/{character_id}/references",
    response_model=list[CharacterReferencePublic],
)
async def list_character_references(
    project_id: UUID,
    character_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[CharacterReference]:
    await _owned_character(project_id, character_id, user.id, session)
    result = await session.scalars(
        select(CharacterReference)
        .where(CharacterReference.character_id == character_id)
        .order_by(CharacterReference.created_at, CharacterReference.id)
    )
    return list(result.all())


@router.post(
    "/{project_id}/characters/{character_id}/references",
    response_model=CharacterReferencePublic,
    status_code=status.HTTP_201_CREATED,
)
async def add_character_reference(
    project_id: UUID,
    character_id: UUID,
    payload: CharacterReferenceCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> CharacterReference:
    await _owned_character(project_id, character_id, user.id, session)
    await _validate_reference_asset(
        payload.media_asset_id,
        user.id,
        session,
        {"image"},
        project_id=project_id,
    )
    reference = CharacterReference(
        character_id=character_id,
        media_asset_id=payload.media_asset_id,
        reference_type=payload.reference_type,
        description=payload.description,
    )
    session.add(reference)
    await session.commit()
    await session.refresh(reference)
    return reference


@router.get("/{project_id}/environments", response_model=list[EnvironmentPublic])
async def list_environments(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[EnvironmentReference]:
    await _owned_project(project_id, user.id, session)
    result = await session.scalars(
        select(EnvironmentReference)
        .where(EnvironmentReference.project_id == project_id)
        .order_by(EnvironmentReference.created_at, EnvironmentReference.id)
    )
    return list(result.all())


@router.post(
    "/{project_id}/environments",
    response_model=EnvironmentPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment(
    project_id: UUID,
    payload: EnvironmentCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> EnvironmentReference:
    await _owned_project(project_id, user.id, session)
    await _validate_reference_asset(
        payload.reference_asset_id, user.id, session, {"image"}, project_id=project_id
    )
    environment = EnvironmentReference(
        project_id=project_id,
        name=payload.name.strip(),
        description=payload.description,
        visual_traits=payload.visual_traits,
        reference_asset_id=payload.reference_asset_id,
    )
    session.add(environment)
    await session.commit()
    await session.refresh(environment)
    return environment


@router.patch("/{project_id}/environments/{environment_id}", response_model=EnvironmentPublic)
async def update_environment(
    project_id: UUID,
    environment_id: UUID,
    payload: EnvironmentUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> EnvironmentReference:
    await _owned_project(project_id, user.id, session)
    environment = await session.scalar(
        select(EnvironmentReference).where(
            EnvironmentReference.id == environment_id,
            EnvironmentReference.project_id == project_id,
        )
    )
    if environment is None:
        raise HTTPException(status_code=404, detail="Environment reference not found.")
    values = payload.model_dump(exclude_unset=True)
    if "reference_asset_id" in values:
        await _validate_reference_asset(
            values["reference_asset_id"], user.id, session, {"image"}, project_id=project_id
        )
    for field, value in values.items():
        setattr(environment, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    await session.refresh(environment)
    return environment


@router.delete(
    "/{project_id}/environments/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_environment(
    project_id: UUID,
    environment_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> None:
    await _owned_project(project_id, user.id, session)
    environment = await session.scalar(
        select(EnvironmentReference).where(
            EnvironmentReference.id == environment_id,
            EnvironmentReference.project_id == project_id,
        )
    )
    if environment is None:
        raise HTTPException(status_code=404, detail="Environment reference not found.")
    await session.delete(environment)
    await session.commit()


@router.get("/{project_id}/scenes", response_model=list[ScenePublic])
async def list_scenes(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[Scene]:
    await _owned_project(project_id, user.id, session)
    result = await session.scalars(
        select(Scene)
        .options(selectinload(Scene.shots))
        .where(Scene.project_id == project_id)
        .order_by(Scene.order_index, Scene.created_at, Scene.id)
    )
    return list(result.unique().all())


@router.post(
    "/{project_id}/scenes",
    response_model=ScenePublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_scene(
    project_id: UUID,
    payload: SceneCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> Scene:
    project = await _owned_project(project_id, user.id, session)
    await _validate_scene_references(
        project_id,
        user.id,
        session,
        environment_id=payload.environment_id,
        character_ids=payload.character_ids,
        first_frame_asset_id=payload.first_frame_asset_id,
        last_frame_asset_id=payload.last_frame_asset_id,
    )
    style = payload.visual_style
    if style is None:
        style = (project.visual_settings or {}).get("visual_style")
    scene = Scene(
        project_id=project_id,
        title=payload.title.strip(),
        description=payload.description,
        scene_prompt=payload.scene_prompt,
        duration_seconds=payload.duration_seconds,
        order_index=payload.order_index,
        visual_style=style,
        camera_movement=payload.camera_movement,
        lighting=payload.lighting,
        color_palette=payload.color_palette,
        environment_id=payload.environment_id,
        character_ids=[str(item) for item in payload.character_ids],
        first_frame_asset_id=payload.first_frame_asset_id,
        last_frame_asset_id=payload.last_frame_asset_id,
        continuity_notes=payload.continuity_notes,
    )
    session.add(scene)
    await session.commit()
    return await _owned_scene(project_id, scene.id, user.id, session)


@router.patch("/{project_id}/scenes/{scene_id}", response_model=ScenePublic)
async def update_scene(
    project_id: UUID,
    scene_id: UUID,
    payload: SceneUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> Scene:
    scene = await _owned_scene(project_id, scene_id, user.id, session)
    values = payload.model_dump(exclude_unset=True)
    references_changed = any(
        key in values
        for key in (
            "environment_id",
            "character_ids",
            "first_frame_asset_id",
            "last_frame_asset_id",
        )
    )
    if references_changed:
        await _validate_scene_references(
            project_id,
            user.id,
            session,
            environment_id=values.get("environment_id", scene.environment_id),
            character_ids=values.get(
                "character_ids",
                [UUID(item) for item in scene.character_ids],
            ),
            first_frame_asset_id=values.get("first_frame_asset_id", scene.first_frame_asset_id),
            last_frame_asset_id=values.get("last_frame_asset_id", scene.last_frame_asset_id),
        )
    if "character_ids" in values:
        values["character_ids"] = [str(item) for item in values["character_ids"]]
    changed_prompt = any(
        key in values
        for key in (
            "scene_prompt",
            "visual_style",
            "camera_movement",
            "lighting",
            "color_palette",
            "character_ids",
            "environment_id",
            "first_frame_asset_id",
            "last_frame_asset_id",
        )
    )
    for field, value in values.items():
        setattr(scene, field, value.strip() if isinstance(value, str) else value)
    if changed_prompt:
        scene.is_approved = False
        previous_job = (
            await session.get(ProcessingJob, scene.generation_job_id)
            if scene.generation_job_id is not None
            else None
        )
        if previous_job is not None and previous_job.status == "queued":
            previous_job.status = "cancelled"
        elif previous_job is not None and previous_job.status == "processing":
            previous_job.cancellation_requested = True
        scene.generation_job_id = None
        scene.generation_status = "not_started"
        scene.generated_media_asset_id = None
        scene.generated_preview_label = None
        scene.generation_provider = None
    await session.commit()
    return await _owned_scene(project_id, scene_id, user.id, session)


@router.delete("/{project_id}/scenes/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scene(
    project_id: UUID,
    scene_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> None:
    scene = await _owned_scene(project_id, scene_id, user.id, session)
    await session.delete(scene)
    await session.commit()


@router.post("/{project_id}/scenes/{scene_id}/approval", response_model=ScenePublic)
async def update_scene_approval(
    project_id: UUID,
    scene_id: UUID,
    payload: SceneApprovalUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> Scene:
    scene = await _owned_scene(project_id, scene_id, user.id, session)
    if payload.is_approved:
        asset_ids = {
            asset_id
            for asset_id in (
                scene.generated_media_asset_id,
                *(shot.media_asset_id for shot in scene.shots),
            )
            if asset_id is not None
        }
        if not asset_ids:
            raise HTTPException(
                status_code=409,
                detail="A scene needs a real uploaded video asset before it can be approved.",
            )
        valid_asset_ids = await session.scalars(
            select(MediaAsset.id).where(
                MediaAsset.id.in_(asset_ids),
                MediaAsset.owner_id == user.id,
                or_(MediaAsset.project_id == project_id, MediaAsset.project_id.is_(None)),
                MediaAsset.media_type == "video",
            )
        )
        if set(valid_asset_ids.all()) != asset_ids:
            raise HTTPException(
                status_code=409,
                detail="A scene video asset is unavailable to this project.",
            )
    scene.is_approved = payload.is_approved
    await session.commit()
    return await _owned_scene(project_id, scene_id, user.id, session)


@router.post(
    "/{project_id}/scenes/{scene_id}/shots",
    response_model=SceneShotPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_scene_shot(
    project_id: UUID,
    scene_id: UUID,
    payload: SceneShotCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> SceneShot:
    await _owned_scene(project_id, scene_id, user.id, session)
    if payload.media_asset_id is not None:
        await _validate_reference_asset(
            payload.media_asset_id, user.id, session, {"video"}, project_id=project_id
        )
    await _validate_reference_asset(
        payload.first_frame_asset_id, user.id, session, project_id=project_id
    )
    await _validate_reference_asset(
        payload.last_frame_asset_id, user.id, session, project_id=project_id
    )
    shot = SceneShot(
        scene_id=scene_id,
        order_index=payload.order_index,
        description=payload.description.strip(),
        shot_prompt=payload.shot_prompt,
        duration_seconds=payload.duration_seconds,
        camera_movement=payload.camera_movement,
        media_asset_id=payload.media_asset_id,
        first_frame_asset_id=payload.first_frame_asset_id,
        last_frame_asset_id=payload.last_frame_asset_id,
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


@router.patch(
    "/{project_id}/scenes/{scene_id}/shots/{shot_id}",
    response_model=SceneShotPublic,
)
async def update_scene_shot(
    project_id: UUID,
    scene_id: UUID,
    shot_id: UUID,
    payload: SceneShotUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> SceneShot:
    await _owned_scene(project_id, scene_id, user.id, session)
    shot = await session.scalar(
        select(SceneShot).where(SceneShot.id == shot_id, SceneShot.scene_id == scene_id)
    )
    if shot is None:
        raise HTTPException(status_code=404, detail="Shot not found.")
    values = payload.model_dump(exclude_unset=True)
    if "media_asset_id" in values:
        await _validate_reference_asset(
            values["media_asset_id"], user.id, session, {"video"}, project_id=project_id
        )
    for field in ("first_frame_asset_id", "last_frame_asset_id"):
        if field in values:
            await _validate_reference_asset(values[field], user.id, session, project_id=project_id)
    for field, value in values.items():
        setattr(shot, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    await session.refresh(shot)
    return shot


@router.delete(
    "/{project_id}/scenes/{scene_id}/shots/{shot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_scene_shot(
    project_id: UUID,
    scene_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> None:
    await _owned_scene(project_id, scene_id, user.id, session)
    shot = await session.scalar(
        select(SceneShot).where(SceneShot.id == shot_id, SceneShot.scene_id == scene_id)
    )
    if shot is None:
        raise HTTPException(status_code=404, detail="Shot not found.")
    await session.delete(shot)
    await session.commit()


@router.get("/{project_id}/continuity", response_model=SceneContinuityReport)
async def review_scene_continuity(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> SceneContinuityReport:
    project = await _owned_project(project_id, user.id, session)
    scenes = await session.scalars(
        select(Scene)
        .options(selectinload(Scene.shots))
        .where(Scene.project_id == project_id)
        .order_by(Scene.order_index, Scene.id)
    )
    project_style = (project.visual_settings or {}).get("visual_style")
    checks: list[SceneContinuityCheck] = []
    for scene in scenes.unique().all():
        issues = []
        if not scene.scene_prompt and not scene.description:
            issues.append("Scene prompt or description is missing.")
        if not scene.shots:
            issues.append("No shots are planned.")
        if not scene.environment_id:
            issues.append("No project environment is assigned.")
        if project_style and scene.visual_style and project_style != scene.visual_style:
            issues.append(
                f"Scene style {scene.visual_style} differs from project style {project_style}."
            )
        if scene.character_ids:
            characters = await session.scalars(
                select(Character.id).where(
                    Character.project_id == project_id,
                    Character.id.in_([UUID(item) for item in scene.character_ids]),
                )
            )
            if len(characters.all()) != len(scene.character_ids):
                issues.append("One or more scene characters are no longer in the project.")
        checks.append(
            SceneContinuityCheck(scene_id=scene.id, scene_title=scene.title, issues=issues)
        )
    return SceneContinuityReport(
        project_id=project_id,
        scenes=checks,
        issue_count=sum(len(item.issues) for item in checks),
    )


@router.get("/{project_id}/scene-provider", response_model=ContentProviderStatus)
async def read_scene_provider_status(
    project_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> ContentProviderStatus:
    await _owned_project(project_id, user.id, session)
    provider: SceneGenerationProvider | None = request.app.state.scene_generation_provider
    return ContentProviderStatus(
        available=provider is not None,
        provider=provider.name if provider else None,
        preview_only=provider.preview_only if provider else False,
        self_hosted_worker_supported=True,
    )


@registry_router.get("/models", response_model=list[GenerationModelRegistryEntry])
async def list_generation_models(
    request: Request,
    user: CurrentUser,
) -> list[GenerationModelRegistryEntry]:
    return generation_model_registry(request.app.state.settings)


@registry_router.get("/worker/assets/{asset_id}")
async def download_worker_reference_asset(
    asset_id: UUID,
    request: Request,
    token: str = Query(min_length=1, max_length=4096),
) -> StreamingResponse:
    settings = request.app.state.settings
    if settings.jwt_secret_key is None:
        raise HTTPException(status_code=503, detail="Worker reference signing is not configured.")
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=["HS256"],
            audience="generation_worker",
            options={"require": ["sub", "project_id", "asset_id", "aud", "iat", "exp"]},
        )
        owner_id = UUID(claims["sub"])
        project_id = UUID(claims["project_id"])
        signed_asset_id = UUID(claims["asset_id"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Worker reference not found.") from None
    if signed_asset_id != asset_id:
        raise HTTPException(status_code=404, detail="Worker reference not found.")

    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured.")
    async with session_factory() as session:
        asset = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == asset_id,
                MediaAsset.owner_id == owner_id,
                MediaAsset.media_type == "image",
                or_(MediaAsset.project_id == project_id, MediaAsset.project_id.is_(None)),
            )
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="Worker reference not found.")
        storage_key = asset.storage_key
        content_type = asset.content_type
    return StreamingResponse(
        request.app.state.storage.open_stream(storage_key),
        media_type=content_type,
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/{project_id}/scenes/{scene_id}/generate",
    response_model=SceneGenerationJobPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_scene_generation(
    project_id: UUID,
    scene_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
    payload: SceneGenerationRequest = DEFAULT_SCENE_GENERATION_REQUEST,
) -> ProcessingJob:
    project = await _owned_project(project_id, user.id, session)
    provider: SceneGenerationProvider | None = request.app.state.scene_generation_provider
    if provider is None:
        raise APIError(
            503,
            "scene_generation_provider_unavailable",
            "No scene generation provider is configured. Connect a self-hosted GPU worker.",
        )
    scene = await _owned_scene(project_id, scene_id, user.id, session)
    if not (scene.scene_prompt or scene.description):
        raise APIError(
            422, "scene_prompt_required", "Add a scene prompt before requesting generation."
        )
    if scene.generation_status in {"queued", "processing"}:
        raise HTTPException(
            status_code=409, detail="This scene already has an active generation job."
        )
    if payload.model_id not in {MOCK_MODEL_ID, OPERATOR_MODEL_ID}:
        raise HTTPException(status_code=422, detail="Choose a model listed in the model registry.")
    if payload.model_id == MOCK_MODEL_ID and not provider.preview_only:
        raise HTTPException(
            status_code=422,
            detail="The mock model can only be used with the development preview worker.",
        )
    if payload.generation_mode == "image_to_video" and scene.first_frame_asset_id is None:
        raise APIError(
            422,
            "first_frame_required",
            "Image-to-video generation requires a first-frame reference image.",
        )
    model_entry = next(
        entry
        for entry in generation_model_registry(request.app.state.settings)
        if entry.id == payload.model_id
    )
    if payload.generation_mode not in model_entry.generation_modes:
        raise HTTPException(
            status_code=422,
            detail="The selected model registry entry does not support this generation mode.",
        )

    character_ids = [UUID(item) for item in scene.character_ids]
    characters = (
        await session.scalars(
            select(Character).where(
                Character.project_id == project_id, Character.id.in_(character_ids)
            )
        )
        if character_ids
        else []
    )
    environment = (
        await session.scalar(
            select(EnvironmentReference).where(
                EnvironmentReference.id == scene.environment_id,
                EnvironmentReference.project_id == project_id,
            )
        )
        if scene.environment_id
        else None
    )
    character_reference_assets: list[WorkerReferenceAsset] = []
    if character_ids:
        references = await session.execute(
            select(CharacterReference, MediaAsset)
            .join(MediaAsset, MediaAsset.id == CharacterReference.media_asset_id)
            .where(
                CharacterReference.character_id.in_(character_ids),
                MediaAsset.owner_id == user.id,
                MediaAsset.media_type == "image",
                or_(MediaAsset.project_id == project_id, MediaAsset.project_id.is_(None)),
            )
        )
        character_reference_assets = [
            WorkerReferenceAsset(
                asset_id=asset.id,
                role="character_reference",
                character_id=reference.character_id,
            )
            for reference, asset in references.all()
        ]
    provider_request = SceneProviderRequest(
        project_id=project_id,
        scene_id=scene.id,
        generation_mode=payload.generation_mode,
        title=scene.title,
        prompt=scene.scene_prompt or scene.description or "",
        visual_style=scene.visual_style,
        camera_movement=scene.camera_movement,
        lighting=scene.lighting,
        color_palette=scene.color_palette,
        character_ids=scene.character_ids,
        environment_id=scene.environment_id,
        first_frame_asset_id=scene.first_frame_asset_id,
        last_frame_asset_id=scene.last_frame_asset_id,
        model_id=model_entry.id,
        model_name=model_entry.model_name,
        model_version=model_entry.model_version,
        model_license=model_entry.model_license,
        commercial_use_permitted=model_entry.commercial_use_permitted,
        generation_settings=payload.settings,
        reference_assets=[
            WorkerReferenceAsset(
                asset_id=asset_id,
                role=role,
            )
            for role, asset_id in (
                ("first_frame", scene.first_frame_asset_id),
                ("last_frame", scene.last_frame_asset_id),
            )
            if asset_id is not None
        ]
        + character_reference_assets
        + (
            [
                WorkerReferenceAsset(
                    asset_id=environment.reference_asset_id,
                    role="environment_reference",
                )
            ]
            if environment is not None and environment.reference_asset_id is not None
            else []
        ),
        settings_snapshot={
            "project_visual_settings": project.visual_settings or {},
            "characters": [
                {
                    "id": str(character.id),
                    "name": character.name,
                    "identity_description": character.identity_description,
                    "outfit_settings": character.outfit_settings or {},
                    "visual_traits": character.visual_traits or {},
                }
                for character in characters
            ],
            "environment": (
                {
                    "id": str(environment.id),
                    "name": environment.name,
                    "description": environment.description,
                    "visual_traits": environment.visual_traits or {},
                }
                if environment
                else None
            ),
        },
    )
    job = ProcessingJob(
        owner_id=user.id,
        project_id=project_id,
        job_type="scene_generation",
        status="queued",
        input_data={
            "project_id": str(project_id),
            "scene_id": str(scene.id),
            "request": provider_request.model_dump(mode="json"),
        },
        model_name=model_entry.model_name,
        model_version=model_entry.model_version,
        model_license=model_entry.model_license,
        commercial_use_permitted=model_entry.commercial_use_permitted,
        generation_mode=payload.generation_mode,
        generation_settings=payload.settings,
    )
    session.add(job)
    await session.flush()
    scene.generation_status = "queued"
    scene.generation_job_id = job.id
    scene.generated_preview_label = None
    scene.generation_provider = None
    scene.generated_media_asset_id = None
    scene.is_approved = False
    await session.commit()
    await session.refresh(job)
    return job


@jobs_router.post("/{job_id}/cancel", response_model=SceneGenerationJobPublic)
async def cancel_scene_generation_job(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "scene_generation",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Scene generation job not found.")
    if job.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=409, detail="This scene generation job is already finished."
        )
    scene_id = (job.input_data or {}).get("scene_id")
    if job.status == "queued":
        job.status = "cancelled"
        if isinstance(scene_id, str):
            scene = await session.scalar(
                select(Scene).where(
                    Scene.id == UUID(scene_id),
                    Scene.generation_job_id == job.id,
                )
            )
            if scene is not None:
                scene.generation_status = "cancelled"
    else:
        job.cancellation_requested = True
    await session.commit()
    await session.refresh(job)
    return job


@jobs_router.post("/{job_id}/retry", response_model=SceneGenerationJobPublic)
async def retry_scene_generation_job(
    job_id: UUID,
    user: CurrentUser,
    request: Request,
    session: SessionDependency,
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "scene_generation",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Scene generation job not found.")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail="Only failed or cancelled scene generation jobs can be retried.",
        )
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=409, detail="This job has reached its retry limit.")
    if request.app.state.scene_generation_provider is None:
        raise APIError(
            503,
            "scene_generation_provider_unavailable",
            "No GPU worker or development preview provider is configured.",
        )
    scene_id = (job.input_data or {}).get("scene_id")
    if not isinstance(scene_id, str):
        raise HTTPException(status_code=409, detail="This job has no associated scene.")
    scene = await session.scalar(
        select(Scene).where(
            Scene.id == UUID(scene_id),
            Scene.project_id == job.project_id,
        )
    )
    if scene is None:
        raise HTTPException(status_code=404, detail="The scene for this job no longer exists.")
    if scene.generation_job_id != job.id:
        raise HTTPException(
            status_code=409,
            detail="The scene changed after this job was created. Queue a new generation instead.",
        )
    job.status = "queued"
    job.progress = 0
    job.retry_count += 1
    job.worker_job_id = None
    job.cancellation_requested = False
    job.error_message = None
    job.output_data = None
    scene.generation_status = "queued"
    scene.generation_job_id = job.id
    scene.generated_preview_label = None
    scene.generation_provider = None
    scene.generated_media_asset_id = None
    scene.is_approved = False
    await session.commit()
    await session.refresh(job)
    return job


@router.post(
    "/{project_id}/storyboard/assemble",
    response_model=StoryboardAssemblyResponse,
)
async def assemble_storyboard_timeline(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> StoryboardAssemblyResponse:
    """Create an editor timeline from approved scene video assets, never mock previews."""

    await _owned_project(project_id, user.id, session)
    scenes = await session.scalars(
        select(Scene)
        .options(selectinload(Scene.shots))
        .where(Scene.project_id == project_id, Scene.is_approved.is_(True))
        .order_by(Scene.order_index, Scene.id)
    )
    clips: list[dict[str, object]] = []
    duration_offset = 0.0
    asset_ids: set[UUID] = set()
    for scene in scenes.unique().all():
        scene_media: list[tuple[UUID, float]] = []
        if scene.generated_media_asset_id:
            scene_media.append((scene.generated_media_asset_id, scene.duration_seconds))
        else:
            for shot in sorted(scene.shots, key=lambda item: (item.order_index, str(item.id))):
                if shot.media_asset_id:
                    scene_media.append(
                        (shot.media_asset_id, shot.duration_seconds or scene.duration_seconds)
                    )
        for media_asset_id, duration in scene_media:
            clips.append(
                {
                    "id": uuid4(),
                    "media_asset_id": media_asset_id,
                    "start": duration_offset,
                    "duration": duration,
                    "source_start": 0,
                    "label": scene.title,
                }
            )
            asset_ids.add(media_asset_id)
            duration_offset += duration
    if not clips:
        raise HTTPException(
            status_code=409,
            detail="No approved scene has a real video asset. Preview-only results cannot be assembled.",
        )

    assets = await session.scalars(
        select(MediaAsset).where(
            MediaAsset.id.in_(asset_ids),
            MediaAsset.owner_id == user.id,
            or_(MediaAsset.project_id == project_id, MediaAsset.project_id.is_(None)),
            MediaAsset.media_type == "video",
        )
    )
    if len(list(assets.all())) != len(asset_ids):
        raise HTTPException(
            status_code=422, detail="A scene video asset is unavailable to this project."
        )
    video_track = TimelineTrackData(
        id=uuid4(),
        name="Approved scenes",
        type="video",
        clips=clips,
    )
    timeline_data = TimelineData(
        name="Storyboard assembly",
        tracks=[
            video_track,
            TimelineTrackData(id=uuid4(), name="Audio 1", type="audio"),
            TimelineTrackData(id=uuid4(), name="Subtitles", type="subtitle"),
        ],
    )
    timeline = await session.scalar(select(Timeline).where(Timeline.project_id == project_id))
    if timeline is None:
        timeline = Timeline(project_id=project_id)
        session.add(timeline)
    timeline.name = timeline_data.name
    timeline.frame_rate = timeline_data.frame_rate
    timeline.width = timeline_data.width
    timeline.height = timeline_data.height
    timeline.duration_seconds = duration_offset
    timeline.timeline_data = timeline_data.model_dump(mode="json")
    await session.commit()
    await session.refresh(timeline)
    return StoryboardAssemblyResponse(
        timeline_id=timeline.id,
        project_id=project_id,
        video_asset_count=len(asset_ids),
        message="Storyboard timeline saved. Queue the existing timeline export endpoint to render an MP4.",
    )


@jobs_router.get("/{job_id}", response_model=SceneGenerationJobPublic)
async def read_scene_generation_job(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "scene_generation",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Scene generation job not found.")
    return job
