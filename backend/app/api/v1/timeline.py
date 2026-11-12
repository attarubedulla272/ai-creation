"""Owner-scoped timeline persistence and asynchronous export endpoints."""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.errors import APIError
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.models.timeline import Timeline
from app.schemas.timeline import (
    TimelineData,
    TimelineExportJobPublic,
    TimelineExportRequest,
    TimelineExportResponse,
    TimelineResponse,
    TimelineSubtitleCue,
    TimelineTextFitRequest,
    TimelineTextFitResponse,
    TimelineTextValidationIssue,
    TimelineTextValidationRequest,
    TimelineTextValidationResponse,
)
from app.services.storage import StorageService
from app.services.subtitle_io import SubtitleFormat, export_subtitles, parse_subtitles
from app.services.timeline_export import TimelineTextRenderError, _render_subtitle_image

router = APIRouter(prefix="/projects/{project_id}/timeline", tags=["timeline"])
export_router = APIRouter(prefix="/timeline/exports", tags=["timeline"])


def _default_timeline() -> TimelineData:
    return TimelineData(
        tracks=[
            {"id": uuid4(), "name": "Video 1", "type": "video"},
            {"id": uuid4(), "name": "Overlay 1", "type": "overlay"},
            {"id": uuid4(), "name": "Audio 1", "type": "audio"},
            {"id": uuid4(), "name": "Subtitles", "type": "subtitle"},
        ]
    )


async def _owned_project(project_id: UUID, owner_id: UUID, session: SessionDependency) -> Project:
    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


async def _get_or_create_timeline(project: Project, session: SessionDependency) -> Timeline:
    timeline = await session.scalar(select(Timeline).where(Timeline.project_id == project.id))
    if timeline is None:
        data = _default_timeline()
        timeline = Timeline(
            project_id=project.id,
            name=data.name,
            duration_seconds=0,
            frame_rate=data.frame_rate,
            width=data.width,
            height=data.height,
            timeline_data=data.model_dump(mode="json"),
        )
        session.add(timeline)
        await session.flush()
    elif not timeline.timeline_data:
        data = _default_timeline()
        timeline.timeline_data = data.model_dump(mode="json")
    return timeline


def _output_dimensions(
    timeline: TimelineData, preset: str | None
) -> tuple[int, int]:
    if preset is None:
        return timeline.width, timeline.height
    long_edge = {"720p": 1280, "1080p": 1920, "4k": 3840}[preset]
    aspect_ratio = timeline.width / timeline.height
    if timeline.width >= timeline.height:
        return long_edge, max(2, round(long_edge / aspect_ratio / 2) * 2)
    return max(2, round(long_edge * aspect_ratio / 2) * 2), long_edge


def _validate_text_document(
    timeline: TimelineData, width: int, height: int
) -> list[TimelineTextValidationIssue]:
    issues: list[TimelineTextValidationIssue] = []
    for track in timeline.tracks:
        if track.muted or track.type not in {"overlay", "subtitle"}:
            continue
        for clip in track.clips:
            if clip.text is None:
                continue
            if not clip.text.strip():
                issues.append(
                    TimelineTextValidationIssue(
                        clip_id=clip.id,
                        track_name=track.name,
                        severity="error",
                        code="empty_text",
                        message="This text clip is empty and cannot be exported.",
                        recommendation="Enter text or delete the empty clip.",
                    )
                )
                continue
            if track.type == "subtitle" and clip.duration < 0.5:
                issues.append(
                    TimelineTextValidationIssue(
                        clip_id=clip.id,
                        track_name=track.name,
                        severity="warning",
                        code="subtitle_duration",
                        message=f"This subtitle lasts only {clip.duration:.2f} seconds.",
                        recommendation="Consider extending its duration after reviewing the subtitle timing.",
                    )
                )

            unsupported: list[str] = []
            if any(effect.enabled for effect in clip.effects):
                unsupported.append("enabled clip effects")
            if clip.brightness != 0 or clip.contrast != 1 or clip.saturation != 1:
                unsupported.append("clip brightness, contrast, or saturation")
            if unsupported:
                issue_text = ", ".join(unsupported)
                issues.append(
                    TimelineTextValidationIssue(
                        clip_id=clip.id,
                        track_name=track.name,
                        severity="error",
                        code="unsupported_style",
                        message=f"The export renderer does not apply {issue_text} to text clips.",
                        recommendation="Reset those clip-level settings before exporting text.",
                    )
                )

            try:
                layout = _render_subtitle_image(
                    clip.text,
                    None,
                    width,
                    height,
                    clip.text_style.model_dump(mode="json"),
                )
            except TimelineTextRenderError as error:
                code = "font" if "No installed Unicode font" in str(error) else "layout"
                issues.append(
                    TimelineTextValidationIssue(
                        clip_id=clip.id,
                        track_name=track.name,
                        severity="error",
                        code=code,
                        message=str(error),
                        recommendation=(
                            "Choose a font available to the export worker or remove unsupported "
                            "characters."
                            if code == "font"
                            else "Increase the text box width, reduce the font size, or split "
                            "the text into multiple clips."
                        ),
                        alternatives=(
                            [
                                value.strip()
                                for value in str(error).split("Available font families on this worker:")[-1]
                                .rstrip(".")
                                .split(",")
                                if value.strip()
                            ]
                            if code == "font" and "Available font families" in str(error)
                            else []
                        ),
                    )
                )
                continue

            if layout.used_fallback_font:
                issues.append(
                    TimelineTextValidationIssue(
                        clip_id=clip.id,
                        track_name=track.name,
                        severity="warning",
                        code="font",
                        message=(
                            f"The requested {clip.text_style.font_family} font face is unavailable; "
                            "the export worker will use a compatible installed fallback."
                        ),
                        recommendation="Select an available family to make the exported appearance more predictable.",
                        alternatives=list(layout.available_font_families),
                    )
                )
            if track.type == "subtitle" and layout.line_count > 2:
                issues.append(
                    TimelineTextValidationIssue(
                        clip_id=clip.id,
                        track_name=track.name,
                        severity="warning",
                        code="layout",
                        message=f"This subtitle wraps to {layout.line_count} lines.",
                        recommendation="Review readability or split the cue at a word boundary.",
                    )
                )
    return issues


@router.get("", response_model=TimelineResponse)
async def read_timeline(
    project_id: UUID, user: CurrentUser, session: SessionDependency
) -> Timeline:
    """Load or initialize a project's structured editor document."""

    project = await _owned_project(project_id, user.id, session)
    timeline = await _get_or_create_timeline(project, session)
    await session.commit()
    await session.refresh(timeline)
    return timeline


@router.put("", response_model=TimelineResponse)
async def save_timeline(
    project_id: UUID,
    payload: TimelineData,
    user: CurrentUser,
    session: SessionDependency,
) -> Timeline:
    """Validate owned media references and persist the timeline document."""

    project = await _owned_project(project_id, user.id, session)
    ids = {
        clip.media_asset_id
        for track in payload.tracks
        for clip in track.clips
        if clip.media_asset_id
    }
    assets_by_id: dict[UUID, MediaAsset] = {}
    if ids:
        assets = await session.scalars(
            select(MediaAsset).where(MediaAsset.id.in_(ids), MediaAsset.owner_id == user.id)
        )
        assets_by_id = {asset.id: asset for asset in assets.all()}
        if ids - assets_by_id.keys():
            raise HTTPException(status_code=422, detail="Timeline contains unavailable media.")

    for track in payload.tracks:
        for clip in track.clips:
            asset = assets_by_id.get(clip.media_asset_id) if clip.media_asset_id else None
            if track.type == "video" and (asset is None or asset.media_type != "video"):
                raise HTTPException(status_code=422, detail="Video tracks require video assets.")
            if (
                track.type == "audio"
                and asset is not None
                and asset.media_type
                not in {
                    "audio",
                    "video",
                }
            ):
                raise HTTPException(
                    status_code=422, detail="Audio tracks require audio or video assets."
                )
            if (
                track.type == "overlay"
                and asset is not None
                and asset.media_type not in {"image", "video"}
            ):
                raise HTTPException(
                    status_code=422, detail="Overlay tracks require image or video assets."
                )
            if track.type == "subtitle" and not clip.text:
                raise HTTPException(status_code=422, detail="Subtitle clips require text.")
            if (
                asset
                and asset.duration_seconds
                and clip.source_start + clip.duration > asset.duration_seconds + 0.05
            ):
                raise HTTPException(
                    status_code=422, detail="A clip exceeds its source media duration."
                )

    timeline = await session.scalar(select(Timeline).where(Timeline.project_id == project.id))
    legacy_cross_dissolves: set[tuple[UUID, UUID, float, float, float]] = set()
    if timeline is not None and timeline.timeline_data:
        previous_data = TimelineData.model_validate(timeline.timeline_data)
        legacy_cross_dissolves = {
            (
                track.id,
                clip.id,
                clip.start,
                clip.duration,
                clip.transition_in_duration,
            )
            for track in previous_data.tracks
            for clip in track.clips
            if clip.transition_in == "cross_dissolve" and clip.transition_in_version == 0
        }
    for track in payload.tracks:
        for clip in track.clips:
            if (
                clip.transition_in == "cross_dissolve"
                and clip.transition_in_version == 0
                and (
                    track.id,
                    clip.id,
                    clip.start,
                    clip.duration,
                    clip.transition_in_duration,
                )
                not in legacy_cross_dissolves
            ):
                raise HTTPException(
                    status_code=422,
                    detail="A new cross dissolve must be configured with a timeline overlap.",
                )
    if timeline is None:
        timeline = Timeline(project_id=project.id)
        session.add(timeline)
    timeline.name = payload.name
    timeline.frame_rate = payload.frame_rate
    timeline.width = payload.width
    timeline.height = payload.height
    timeline.duration_seconds = max(
        (clip.start + clip.duration for track in payload.tracks for clip in track.clips),
        default=0,
    )
    timeline.timeline_data = payload.model_dump(mode="json")
    await session.commit()
    await session.refresh(timeline)
    return timeline


@router.post("/text-validation", response_model=TimelineTextValidationResponse)
async def validate_timeline_text(
    project_id: UUID,
    payload: TimelineTextValidationRequest,
    user: CurrentUser,
    session: SessionDependency,
) -> TimelineTextValidationResponse:
    """Validate visible text with the same Pillow layout and fonts used by export."""

    await _owned_project(project_id, user.id, session)
    width, height = _output_dimensions(payload.timeline, payload.preset)
    return TimelineTextValidationResponse(
        issues=_validate_text_document(payload.timeline, width, height)
    )


@router.post("/text-fit", response_model=TimelineTextFitResponse)
async def propose_timeline_text_fit(
    project_id: UUID,
    payload: TimelineTextFitRequest,
    user: CurrentUser,
    session: SessionDependency,
) -> TimelineTextFitResponse:
    """Return a temporary, validated fit proposal without persisting timeline changes."""

    await _owned_project(project_id, user.id, session)
    timeline = payload.timeline.model_copy(deep=True)
    match = next(
        (
            (track, clip)
            for track in timeline.tracks
            for clip in track.clips
            if clip.id == payload.clip_id
        ),
        None,
    )
    if match is None or match[0].type not in {"overlay", "subtitle"} or match[1].text is None:
        raise HTTPException(status_code=404, detail="Choose a text or subtitle clip to fit.")
    track, clip = match
    if track.locked:
        raise HTTPException(status_code=409, detail="Unlock the selected text track before fitting.")
    if not clip.text.strip():
        raise HTTPException(status_code=422, detail="Enter text before applying a fit operation.")

    width, height = _output_dimensions(timeline, payload.preset)
    warnings: list[str] = []
    if payload.operation == "fit_width":
        clip.text_style.width = 1.0
        proposed_clips = [clip]
    elif payload.operation == "shrink":
        if payload.minimum_font_size > clip.text_style.font_size:
            raise HTTPException(
                status_code=422,
                detail="Minimum font size cannot exceed the current font size.",
            )
        proposed_clips = []
        for font_size in range(
            clip.text_style.font_size - 1, payload.minimum_font_size - 1, -1
        ):
            style = clip.text_style.model_copy(update={"font_size": font_size})
            try:
                _render_subtitle_image(
                    clip.text, None, width, height, style.model_dump(mode="json")
                )
            except TimelineTextRenderError:
                continue
            clip.text_style = style
            proposed_clips = [clip]
            break
        if not proposed_clips:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Text still exceeds the export renderer limit at the minimum font size "
                    f"of {payload.minimum_font_size}px. Increase the box width or split the text."
                ),
            )
    else:
        source_clip = clip.model_copy(deep=True)
        source_text = clip.text
        style = clip.text_style.model_dump(mode="json")

        def split_renderable(value: str, *, force_split: bool = False) -> list[str]:
            try:
                _render_subtitle_image(value, None, width, height, style)
            except TimelineTextRenderError as error:
                if "No installed Unicode font" in str(error):
                    raise HTTPException(status_code=422, detail=str(error)) from error
                can_render = False
            else:
                can_render = True
            if can_render and not force_split:
                return [value]

            tokens = list(re.finditer(r"\S+\s*", value))
            if len(tokens) < 2:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "A word-boundary split cannot make this text renderable. "
                        "Increase the text box width or reduce the font size."
                    ),
                )
            split_token = min(
                range(1, len(tokens)),
                key=lambda index: abs(
                    len(value[: tokens[index - 1].end()])
                    - len(value[tokens[index - 1].end() :])
                ),
            )
            split_position = tokens[split_token - 1].end()
            return split_renderable(value[:split_position]) + split_renderable(
                value[split_position:]
            )

        parts = split_renderable(source_text, force_split=True)
        if sum(len(item.clips) for item in timeline.tracks) + len(parts) - 1 > 500:
            raise HTTPException(
                status_code=422,
                detail="Splitting would exceed the 500-clip timeline limit.",
            )
        proposed_clips = []
        elapsed = 0.0
        for index, part in enumerate(parts):
            duration = (
                source_clip.duration - elapsed
                if index == len(parts) - 1
                else source_clip.duration * len(part) / len(source_text)
            )
            start = source_clip.start + elapsed
            label = part.strip()[:80]
            if index == 0:
                clip.start = start
                clip.duration = duration
                clip.text = part
                clip.label = label
                proposed_clip = clip
            else:
                proposed_clip = source_clip.model_copy(
                    deep=True,
                    update={
                        "id": uuid4(),
                        "start": start,
                        "duration": duration,
                        "text": part,
                        "label": label,
                    },
                )
                track.clips.append(proposed_clip)
            proposed_clips.append(proposed_clip)
            elapsed += duration
        if track.type == "subtitle" and any(item.duration < 0.5 for item in proposed_clips):
            warnings.append(
                "At least one proposed subtitle cue is shorter than 0.50 seconds; review its timing."
            )
    issues = _validate_text_document(timeline, width, height)
    proposed_clip_ids = {proposed_clip.id for proposed_clip in proposed_clips}
    blocking_issues = [
        issue
        for issue in issues
        if issue.severity == "error"
        and issue.clip_id in proposed_clip_ids
        and not (payload.operation == "fit_width" and issue.code == "layout")
    ]
    if blocking_issues:
        raise HTTPException(
            status_code=422,
            detail=blocking_issues[0].message,
        )
    if payload.operation == "fit_width" and any(
        issue.severity == "error"
        and issue.code == "layout"
        and issue.clip_id in proposed_clip_ids
        for issue in issues
    ):
        warnings.append(
            "The wider box still exceeds the export renderer line limit. Review a shrink or split proposal."
        )
    return TimelineTextFitResponse(timeline=timeline, warnings=warnings)


@router.post("/subtitles/import", response_model=list[TimelineSubtitleCue])
async def import_subtitle_file(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
    file: Annotated[UploadFile, File(...)],
) -> list[TimelineSubtitleCue]:
    """Parse a bounded SRT or WebVTT upload for an owned project."""

    await _owned_project(project_id, user.id, session)
    extension = (file.filename or "").rsplit(".", maxsplit=1)[-1].lower()
    if extension not in {"srt", "vtt"}:
        raise HTTPException(status_code=415, detail="Choose an SRT or VTT subtitle file.")
    subtitle_format: SubtitleFormat = "srt" if extension == "srt" else "vtt"
    content = await file.read(2_000_001)
    if len(content) > 2_000_000:
        raise HTTPException(status_code=413, detail="Subtitle files must be 2 MB or smaller.")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=422, detail="Subtitle files must use UTF-8 encoding."
        ) from error
    try:
        return parse_subtitles(decoded, subtitle_format)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/subtitles/export")
async def export_subtitle_file(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
    subtitle_format: Annotated[SubtitleFormat, Query(alias="format")] = "srt",
) -> Response:
    """Export saved subtitle-track clips as SRT or WebVTT."""

    project = await _owned_project(project_id, user.id, session)
    timeline = await session.scalar(select(Timeline).where(Timeline.project_id == project.id))
    if timeline is None or not timeline.timeline_data:
        raise HTTPException(status_code=409, detail="Save a timeline before exporting subtitles.")
    data = TimelineData.model_validate(timeline.timeline_data)
    cues = [
        TimelineSubtitleCue(start=clip.start, duration=clip.duration, text=clip.text or "")
        for track in data.tracks
        if track.type == "subtitle" and not track.muted
        for clip in track.clips
        if clip.text
    ]
    if not cues:
        raise HTTPException(status_code=409, detail="The timeline has no subtitle cues to export.")
    content = export_subtitles(cues, subtitle_format)
    return Response(
        content=content,
        media_type="text/vtt" if subtitle_format == "vtt" else "application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="subtitles.{subtitle_format}"'},
    )


@router.post("/export", response_model=TimelineExportResponse, status_code=status.HTTP_202_ACCEPTED)
async def queue_timeline_export(
    project_id: UUID,
    payload: TimelineExportRequest,
    user: CurrentUser,
    session: SessionDependency,
) -> TimelineExportResponse:
    """Queue an MP4 render of selected video clips and an optional audio bed."""

    project = await _owned_project(project_id, user.id, session)
    timeline = await session.scalar(select(Timeline).where(Timeline.project_id == project.id))
    if timeline is None or not timeline.timeline_data:
        raise HTTPException(status_code=409, detail="Save a timeline before exporting.")
    data = TimelineData.model_validate(timeline.timeline_data)
    video_clips = [
        clip
        for track in data.tracks
        if track.type == "video" and not track.muted
        for clip in track.clips
    ]
    if payload.selected_clip_ids:
        wanted = set(payload.selected_clip_ids)
        video_clips = [clip for clip in video_clips if clip.id in wanted]
        if {clip.id for clip in video_clips} != wanted:
            raise HTTPException(
                status_code=422, detail="Selected clips must be video clips in this timeline."
            )
    video_clips.sort(key=lambda clip: (clip.start, str(clip.id)))
    if not video_clips:
        raise HTTPException(status_code=422, detail="Add at least one video clip before exporting.")

    if payload.selected_clip_ids:
        selected_ids = set(payload.selected_clip_ids)
        if {clip.id for clip in video_clips} != selected_ids:
            raise HTTPException(
                status_code=422, detail="Selected clips must be video clips in this timeline."
            )
        render_tracks = [
            track.model_copy(
                update={
                    "clips": [
                        clip
                        for clip in track.clips
                        if track.type == "video" and clip.id in selected_ids
                    ]
                }
            )
            for track in data.tracks
        ]
    else:
        render_tracks = data.tracks
    render_tracks = [track for track in render_tracks if not track.muted]
    has_solo_audio_track = any(track.type == "audio" and track.solo for track in render_tracks)
    render_clips = [
        (track_order, track, clip)
        for track_order, track in enumerate(render_tracks)
        for clip in track.clips
    ]
    requested_asset_ids = {
        clip.media_asset_id for _, _, clip in render_clips if clip.media_asset_id is not None
    }
    assets = await session.scalars(
        select(MediaAsset).where(
            MediaAsset.id.in_(requested_asset_ids),
            MediaAsset.owner_id == user.id,
        )
    )
    assets_by_id = {asset.id: asset for asset in assets.all()}
    if requested_asset_ids - assets_by_id.keys():
        raise HTTPException(status_code=422, detail="Timeline contains unavailable media.")

    output_width, output_height = _output_dimensions(data, payload.preset)
    if payload.preset is not None:
        long_edge = {"720p": 1280, "1080p": 1920, "4k": 3840}[payload.preset]
        for clip in video_clips:
            if clip.media_asset_id is None:
                raise HTTPException(status_code=422, detail="Export clips require video assets.")
            asset = assets_by_id[clip.media_asset_id]
            probe = (asset.metadata_json or {}).get("probe")
            if not isinstance(probe, dict):
                raise HTTPException(
                    status_code=409,
                    detail="Wait for source video processing before choosing an export preset.",
                )
            width = probe.get("width")
            height = probe.get("height")
            if not isinstance(width, int) or not isinstance(height, int):
                raise HTTPException(
                    status_code=409,
                    detail="Source video dimensions are not available for preset validation.",
                )
            if max(width, height) < long_edge:
                raise HTTPException(
                    status_code=422,
                    detail=f"{payload.preset} export requires source video at least "
                    f"{long_edge} pixels on its long edge.",
                )

    text_issues = _validate_text_document(
        data.model_copy(update={"tracks": render_tracks}), output_width, output_height
    )
    blocking_text_issues = [issue for issue in text_issues if issue.severity == "error"]
    if blocking_text_issues:
        raise APIError(
            422,
            "text_export_blocked",
            "Fix blocking text-rendering issues before exporting.",
            details=[issue.model_dump(mode="json") for issue in blocking_text_issues],
        )

    export_tracks: list[dict[str, object]] = []
    for track_order, track in enumerate(render_tracks):
        track_clips: list[dict[str, object]] = []
        for clip in track.clips:
            asset = assets_by_id.get(clip.media_asset_id) if clip.media_asset_id else None
            if clip.media_asset_id and asset is None:
                raise HTTPException(status_code=422, detail="Timeline contains unavailable media.")
            if track.type == "video" and (asset is None or asset.media_type != "video"):
                raise HTTPException(status_code=422, detail="Video tracks require video assets.")
            if track.type == "overlay" and asset and asset.media_type not in {"image", "video"}:
                raise HTTPException(
                    status_code=422, detail="Overlay tracks require image or video."
                )
            if track.type == "audio" and asset and asset.media_type not in {"audio", "video"}:
                raise HTTPException(status_code=422, detail="Audio tracks require audio or video.")
            if track.type == "subtitle" or (track.type == "overlay" and clip.text is not None):
                if not clip.text:
                    raise HTTPException(status_code=422, detail="Text clips require content.")
                track_clips.append(
                    {
                        **clip.model_dump(mode="json"),
                        "storage_key": None,
                        "media_type": None,
                        "has_audio": False,
                    }
                )
                continue
            if asset is None:
                continue
            probe = (asset.metadata_json or {}).get("probe")
            audio_streams = probe.get("audio_streams", []) if isinstance(probe, dict) else []
            track_clips.append(
                {
                    **clip.model_dump(mode="json"),
                    "storage_key": asset.storage_key,
                    "media_type": asset.media_type,
                    "has_audio": bool(audio_streams),
                }
            )
        export_tracks.append(
            {
                "type": track.type,
                "muted": track.muted,
                "audio_muted": has_solo_audio_track and not (track.type == "audio" and track.solo),
                "volume": track.volume,
                "order": track_order,
                "clips": track_clips,
            }
        )
    timeline_duration = max(
        (clip.start + clip.duration for _, _, clip in render_clips),
        default=0,
    )
    if timeline_duration <= 0 or timeline_duration > 86_400:
        raise HTTPException(status_code=422, detail="Timeline duration is invalid.")

    job = ProcessingJob(
        owner_id=user.id,
        project_id=project.id,
        job_type="timeline_export",
        status="queued",
        input_data={
            "tracks": export_tracks,
            "duration": timeline_duration,
            "frame_rate": data.frame_rate,
            "width": output_width,
            "height": output_height,
            "preset": payload.preset or "timeline",
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return TimelineExportResponse(job_id=job.id, status="queued", progress=0)


@export_router.get("/{job_id}", response_model=TimelineExportJobPublic)
async def read_timeline_export(
    job_id: UUID, user: CurrentUser, session: SessionDependency
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "timeline_export",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found.")
    return job


@export_router.post("/{job_id}/retry", response_model=TimelineExportJobPublic)
async def retry_timeline_export(
    job_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    """Requeue a failed or cancelled timeline export while retries remain."""

    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "timeline_export",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found.")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(
            status_code=409, detail="Only failed or cancelled exports can be retried."
        )
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=409, detail="The export has reached its retry limit.")
    tracks = (job.input_data or {}).get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise HTTPException(status_code=409, detail="The export source media is unavailable.")
    storage: StorageService = request.app.state.storage
    source_keys = {
        clip.get("storage_key")
        for track in tracks
        if isinstance(track, dict) and isinstance(track.get("clips"), list)
        for clip in track["clips"]
        if isinstance(clip, dict) and isinstance(clip.get("storage_key"), str)
    }
    if not source_keys:
        raise HTTPException(status_code=409, detail="The export source media is unavailable.")
    for source_key in source_keys:
        if not await storage.exists(source_key):
            raise HTTPException(status_code=409, detail="The export source media is unavailable.")
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    job.output_data = None
    job.cancellation_requested = False
    job.retry_count += 1
    await session.commit()
    await session.refresh(job)
    return job


@export_router.post("/{job_id}/cancel", response_model=TimelineExportJobPublic)
async def cancel_timeline_export(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    """Cancel a queued export or ask the worker to stop an active render."""

    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "timeline_export",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found.")
    if job.status == "queued":
        job.status = "cancelled"
        job.cancellation_requested = True
        job.error_message = "Timeline export was cancelled."
    elif job.status == "processing":
        job.cancellation_requested = True
    else:
        raise HTTPException(
            status_code=409, detail="Only queued or processing exports can be cancelled."
        )
    await session.commit()
    await session.refresh(job)
    return job


@export_router.get("/{job_id}/download")
async def download_timeline_export(
    job_id: UUID, request: Request, user: CurrentUser, session: SessionDependency
) -> StreamingResponse:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "timeline_export",
        )
    )
    if job is None or job.status != "completed" or not job.output_data:
        raise HTTPException(status_code=404, detail="Completed export not found.")
    storage_key = job.output_data.get("storage_key")
    if not isinstance(storage_key, str):
        raise HTTPException(status_code=404, detail="Completed export file is unavailable.")
    storage: StorageService = request.app.state.storage
    if not await storage.exists(storage_key):
        raise HTTPException(status_code=404, detail="Completed export file is unavailable.")
    return StreamingResponse(
        storage.open_stream(storage_key),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="timeline-{job.id}.mp4"'},
    )
