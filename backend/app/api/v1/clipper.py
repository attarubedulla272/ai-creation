"""Authenticated Smart Clipper analysis, editing, caption, and export APIs."""

from __future__ import annotations

import re
import shutil
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.api.dependencies import CurrentUser, SessionDependency
from app.models.clip_candidate import ClipCandidate
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.schemas.clipper import (
    ClipAnalysisCreate,
    ClipCandidatePublic,
    ClipCandidateUpdate,
    ClipCaptionsUpdate,
    ClipExportCreate,
    ClipFramingUpdate,
    ClipJobPublic,
    ClipRankingUpdate,
)
from app.services.smart_clipper import DEFAULT_RANKING_WEIGHTS

router = APIRouter(prefix="/clipper", tags=["smart clipper"])
JOB_TYPES = ("smart_clip_analysis", "smart_clip_export")


@router.get("/capabilities")
async def read_capabilities(request: Request) -> dict[str, object]:
    """Report installed clipper components without claiming unsupported AI features."""

    voice_providers = request.app.state.voice_providers
    transcription = voice_providers.transcription
    ffmpeg_available = shutil.which("ffmpeg") is not None
    return {
        "scene_detection": {"available": True, "provider": "PySceneDetect ContentDetector"},
        "speaker_diarization": {
            "available": False,
            "provider": None,
            "note": "Existing transcript speaker labels are preserved when supplied.",
        },
        "silence_detection": {
            "available": ffmpeg_available,
            "provider": "FFmpeg silencedetect" if ffmpeg_available else None,
        },
        "transcription": {
            "available": transcription is not None,
            "provider": transcription.name if transcription else None,
            "timestamp_precision": "segment",
            "word_timestamps_available": False,
        },
        "rendering": {
            "available": ffmpeg_available,
            "provider": "FFmpeg" if ffmpeg_available else None,
        },
        "subtitle_export": {"available": ffmpeg_available, "format": "MP4 mov_text track"},
        "face_tracking": {"available": False, "provider": None, "fallback": "Manual crop position"},
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


async def _owned_candidate(
    candidate_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
) -> ClipCandidate:
    candidate = await session.scalar(
        select(ClipCandidate)
        .join(Project, Project.id == ClipCandidate.project_id)
        .where(ClipCandidate.id == candidate_id, Project.owner_id == owner_id)
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Clip candidate not found.")
    return candidate


async def _owned_job(
    job_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == owner_id,
            ProcessingJob.job_type.in_(JOB_TYPES),
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Smart Clipper job not found.")
    return job


def _candidate_score(factors: dict[str, object] | None, weights: dict[str, float]) -> float:
    values = factors or {}
    configured = {
        key: max(0, min(3, weights.get(key, value)))
        for key, value in DEFAULT_RANKING_WEIGHTS.items()
    }
    total = sum(configured.values()) or 1
    return round(
        100 * sum(float(values.get(key, 0)) * configured[key] for key in configured) / total,
        1,
    )


def _subtitle_time(seconds: float, separator: str) -> str:
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    whole, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{whole:02}{separator}{ms:03}"


def _subtitle_document(
    candidate: ClipCandidate,
    format_name: Literal["srt", "vtt"],
) -> str:
    entries: list[str] = []
    for index, caption in enumerate(candidate.caption_data or [], start=1):
        text = str(caption.get("text", "")).strip()
        try:
            start = float(caption["start_seconds"]) - candidate.start_seconds
            end = float(caption["end_seconds"]) - candidate.start_seconds
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not text
            or start < 0
            or end <= start
            or end > candidate.end_seconds - candidate.start_seconds
        ):
            continue
        separator = "." if format_name == "vtt" else ","
        entries.append(
            f"{index}\n{_subtitle_time(start, separator)} --> "
            f"{_subtitle_time(end, separator)}\n{text}"
        )
    document = "\n\n".join(entries)
    return f"WEBVTT\n\n{document}\n" if format_name == "vtt" else f"{document}\n"


@router.post("/analyses", response_model=ClipJobPublic, status_code=status.HTTP_202_ACCEPTED)
async def create_analysis(
    payload: ClipAnalysisCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    """Queue source metadata, scene-change, transcript, and highlight analysis."""

    await _owned_project(payload.project_id, user.id, session)
    asset = await session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == payload.source_media_asset_id,
            MediaAsset.owner_id == user.id,
            MediaAsset.project_id == payload.project_id,
            MediaAsset.media_type == "video",
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Project video not found.")
    job = ProcessingJob(
        owner_id=user.id,
        project_id=payload.project_id,
        job_type="smart_clip_analysis",
        status="queued",
        input_data=payload.model_dump(mode="json"),
        max_retries=2,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/analyses/{job_id}", response_model=ClipJobPublic)
async def read_analysis(
    job_id: UUID, user: CurrentUser, session: SessionDependency
) -> ProcessingJob:
    job = await _owned_job(job_id, user.id, session)
    if job.job_type != "smart_clip_analysis":
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    return job


@router.get("/projects/{project_id}/candidates", response_model=list[ClipCandidatePublic])
async def list_candidates(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[ClipCandidate]:
    await _owned_project(project_id, user.id, session)
    result = await session.scalars(
        select(ClipCandidate)
        .where(ClipCandidate.project_id == project_id)
        .order_by(ClipCandidate.score.desc(), ClipCandidate.created_at, ClipCandidate.id)
    )
    return list(result.all())


@router.get("/candidates/{candidate_id}", response_model=ClipCandidatePublic)
async def read_candidate(
    candidate_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ClipCandidate:
    return await _owned_candidate(candidate_id, user.id, session)


@router.patch("/projects/{project_id}/ranking", response_model=list[ClipCandidatePublic])
async def rank_candidates(
    project_id: UUID,
    payload: ClipRankingUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> list[ClipCandidate]:
    await _owned_project(project_id, user.id, session)
    result = await session.scalars(
        select(ClipCandidate).where(ClipCandidate.project_id == project_id)
    )
    candidates = list(result.all())
    for candidate in candidates:
        candidate.score = _candidate_score(candidate.scoring_factors, payload.preferences)
    await session.commit()
    return sorted(candidates, key=lambda candidate: candidate.score or 0, reverse=True)


@router.patch("/candidates/{candidate_id}", response_model=ClipCandidatePublic)
async def edit_candidate(
    candidate_id: UUID,
    payload: ClipCandidateUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> ClipCandidate:
    candidate = await _owned_candidate(candidate_id, user.id, session)
    start = payload.start_seconds if payload.start_seconds is not None else candidate.start_seconds
    end = payload.end_seconds if payload.end_seconds is not None else candidate.end_seconds
    if start >= end or end - start > 600:
        raise HTTPException(
            status_code=422,
            detail="Clip boundaries must form a positive clip of at most 10 minutes.",
        )
    asset = await session.get(MediaAsset, candidate.source_asset_id)
    if asset is None or asset.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Source video not found.")
    duration = asset.duration_seconds
    if duration is None:
        duration_value = (asset.metadata_json or {}).get("probe", {}).get("duration_seconds")
        duration = float(duration_value) if isinstance(duration_value, (int, float)) else None
    if duration is not None and end > duration:
        raise HTTPException(status_code=422, detail="Clip end exceeds source video duration.")
    trimmed_captions = []
    for caption in candidate.caption_data or []:
        caption_start = float(caption.get("start_seconds", start))
        caption_end = float(caption.get("end_seconds", end))
        if caption_end <= start or caption_start >= end:
            continue
        trimmed_captions.append(
            {
                **caption,
                "start_seconds": max(caption_start, start),
                "end_seconds": min(caption_end, end),
            }
        )
    candidate.caption_data = trimmed_captions
    candidate.start_seconds = start
    candidate.end_seconds = end
    await session.commit()
    await session.refresh(candidate)
    return candidate


@router.post("/candidates/{candidate_id}/regenerate-boundaries", response_model=ClipCandidatePublic)
async def regenerate_boundaries(
    candidate_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ClipCandidate:
    candidate = await _owned_candidate(candidate_id, user.id, session)
    captions = candidate.caption_data or []
    if not captions:
        raise HTTPException(
            status_code=409, detail="No transcript timing is available to align boundaries."
        )
    valid = [
        caption
        for caption in captions
        if isinstance(caption.get("start_seconds"), (int, float))
        and isinstance(caption.get("end_seconds"), (int, float))
    ]
    if not valid:
        raise HTTPException(status_code=409, detail="No usable caption timing is available.")
    candidate.start_seconds = max(0, float(valid[0]["start_seconds"]))
    candidate.end_seconds = float(valid[-1]["end_seconds"])
    await session.commit()
    await session.refresh(candidate)
    return candidate


@router.post("/candidates/{candidate_id}/approve", response_model=ClipCandidatePublic)
async def approve_candidate(
    candidate_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ClipCandidate:
    candidate = await _owned_candidate(candidate_id, user.id, session)
    candidate.status = "approved"
    await session.commit()
    await session.refresh(candidate)
    return candidate


@router.post("/candidates/{candidate_id}/reject", response_model=ClipCandidatePublic)
async def reject_candidate(
    candidate_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ClipCandidate:
    candidate = await _owned_candidate(candidate_id, user.id, session)
    candidate.status = "rejected"
    await session.commit()
    await session.refresh(candidate)
    return candidate


@router.get("/candidates/{candidate_id}/captions")
async def read_captions(
    candidate_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
    format_name: Literal["srt", "vtt"] = Query(alias="format", default="srt"),
) -> PlainTextResponse:
    candidate = await _owned_candidate(candidate_id, user.id, session)
    return PlainTextResponse(
        _subtitle_document(candidate, format_name),
        media_type="text/vtt" if format_name == "vtt" else "application/x-subrip",
    )


@router.patch("/candidates/{candidate_id}/captions", response_model=ClipCandidatePublic)
async def edit_captions(
    candidate_id: UUID,
    payload: ClipCaptionsUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> ClipCandidate:
    candidate = await _owned_candidate(candidate_id, user.id, session)
    for caption in payload.captions:
        if (
            caption.start_seconds < candidate.start_seconds
            or caption.end_seconds > candidate.end_seconds
            or caption.start_seconds >= caption.end_seconds
        ):
            raise HTTPException(
                status_code=422, detail="Caption timing must be inside clip boundaries."
            )
        available_words = {word.strip(".,!?;:").casefold() for word in caption.text.split()}
        if any(
            word.strip(".,!?;:").casefold() not in available_words
            for word in caption.highlighted_words
        ):
            raise HTTPException(
                status_code=422, detail="Highlighted words must appear in the caption text."
            )
    candidate.caption_data = [caption.model_dump() for caption in payload.captions]
    await session.commit()
    await session.refresh(candidate)
    return candidate


@router.patch("/candidates/{candidate_id}/framing", response_model=ClipCandidatePublic)
async def update_framing(
    candidate_id: UUID,
    payload: ClipFramingUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> ClipCandidate:
    candidate = await _owned_candidate(candidate_id, user.id, session)
    candidate.framing_data = payload.model_dump()
    await session.commit()
    await session.refresh(candidate)
    return candidate


@router.get("/projects/{project_id}/b-roll")
async def recommend_b_roll(
    project_id: UUID,
    candidate_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[dict[str, object]]:
    await _owned_project(project_id, user.id, session)
    candidate = await _owned_candidate(candidate_id, user.id, session)
    if candidate.project_id != project_id:
        raise HTTPException(status_code=404, detail="Clip candidate not found.")
    words = {
        word.casefold()
        for word in re.findall(
            r"[A-Za-z0-9]{4,}", f"{candidate.title or ''} {candidate.transcript_text or ''}"
        )
    }
    assets = await session.scalars(
        select(MediaAsset).where(
            MediaAsset.owner_id == user.id,
            MediaAsset.project_id == project_id,
            MediaAsset.media_type == "video",
            MediaAsset.id != candidate.source_asset_id,
        )
    )
    recommendations: list[dict[str, object]] = []
    for asset in assets:
        details = asset.metadata_json or {}
        text = f"{asset.name} {details.get('description', '')}".casefold()
        matched = sorted(word for word in words if word in text)
        if matched:
            recommendations.append(
                {
                    "id": str(asset.id),
                    "name": asset.name,
                    "duration_seconds": asset.duration_seconds,
                    "matched_terms": matched,
                    "reason": "Project video shares words with this clip's transcript.",
                }
            )
    return sorted(recommendations, key=lambda item: len(item["matched_terms"]), reverse=True)


@router.post("/exports", response_model=ClipJobPublic, status_code=status.HTTP_202_ACCEPTED)
async def create_export(
    payload: ClipExportCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    candidates = await session.scalars(
        select(ClipCandidate)
        .join(Project, Project.id == ClipCandidate.project_id)
        .where(
            ClipCandidate.id.in_(payload.candidate_ids),
            Project.owner_id == user.id,
        )
    )
    selected = list(candidates.all())
    if len(selected) != len(set(payload.candidate_ids)):
        raise HTTPException(status_code=404, detail="One or more selected clips were not found.")
    if any(candidate.status != "approved" for candidate in selected):
        raise HTTPException(status_code=409, detail="Only approved clips can be exported.")
    if payload.captions and any(not candidate.caption_data for candidate in selected):
        raise HTTPException(
            status_code=409,
            detail="Captions were requested, but at least one approved clip has no transcript timing.",
        )
    if payload.animated_highlighting:
        raise HTTPException(
            status_code=422,
            detail="Animated word highlighting requires verified word-level timestamps, which are unavailable.",
        )
    source_ids = {candidate.source_asset_id for candidate in selected}
    sources = await session.scalars(
        select(MediaAsset).where(
            MediaAsset.id.in_(source_ids),
            MediaAsset.owner_id == user.id,
            MediaAsset.project_id == selected[0].project_id,
            MediaAsset.media_type == "video",
        )
    )
    if len(list(sources.all())) != len(source_ids):
        raise HTTPException(status_code=404, detail="One or more clip sources were not found.")
    project_ids = {candidate.project_id for candidate in selected}
    if len(project_ids) != 1:
        raise HTTPException(
            status_code=422, detail="Batch exports must use clips from one project."
        )
    project_id = next(iter(project_ids))
    job = ProcessingJob(
        owner_id=user.id,
        project_id=project_id,
        job_type="smart_clip_export",
        status="queued",
        input_data={
            "candidate_ids": [str(value) for value in payload.candidate_ids],
            "options": {
                "aspect_ratio": payload.aspect_ratio,
                "resolution": payload.resolution,
                "captions": payload.captions,
                "caption_position": payload.caption_position,
                "caption_theme": payload.caption_theme,
                "caption_font_size": payload.caption_font_size,
                "caption_color": payload.caption_color,
                "caption_background_color": payload.caption_background_color,
                "caption_outline_color": payload.caption_outline_color,
                "watermark": payload.watermark,
            },
        },
        max_retries=2,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=ClipJobPublic)
async def read_job(job_id: UUID, user: CurrentUser, session: SessionDependency) -> ProcessingJob:
    return await _owned_job(job_id, user.id, session)


@router.post("/jobs/{job_id}/retry", response_model=ClipJobPublic)
async def retry_job(job_id: UUID, user: CurrentUser, session: SessionDependency) -> ProcessingJob:
    job = await _owned_job(job_id, user.id, session)
    if job.job_type not in JOB_TYPES or job.status != "failed":
        raise HTTPException(
            status_code=409, detail="Only failed Smart Clipper jobs can be retried."
        )
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=409, detail="The job retry limit has been reached.")
    if job.job_type == "smart_clip_analysis":
        input_data = job.input_data or {}
        try:
            project_id = UUID(str(input_data["project_id"]))
            source_id = UUID(str(input_data["source_media_asset_id"]))
        except (KeyError, ValueError):
            raise HTTPException(
                status_code=409, detail="The analysis source is unavailable."
            ) from None
        source = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == source_id,
                MediaAsset.project_id == project_id,
                MediaAsset.owner_id == user.id,
                MediaAsset.media_type == "video",
            )
        )
        if source is None or job.project_id != project_id:
            raise HTTPException(status_code=409, detail="The analysis source is unavailable.")
    job.retry_count += 1
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    job.output_data = None
    job.cancellation_requested = False
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=ClipJobPublic)
async def cancel_job(job_id: UUID, user: CurrentUser, session: SessionDependency) -> ProcessingJob:
    job = await _owned_job(job_id, user.id, session)
    if job.status == "queued":
        job.status = "cancelled"
    elif job.status == "processing":
        job.cancellation_requested = True
    else:
        raise HTTPException(
            status_code=409, detail="Only queued or processing jobs can be cancelled."
        )
    await session.commit()
    await session.refresh(job)
    return job
