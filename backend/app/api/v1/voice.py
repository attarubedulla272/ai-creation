"""Authenticated voice, transcript, and dubbing-plan endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.errors import APIError
from app.models.dubbing_project import DubbingProject
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.project import Project
from app.models.transcript import Transcript
from app.models.transcript_revision import TranscriptRevision
from app.models.voice_profile import VoiceConsent, VoiceProfile
from app.schemas.voice import (
    DubbingExportRequest,
    DubbingProjectCreate,
    DubbingProjectPublic,
    DubbingProjectUpdate,
    SpeechPreviewRequest,
    TranscriptionCreate,
    TranscriptPublic,
    TranscriptRevisionPublic,
    TranscriptSegmentUpdate,
    TranslationQueueRequest,
    VoiceConsentCreate,
    VoiceConsentPublic,
    VoiceJobPublic,
    VoiceProfileCreate,
    VoiceProfilePublic,
)

router = APIRouter(prefix="/voice", tags=["voice studio"])
INDIC_TRANSLATION_LANGUAGE_CODES = {"hi", "te", "ta", "kn", "ml"}


async def _owned_profile(
    profile_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
) -> VoiceProfile:
    profile = await session.scalar(
        select(VoiceProfile)
        .options(selectinload(VoiceProfile.consent))
        .join(MediaAsset, MediaAsset.id == VoiceProfile.reference_asset_id)
        .where(VoiceProfile.id == profile_id, VoiceProfile.owner_id == owner_id)
        .where(MediaAsset.owner_id == owner_id, MediaAsset.media_type == "audio")
    )
    if profile is None or profile.consent.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Authorized voice profile not found.")
    return profile


async def _owned_transcript(
    transcript_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
) -> Transcript:
    transcript = await session.scalar(
        select(Transcript)
        .join(Project, Project.id == Transcript.project_id)
        .options(selectinload(Transcript.segments))
        .where(Transcript.id == transcript_id, Project.owner_id == owner_id)
    )
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    return transcript


async def _owned_dubbing_project(
    dubbing_project_id: UUID,
    owner_id: UUID,
    session: SessionDependency,
) -> DubbingProject:
    dubbing_project = await session.scalar(
        select(DubbingProject).where(
            DubbingProject.id == dubbing_project_id,
            DubbingProject.owner_id == owner_id,
        )
    )
    if dubbing_project is None:
        raise HTTPException(status_code=404, detail="Dubbing project not found.")
    return dubbing_project


def _subtitle_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def _subtitle_document(
    segments: list[tuple[float, float, str]],
    format_name: Literal["srt", "vtt"],
) -> str:
    entries = []
    for index, (start, end, text) in enumerate(segments, start=1):
        if not text.strip():
            continue
        start_time = _subtitle_time(start)
        end_time = _subtitle_time(max(start, end))
        if format_name == "vtt":
            start_time = start_time.replace(",", ".")
            end_time = end_time.replace(",", ".")
        entries.append(f"{index}\n{start_time} --> {end_time}\n{text.strip()}")
    document = "\n\n".join(entries)
    return f"WEBVTT\n\n{document}\n" if format_name == "vtt" else f"{document}\n"


@router.get("/providers")
async def read_provider_capabilities(request: Request) -> dict[str, dict[str, object]]:
    """Report concrete local provider availability without fabricating capability."""

    return request.app.state.voice_providers.capability_status()


@router.post(
    "/consents",
    response_model=VoiceConsentPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice_consent(
    payload: VoiceConsentCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> VoiceConsent:
    """Record the signed-in user's explicit authorization attestation."""

    consent = VoiceConsent(
        owner_id=user.id,
        consent_method="user_attestation",
        consent_text_version=payload.consent_text_version,
        authorization_basis=payload.authorization_basis,
        evidence_reference=payload.evidence_reference,
    )
    session.add(consent)
    await session.commit()
    await session.refresh(consent)
    return consent


@router.get("/consents", response_model=list[VoiceConsentPublic])
async def list_voice_consents(
    user: CurrentUser,
    session: SessionDependency,
) -> list[VoiceConsent]:
    result = await session.scalars(
        select(VoiceConsent)
        .where(VoiceConsent.owner_id == user.id)
        .order_by(VoiceConsent.granted_at.desc())
    )
    return list(result.all())


@router.post(
    "/profiles",
    response_model=VoiceProfilePublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice_profile(
    payload: VoiceProfileCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> VoiceProfile:
    """Save an authorized reference recording, not a cloned or generated voice."""

    consent = await session.scalar(
        select(VoiceConsent).where(
            VoiceConsent.id == payload.consent_id,
            VoiceConsent.owner_id == user.id,
            VoiceConsent.revoked_at.is_(None),
        )
    )
    if consent is None:
        raise APIError(
            422, "active_consent_required", "An active authorization attestation is required."
        )
    if payload.reference_asset_id is None:
        raise APIError(
            422, "voice_reference_required", "Upload and select an audio reference recording."
        )
    reference = await session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == payload.reference_asset_id,
            MediaAsset.owner_id == user.id,
            MediaAsset.media_type == "audio",
        )
    )
    if reference is None:
        raise HTTPException(status_code=404, detail="Owned audio reference not found.")
    profile = VoiceProfile(
        owner_id=user.id,
        consent_id=consent.id,
        reference_asset_id=reference.id,
        name=payload.name.strip(),
        language=payload.language,
        status="reference_only",
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


@router.get("/profiles", response_model=list[VoiceProfilePublic])
async def list_voice_profiles(
    user: CurrentUser,
    session: SessionDependency,
) -> list[VoiceProfile]:
    result = await session.scalars(
        select(VoiceProfile)
        .join(VoiceConsent, VoiceConsent.id == VoiceProfile.consent_id)
        .join(MediaAsset, MediaAsset.id == VoiceProfile.reference_asset_id)
        .where(VoiceProfile.owner_id == user.id, VoiceConsent.revoked_at.is_(None))
        .where(MediaAsset.owner_id == user.id, MediaAsset.media_type == "audio")
        .order_by(VoiceProfile.created_at.desc())
    )
    return list(result.all())


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice_profile(
    profile_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> None:
    profile = await session.scalar(
        select(VoiceProfile).where(VoiceProfile.id == profile_id, VoiceProfile.owner_id == user.id)
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Authorized voice profile not found.")
    await session.delete(profile)
    await session.commit()


@router.post("/consents/{consent_id}/revoke", response_model=VoiceConsentPublic)
async def revoke_voice_consent(
    consent_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> VoiceConsent:
    consent = await session.scalar(
        select(VoiceConsent).where(VoiceConsent.id == consent_id, VoiceConsent.owner_id == user.id)
    )
    if consent is None:
        raise HTTPException(status_code=404, detail="Voice consent record not found.")
    consent.revoked_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(consent)
    return consent


@router.post("/transcriptions", response_model=VoiceJobPublic, status_code=status.HTTP_202_ACCEPTED)
async def create_transcription(
    payload: TranscriptionCreate,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    """Queue transcription of an owned local audio source."""

    providers = request.app.state.voice_providers
    if providers.transcription is None:
        raise APIError(
            503,
            "transcription_provider_unavailable",
            "Local transcription is unavailable. On Apple Silicon macOS, install the voice-mlx extra.",
        )
    project = await session.scalar(
        select(Project).where(Project.id == payload.project_id, Project.owner_id == user.id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    asset = await session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == payload.media_asset_id, MediaAsset.owner_id == user.id
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found.")
    if asset.media_type == "audio":
        source_key = asset.storage_key
    elif asset.media_type == "video":
        derivatives = (asset.metadata_json or {}).get("derivatives", {})
        source_key = derivatives.get("extracted_audio") if isinstance(derivatives, dict) else None
        if not isinstance(source_key, str):
            raise APIError(
                409,
                "audio_derivative_not_ready",
                "Wait for media processing to extract the video's audio, or upload an audio file.",
            )
    else:
        raise APIError(
            415,
            "audio_required",
            "Transcription requires an audio file or video with extracted audio.",
        )

    job = ProcessingJob(
        owner_id=user.id,
        project_id=project.id,
        job_type="voice_transcription",
        status="queued",
        input_data={
            "source_storage_key": source_key,
            "media_asset_id": str(asset.id),
            "project_id": str(project.id),
            "language": payload.language,
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=VoiceJobPublic)
async def read_voice_job(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.owner_id == user.id)
    )
    if job is None or job.job_type not in {
        "voice_transcription",
        "voice_dubbing_export",
        "voice_translation",
    }:
        raise HTTPException(status_code=404, detail="Voice processing job not found.")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=VoiceJobPublic)
async def cancel_voice_job(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type.in_(
                ("voice_transcription", "voice_dubbing_export", "voice_translation")
            ),
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Voice processing job not found.")
    if job.status == "queued":
        job.status = "cancelled"
        job.progress = 0
        job.error_message = "Voice processing was cancelled."
        if job.job_type == "voice_translation":
            data = job.input_data or {}
            project = await session.scalar(
                select(DubbingProject).where(
                    DubbingProject.id == data.get("dubbing_project_id"),
                    DubbingProject.owner_id == user.id,
                )
            )
            if project is not None:
                segment_ids = set(data.get("segment_ids", []))
                project.segments_data = [
                    {
                        **item,
                        **(
                            {
                                "translation_status": "cancelled",
                                "translation_error": "Translation was cancelled.",
                            }
                            if str(item.get("id")) in segment_ids
                            and item.get("translation_status") == "queued"
                            else {}
                        ),
                    }
                    for item in project.segments_data
                ]
    elif job.status == "processing":
        job.cancellation_requested = True
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/jobs/{job_id}/retry", response_model=VoiceJobPublic)
async def retry_voice_job(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "voice_translation",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Translation job not found.")
    if job.status != "failed":
        raise APIError(
            409, "translation_retry_unavailable", "Only failed translation jobs can retry."
        )
    if job.retry_count >= job.max_retries:
        raise APIError(409, "translation_retry_limit", "The translation retry limit was reached.")
    data = dict(job.input_data or {})
    try:
        dubbing_project_id = UUID(str(data["dubbing_project_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise APIError(
            409,
            "translation_job_invalid",
            "The failed translation job has an invalid dubbing project reference.",
        ) from error
    dubbing_project = await session.scalar(
        select(DubbingProject).where(
            DubbingProject.id == dubbing_project_id,
            DubbingProject.owner_id == user.id,
        )
    )
    if dubbing_project is None:
        raise HTTPException(status_code=404, detail="Dubbing project not found.")
    failed_ids = {
        str(item.get("id"))
        for item in dubbing_project.segments_data
        if item.get("translation_status") == "failed"
    }
    data["segment_ids"] = [
        segment_id for segment_id in data.get("segment_ids", []) if segment_id in failed_ids
    ]
    if not data["segment_ids"]:
        raise APIError(409, "translation_retry_empty", "No failed segments remain to retry.")
    active_jobs = await session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "voice_translation",
            ProcessingJob.status.in_(("queued", "processing")),
        )
    )
    if any(
        (active.input_data or {}).get("dubbing_project_id") == str(dubbing_project.id)
        for active in active_jobs
    ):
        raise APIError(409, "translation_already_running", "A translation is already running.")
    job.retry_count += 1
    job.status = "queued"
    job.progress = 0
    job.output_data = None
    job.error_message = None
    job.input_data = data
    retry_ids = set(data["segment_ids"])
    dubbing_project.segments_data = [
        {
            **item,
            **(
                {"translation_status": "queued", "translation_error": None}
                if str(item.get("id")) in retry_ids
                else {}
            ),
        }
        for item in dubbing_project.segments_data
    ]
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/transcripts/{transcript_id}", response_model=TranscriptPublic)
async def read_transcript(
    transcript_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> Transcript:
    return await _owned_transcript(transcript_id, user.id, session)


@router.get("/transcripts", response_model=list[TranscriptPublic])
async def list_transcripts(
    user: CurrentUser,
    session: SessionDependency,
) -> list[Transcript]:
    result = await session.scalars(
        select(Transcript)
        .join(Project, Project.id == Transcript.project_id)
        .options(selectinload(Transcript.segments))
        .where(Project.owner_id == user.id)
        .order_by(Transcript.created_at.desc())
        .limit(100)
    )
    return list(result.unique().all())


@router.patch(
    "/transcripts/{transcript_id}/segments/{segment_id}",
    response_model=TranscriptPublic,
)
async def update_transcript_segment(
    transcript_id: UUID,
    segment_id: UUID,
    payload: TranscriptSegmentUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> Transcript:
    transcript = await _owned_transcript(transcript_id, user.id, session)
    segment = next((item for item in transcript.segments if item.id == segment_id), None)
    if segment is None:
        raise HTTPException(status_code=404, detail="Transcript segment not found.")
    fields = payload.model_dump(exclude_unset=True)
    if any(getattr(segment, field) != value for field, value in fields.items()):
        revision_number = (
            await session.scalar(
                select(func.max(TranscriptRevision.revision_number)).where(
                    TranscriptRevision.transcript_id == transcript.id
                )
            )
            or 0
        ) + 1
        snapshot = [
            {
                "id": str(item.id),
                "order_index": item.order_index,
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "text": item.text,
                "speaker_label": item.speaker_label,
                "translated_text": item.translated_text,
            }
            for item in transcript.segments
        ]
        session.add(
            TranscriptRevision(
                transcript_id=transcript.id,
                revision_number=revision_number,
                snapshot=snapshot,
                created_by=user.id,
            )
        )
    for field, value in fields.items():
        setattr(segment, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    return await _owned_transcript(transcript_id, user.id, session)


@router.get(
    "/transcripts/{transcript_id}/revisions",
    response_model=list[TranscriptRevisionPublic],
)
async def list_transcript_revisions(
    transcript_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> list[TranscriptRevision]:
    transcript = await _owned_transcript(transcript_id, user.id, session)
    result = await session.scalars(
        select(TranscriptRevision)
        .where(TranscriptRevision.transcript_id == transcript.id)
        .order_by(TranscriptRevision.revision_number.desc())
    )
    return list(result.all())


async def _create_translation_job(
    dubbing_project: DubbingProject,
    segments: list[dict[str, object]],
    user: CurrentUser,
    session: SessionDependency,
    source_language: str | None,
    target_language: str,
) -> ProcessingJob:
    selected_ids = [
        str(segment["id"]) for segment in segments if segment.get("translation_status") == "queued"
    ]
    glossary = [
        {
            "source": str(item["source"]),
            "translation": str(item["translation"]),
        }
        for item in dubbing_project.glossary
        if item.get("source") and item.get("translation")
    ]
    job = ProcessingJob(
        owner_id=user.id,
        project_id=dubbing_project.project_id,
        job_type="voice_translation",
        status="queued",
        input_data={
            "dubbing_project_id": str(dubbing_project.id),
            "segment_ids": selected_ids,
            "source_language": source_language,
            "target_language": target_language,
            "glossary": glossary,
        },
    )
    dubbing_project.segments_data = segments
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.post(
    "/dubbing-projects/{dubbing_project_id}/translate",
    response_model=VoiceJobPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def translate_dubbing_project(
    dubbing_project_id: UUID,
    payload: TranslationQueueRequest,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    dubbing_project = await _owned_dubbing_project(dubbing_project_id, user.id, session)
    provider = request.app.state.voice_providers.translation
    if provider is None:
        raise APIError(
            503,
            "translation_provider_unavailable",
            "The optional local translation worker is not configured.",
        )
    transcript = await _owned_transcript(dubbing_project.transcript_id, user.id, session)
    source_language = transcript.language
    target_language = dubbing_project.target_language
    if not (
        (source_language == "en" and target_language in INDIC_TRANSLATION_LANGUAGE_CODES)
        or (source_language in INDIC_TRANSLATION_LANGUAGE_CODES and target_language == "en")
    ):
        raise APIError(
            422,
            "translation_pair_unavailable",
            "The configured IndicTrans2 candidate accepts English ↔ Hindi, Telugu, Tamil, Kannada, or Malayalam; output quality is not yet verified.",
        )
    segments = [dict(item) for item in dubbing_project.segments_data]
    active_jobs = await session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "voice_translation",
            ProcessingJob.status.in_(("queued", "processing")),
        )
    )
    if any(
        (job.input_data or {}).get("dubbing_project_id") == str(dubbing_project.id)
        for job in active_jobs
    ):
        raise APIError(409, "translation_already_running", "A translation is already running.")
    eligible = []
    for segment in segments:
        if payload.regenerate_existing or not str(segment.get("translated_text", "")).strip():
            segment["translation_status"] = "queued"
            segment["translation_error"] = None
            eligible.append(segment)
    if not eligible:
        raise APIError(
            409,
            "translation_already_complete",
            "All segments already have translations. Set regenerate_existing to replace them.",
        )
    return await _create_translation_job(
        dubbing_project,
        segments,
        user,
        session,
        source_language,
        target_language,
    )


@router.post(
    "/dubbing-projects/{dubbing_project_id}/segments/{segment_id}/translate",
    response_model=VoiceJobPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def translate_dubbing_segment(
    dubbing_project_id: UUID,
    segment_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    dubbing_project = await _owned_dubbing_project(dubbing_project_id, user.id, session)
    if request.app.state.voice_providers.translation is None:
        raise APIError(
            503,
            "translation_provider_unavailable",
            "The optional local translation worker is not configured.",
        )
    transcript = await _owned_transcript(dubbing_project.transcript_id, user.id, session)
    source_language = transcript.language
    target_language = dubbing_project.target_language
    if not (
        (source_language == "en" and target_language in INDIC_TRANSLATION_LANGUAGE_CODES)
        or (source_language in INDIC_TRANSLATION_LANGUAGE_CODES and target_language == "en")
    ):
        raise APIError(
            422,
            "translation_pair_unavailable",
            "The configured IndicTrans2 candidate accepts English ↔ Hindi, Telugu, Tamil, Kannada, or Malayalam; output quality is not yet verified.",
        )
    segments = [dict(item) for item in dubbing_project.segments_data]
    selected = next((item for item in segments if str(item.get("id")) == str(segment_id)), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Dubbing segment not found.")
    active_jobs = await session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "voice_translation",
            ProcessingJob.status.in_(("queued", "processing")),
        )
    )
    if any(
        (job.input_data or {}).get("dubbing_project_id") == str(dubbing_project.id)
        for job in active_jobs
    ):
        raise APIError(409, "translation_already_running", "A translation is already running.")
    selected["translation_status"] = "queued"
    selected["translation_error"] = None
    return await _create_translation_job(
        dubbing_project,
        segments,
        user,
        session,
        source_language,
        target_language,
    )


@router.get("/transcripts/{transcript_id}/subtitles/{format_name}")
async def export_transcript_subtitles(
    transcript_id: UUID,
    format_name: Literal["srt", "vtt"],
    user: CurrentUser,
    session: SessionDependency,
) -> PlainTextResponse:
    transcript = await _owned_transcript(transcript_id, user.id, session)
    segments = [(item.start_seconds, item.end_seconds, item.text) for item in transcript.segments]
    return PlainTextResponse(
        _subtitle_document(segments, format_name),
        media_type="text/vtt" if format_name == "vtt" else "application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="transcript.{format_name}"'},
    )


@router.post(
    "/dubbing-projects",
    response_model=DubbingProjectPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_dubbing_project(
    payload: DubbingProjectCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> DubbingProject:
    transcript = await _owned_transcript(payload.transcript_id, user.id, session)
    dubbing_project = DubbingProject(
        owner_id=user.id,
        project_id=transcript.project_id,
        transcript_id=transcript.id,
        target_language=payload.target_language,
        segments_data=[
            {
                "id": str(uuid4()),
                "source_segment_id": str(segment.id),
                "order_index": segment.order_index,
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "original_start_seconds": segment.start_seconds,
                "original_end_seconds": segment.end_seconds,
                "source_text": segment.text,
                "translated_text": segment.translated_text or "",
                "speaker_label": segment.speaker_label,
                "voice_profile_id": None,
                "speech_rate": 1.0,
                "audio_asset_id": None,
                "audio_source": None,
                "audio_duration_seconds": None,
                "translation_approved": False,
                "translation_status": "manual" if segment.translated_text else "not_translated",
                "translation_provider": None,
                "translation_model": None,
                "translation_model_version": None,
                "translation_error": None,
                "segment_approved": False,
                "timing_conflict": False,
                "processing_status": "not_generated",
                "generated_audio_path": None,
            }
            for segment in transcript.segments
        ],
    )
    session.add(dubbing_project)
    await session.commit()
    await session.refresh(dubbing_project)
    return dubbing_project


@router.get("/dubbing-projects/{dubbing_project_id}", response_model=DubbingProjectPublic)
async def read_dubbing_project(
    dubbing_project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> DubbingProject:
    return await _owned_dubbing_project(dubbing_project_id, user.id, session)


@router.get("/dubbing-projects", response_model=list[DubbingProjectPublic])
async def list_dubbing_projects(
    user: CurrentUser,
    session: SessionDependency,
) -> list[DubbingProject]:
    result = await session.scalars(
        select(DubbingProject)
        .where(DubbingProject.owner_id == user.id)
        .order_by(DubbingProject.created_at.desc())
        .limit(100)
    )
    return list(result.all())


@router.patch("/dubbing-projects/{dubbing_project_id}", response_model=DubbingProjectPublic)
async def update_dubbing_project(
    dubbing_project_id: UUID,
    payload: DubbingProjectUpdate,
    user: CurrentUser,
    session: SessionDependency,
) -> DubbingProject:
    dubbing_project = await _owned_dubbing_project(dubbing_project_id, user.id, session)
    existing = [dict(item) for item in dubbing_project.segments_data]
    segments_by_id = {str(item.get("id")): item for item in existing}
    updates = {str(item.id): item for item in payload.segments}
    if len(updates) != len(payload.segments) or not updates.keys() <= segments_by_id.keys():
        raise APIError(
            422, "invalid_dubbing_segments", "Segment updates must reference this dubbing project."
        )

    for segment_id, update_payload in updates.items():
        segment = segments_by_id[segment_id]
        fields = update_payload.model_dump(exclude_unset=True, exclude={"id"})
        translated_text = fields.get("translated_text")
        translation_changed = isinstance(
            translated_text, str
        ) and translated_text.strip() != segment.get("translated_text", "")
        audio_changed = "audio_asset_id" in fields and (
            str(fields["audio_asset_id"]) if fields["audio_asset_id"] is not None else None
        ) != segment.get("audio_asset_id")
        timing_changed = any(
            key in fields and fields[key] != segment.get(key)
            for key in ("start_seconds", "end_seconds", "speech_rate")
        )
        if "voice_profile_id" in fields and fields["voice_profile_id"] is not None:
            await _owned_profile(fields["voice_profile_id"], user.id, session)
        if "audio_asset_id" in fields and fields["audio_asset_id"] is not None:
            audio_asset = await session.scalar(
                select(MediaAsset).where(
                    MediaAsset.id == fields["audio_asset_id"],
                    MediaAsset.owner_id == user.id,
                    MediaAsset.media_type == "audio",
                )
            )
            if audio_asset is None:
                raise HTTPException(status_code=404, detail="Owned audio segment not found.")
            segment["audio_source"] = "user_supplied"
            segment["processing_status"] = "user_audio_attached"
            segment["generated_audio_path"] = None
            segment["audio_duration_seconds"] = audio_asset.duration_seconds
        elif "audio_asset_id" in fields:
            segment["audio_source"] = None
            segment["processing_status"] = "not_generated"
            segment["audio_duration_seconds"] = None
            segment["generated_audio_path"] = None

        start = fields.get("start_seconds", segment["start_seconds"])
        end = fields.get("end_seconds", segment["end_seconds"])
        if end <= start:
            raise APIError(
                422, "invalid_segment_timing", "Each segment end must be after its start."
            )
        json_fields = {
            key: str(value) if isinstance(value, UUID) else value for key, value in fields.items()
        }
        segment.update(json_fields)
        if "translated_text" in fields and isinstance(fields["translated_text"], str):
            segment["translated_text"] = fields["translated_text"].strip()
        if translation_changed:
            segment["translation_approved"] = False
            segment["translation_status"] = (
                "manual"
                if isinstance(translated_text, str) and translated_text.strip()
                else "not_translated"
            )
            segment["translation_provider"] = None
            segment["translation_model"] = None
            segment["translation_model_version"] = None
            segment["translation_error"] = None
        if timing_changed or audio_changed:
            segment["segment_approved"] = False
        duration = segment.get("audio_duration_seconds")
        rate = float(segment.get("speech_rate", 1.0))
        segment["timing_conflict"] = (
            isinstance(duration, (int, float)) and duration / rate > end - start + 0.025
        )
        translated_text = segment.get("translated_text")
        if segment.get("translation_approved") and (
            not isinstance(translated_text, str) or not translated_text.strip()
        ):
            raise APIError(
                422,
                "translation_not_ready",
                "A segment needs translated text before it can be approved.",
            )
        if segment.get("segment_approved") and not segment.get("audio_asset_id"):
            raise APIError(
                422,
                "audio_not_ready",
                "Attach a user-supplied audio segment before approving it.",
            )
    dubbing_project.segments_data = [dict(item) for item in existing]
    if payload.glossary is not None:
        source_terms = [item.source.casefold().strip() for item in payload.glossary]
        if len(source_terms) != len(set(source_terms)):
            raise APIError(
                422,
                "duplicate_glossary_term",
                "Each glossary source term must be unique.",
            )
        dubbing_project.glossary = [
            {
                "source": item.source.strip(),
                "translation": item.translation.strip(),
                **({"notes": item.notes.strip()} if item.notes and item.notes.strip() else {}),
            }
            for item in payload.glossary
        ]
    await session.commit()
    await session.refresh(dubbing_project)
    return dubbing_project


@router.post(
    "/dubbing-projects/{dubbing_project_id}/segments/{segment_id}/regenerate",
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
)
async def regenerate_dubbing_segment(
    dubbing_project_id: UUID,
    segment_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> None:
    dubbing_project = await _owned_dubbing_project(dubbing_project_id, user.id, session)
    if not any(str(item.get("id")) == str(segment_id) for item in dubbing_project.segments_data):
        raise HTTPException(status_code=404, detail="Dubbing segment not found.")
    if request.app.state.voice_providers.synthesis is None:
        raise APIError(
            503,
            "synthesis_provider_unavailable",
            "No text-to-speech provider is installed; no audio was generated.",
        )
    raise APIError(
        501, "synthesis_workflow_unavailable", "No speech synthesis workflow is configured."
    )


@router.post(
    "/dubbing-projects/{dubbing_project_id}/export",
    response_model=VoiceJobPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_dubbing_audio(
    dubbing_project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
    payload: DubbingExportRequest | None = None,
) -> ProcessingJob:
    """Queue non-truncating audio assembly from explicitly supplied segments."""

    dubbing_project = await _owned_dubbing_project(dubbing_project_id, user.id, session)
    segments = dubbing_project.segments_data
    if not segments or any(not item.get("audio_asset_id") for item in segments):
        raise APIError(
            409,
            "dubbing_audio_incomplete",
            "Attach an owned audio file to every segment before exporting. This does not synthesize speech.",
        )
    asset_ids = {UUID(item["audio_asset_id"]) for item in segments}
    assets = await session.scalars(
        select(MediaAsset).where(MediaAsset.owner_id == user.id, MediaAsset.id.in_(asset_ids))
    )
    assets_by_id = {asset.id: asset for asset in assets}
    if len(assets_by_id) != len(asset_ids) or any(
        assets_by_id[asset_id].media_type != "audio" for asset_id in asset_ids
    ):
        raise HTTPException(
            status_code=404, detail="One or more user-supplied audio segments were not found."
        )
    if any(assets_by_id[asset_id].duration_seconds is None for asset_id in asset_ids):
        raise APIError(
            409,
            "audio_duration_unavailable",
            "Wait for media processing to determine every attached audio segment's duration.",
        )

    source_video = None
    if payload and payload.source_video_asset_id:
        source_video = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == payload.source_video_asset_id,
                MediaAsset.owner_id == user.id,
                MediaAsset.project_id == dubbing_project.project_id,
                MediaAsset.media_type == "video",
            )
        )
        if source_video is None:
            raise HTTPException(status_code=404, detail="Owned project video not found.")

    job = ProcessingJob(
        owner_id=user.id,
        project_id=dubbing_project.project_id,
        job_type="voice_dubbing_export",
        status="queued",
        input_data={
            "dubbing_project_id": str(dubbing_project.id),
            "project_id": str(dubbing_project.project_id),
            "segments": [
                {
                    "storage_key": assets_by_id[UUID(item["audio_asset_id"])].storage_key,
                    "start_seconds": item["start_seconds"],
                    "end_seconds": item["end_seconds"],
                    "speech_rate": item["speech_rate"],
                    "audio_duration_seconds": assets_by_id[
                        UUID(item["audio_asset_id"])
                    ].duration_seconds,
                }
                for item in segments
            ],
            "source_video_storage_key": source_video.storage_key if source_video else None,
            "source_video_asset_id": str(source_video.id) if source_video else None,
            "timing_conflicts": [
                str(item["id"]) for item in segments if item.get("timing_conflict")
            ],
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.get("/dubbing-projects/{dubbing_project_id}/subtitles/{format_name}")
async def export_dubbing_subtitles(
    dubbing_project_id: UUID,
    format_name: Literal["srt", "vtt"],
    user: CurrentUser,
    session: SessionDependency,
) -> PlainTextResponse:
    dubbing_project = await _owned_dubbing_project(dubbing_project_id, user.id, session)
    if any(not item.get("translated_text", "").strip() for item in dubbing_project.segments_data):
        raise APIError(
            409,
            "translation_incomplete",
            "Add translated text to every segment before subtitle export.",
        )
    segments = []
    for item in dubbing_project.segments_data:
        start = float(item["start_seconds"])
        duration = item.get("audio_duration_seconds")
        rate = max(0.5, min(2.0, float(item.get("speech_rate", 1.0))))
        end = (
            start + float(duration) / rate
            if isinstance(duration, (int, float)) and duration > 0
            else float(item["end_seconds"])
        )
        segments.append((start, end, item["translated_text"]))
    return PlainTextResponse(
        _subtitle_document(segments, format_name),
        media_type="text/vtt" if format_name == "vtt" else "application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="dubbing.{format_name}"'},
    )


@router.post("/speech-preview", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
async def preview_speech(
    payload: SpeechPreviewRequest,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> None:
    await _owned_profile(payload.voice_profile_id, user.id, session)
    if request.app.state.voice_providers.synthesis is None:
        raise APIError(
            503,
            "synthesis_provider_unavailable",
            "No text-to-speech provider is installed; no preview audio was generated.",
        )
    raise APIError(
        501,
        "synthesis_workflow_unavailable",
        "No tested local TTS provider is configured; no speech was generated.",
    )
