"""Official YouTube OAuth, upload, and analytics endpoints."""

from __future__ import annotations

import hmac
import logging
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, or_, select, update

from app.api.dependencies import CurrentUser, SessionDependency
from app.models.clip_candidate import ClipCandidate
from app.models.media_asset import MediaAsset
from app.models.processing_job import ProcessingJob
from app.models.publication import Publication
from app.models.youtube import YouTubeConnection, YouTubeOAuthState
from app.schemas.publishing import (
    YouTubeAnalyticsPublic,
    YouTubeConnectionPublic,
    YouTubeDisconnectResponse,
    YouTubeOAuthStartResponse,
    YouTubeUploadJobPublic,
    YouTubeUploadRequest,
)
from app.services.youtube_api import (
    YOUTUBE_ANALYTICS_SCOPE,
    YOUTUBE_ANALYTICS_SCOPES,
    YOUTUBE_BASE_SCOPES,
    YouTubeApiClient,
    YouTubeApiError,
    YouTubeOAuthNotConfigured,
)
from app.services.youtube_publishing import _publication_metadata

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/publishing/youtube", tags=["YouTube publishing"])
STATE_LIFETIME = timedelta(minutes=10)


def _client(request: Request) -> YouTubeApiClient:
    client = getattr(request.app.state, "youtube_client", None)
    if not isinstance(client, YouTubeApiClient):
        raise HTTPException(
            status_code=503,
            detail=(
                "YouTube integration is not configured. Set the Google OAuth client, exact "
                "callback URI, frontend return URI, and token encryption key."
            ),
        )
    return client


def _frontend_redirect(request: Request, result: str) -> RedirectResponse:
    settings = request.app.state.settings
    parts = urlsplit(str(settings.youtube_oauth_frontend_return_url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["youtube_connection"] = result
    location = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)


async def _start_authorization(
    *,
    request: Request,
    user_id: UUID,
    session: SessionDependency,
    purpose: str,
    expected_channel_id: str | None = None,
) -> YouTubeOAuthStartResponse:
    client = _client(request)
    await session.execute(
        delete(YouTubeOAuthState).where(
            or_(
                YouTubeOAuthState.consumed_at.is_not(None),
                YouTubeOAuthState.expires_at < datetime.now(UTC),
            )
        )
    )
    state = client.new_state()
    verifier = client.new_code_verifier()
    scopes = YOUTUBE_ANALYTICS_SCOPES if purpose == "analytics" else YOUTUBE_BASE_SCOPES
    session.add(
        YouTubeOAuthState(
            owner_id=user_id,
            state_hash=client.state_hash(state),
            code_verifier_encrypted=client.cipher.encrypt(verifier),
            purpose=purpose,
            expected_channel_id=expected_channel_id,
            expires_at=datetime.now(UTC) + STATE_LIFETIME,
        )
    )
    await session.commit()
    return YouTubeOAuthStartResponse(
        authorization_url=client.create_authorization(
            scopes=scopes,
            state=state,
            code_verifier=verifier,
            force_consent=purpose == "connect",
        )
    )


@router.get("/connections", response_model=list[YouTubeConnectionPublic])
async def list_connections(
    user: CurrentUser,
    session: SessionDependency,
) -> list[YouTubeConnectionPublic]:
    result = await session.scalars(
        select(YouTubeConnection)
        .where(YouTubeConnection.owner_id == user.id)
        .order_by(YouTubeConnection.channel_title, YouTubeConnection.id)
    )
    return [
        YouTubeConnectionPublic(
            id=connection.id,
            channel_id=connection.channel_id,
            channel_title=connection.channel_title,
            channel_custom_url=connection.channel_custom_url,
            status=connection.status,
            analytics_enabled=YOUTUBE_ANALYTICS_SCOPE in connection.granted_scopes,
        )
        for connection in result.all()
    ]


@router.post("/connect", response_model=YouTubeOAuthStartResponse)
async def connect_channel(
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> YouTubeOAuthStartResponse:
    return await _start_authorization(
        request=request,
        user_id=user.id,
        session=session,
        purpose="connect",
    )


@router.post(
    "/connections/{connection_id}/analytics/authorize",
    response_model=YouTubeOAuthStartResponse,
)
async def authorize_analytics(
    connection_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> YouTubeOAuthStartResponse:
    connection = await session.scalar(
        select(YouTubeConnection).where(
            YouTubeConnection.id == connection_id,
            YouTubeConnection.owner_id == user.id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="YouTube channel not found.")
    if connection.status != "connected":
        raise HTTPException(status_code=409, detail="Reconnect this YouTube channel first.")
    if YOUTUBE_ANALYTICS_SCOPE in connection.granted_scopes:
        raise HTTPException(status_code=409, detail="Analytics access is already authorized.")
    return await _start_authorization(
        request=request,
        user_id=user.id,
        session=session,
        purpose="analytics",
        expected_channel_id=connection.channel_id,
    )


@router.get("/oauth/callback", include_in_schema=False)
async def oauth_callback(
    request: Request,
    session: SessionDependency,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    client = _client(request)
    if not state:
        return _frontend_redirect(request, "invalid_state")
    state_hash = client.state_hash(state)
    oauth_state = await session.scalar(
        select(YouTubeOAuthState).where(YouTubeOAuthState.state_hash == state_hash)
    )
    if oauth_state is None or not hmac.compare_digest(oauth_state.state_hash, state_hash):
        return _frontend_redirect(request, "invalid_state")
    expires_at = oauth_state.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if oauth_state.consumed_at is not None or expires_at <= datetime.now(UTC):
        return _frontend_redirect(request, "expired_state")

    consumed = await session.execute(
        update(YouTubeOAuthState)
        .where(
            YouTubeOAuthState.id == oauth_state.id,
            YouTubeOAuthState.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(UTC))
    )
    if consumed.rowcount != 1:
        await session.rollback()
        return _frontend_redirect(request, "expired_state")
    await session.commit()
    owner_id = oauth_state.owner_id
    purpose = oauth_state.purpose
    expected_channel_id = oauth_state.expected_channel_id

    if error:
        return _frontend_redirect(
            request,
            "cancelled" if error == "access_denied" else "oauth_failed",
        )
    if not code:
        return _frontend_redirect(request, "oauth_failed")

    try:
        verifier = client.cipher.decrypt(oauth_state.code_verifier_encrypted)
        token_data = await client.exchange_code(code, verifier)
        access_token = str(token_data["access_token"])
        channel = await client.get_authenticated_channel(access_token)
        if expected_channel_id and channel["channel_id"] != expected_channel_id:
            return _frontend_redirect(request, "channel_mismatch")
        connection = await session.scalar(
            select(YouTubeConnection).where(
                YouTubeConnection.owner_id == owner_id,
                YouTubeConnection.channel_id == channel["channel_id"],
            )
        )
        scopes_value = token_data.get("scope")
        granted_scopes = (
            set(scopes_value.split())
            if isinstance(scopes_value, str)
            else set(YOUTUBE_ANALYTICS_SCOPES if purpose == "analytics" else YOUTUBE_BASE_SCOPES)
        )
        if connection is not None:
            granted_scopes.update(connection.granted_scopes)
        if not set(YOUTUBE_BASE_SCOPES).issubset(granted_scopes):
            return _frontend_redirect(request, "missing_scope")
        if purpose == "analytics" and YOUTUBE_ANALYTICS_SCOPE not in granted_scopes:
            return _frontend_redirect(request, "missing_scope")

        refresh_token = token_data.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            if connection is None:
                return _frontend_redirect(request, "missing_refresh_token")
            try:
                try:
                    refresh_token = client.cipher.decrypt(connection.refresh_token_encrypted)
                except YouTubeOAuthNotConfigured:
                    refresh_token = None
            except YouTubeOAuthNotConfigured:
                logger.warning(
                    "Stored YouTube refresh token could not be decrypted for channel %s",
                    connection.channel_id,
                )
                return _frontend_redirect(request, "oauth_failed")
        if connection is None:
            connection = YouTubeConnection(
                owner_id=owner_id,
                channel_id=channel["channel_id"],
                channel_title=channel["channel_title"],
                channel_custom_url=channel.get("channel_custom_url"),
                refresh_token_encrypted=client.cipher.encrypt(refresh_token),
                granted_scopes=sorted(granted_scopes),
                status="connected",
                last_error=None,
            )
            session.add(connection)
        else:
            connection.channel_title = channel["channel_title"]
            connection.channel_custom_url = channel.get("channel_custom_url")
            connection.refresh_token_encrypted = client.cipher.encrypt(refresh_token)
            connection.granted_scopes = sorted(granted_scopes)
            connection.status = "connected"
            connection.last_error = None
        await session.commit()
        return _frontend_redirect(request, "connected")
    except YouTubeOAuthNotConfigured:
        logger.warning(
            "Stored YouTube OAuth verifier could not be decrypted for user %s",
            owner_id,
        )
        return _frontend_redirect(request, "oauth_failed")
    except YouTubeApiError as exception:
        logger.warning(
            "YouTube OAuth callback failed for user %s: status=%s reason=%s",
            owner_id,
            exception.status_code,
            exception.reason,
        )
        await session.rollback()
        return _frontend_redirect(request, "oauth_failed")


@router.post(
    "/connections/{connection_id}/disconnect",
    response_model=YouTubeDisconnectResponse,
)
async def disconnect_channel(
    connection_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> YouTubeDisconnectResponse:
    client = _client(request)
    connection = await session.scalar(
        select(YouTubeConnection).where(
            YouTubeConnection.id == connection_id,
            YouTubeConnection.owner_id == user.id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="YouTube channel not found.")
    refresh_token = client.cipher.decrypt(connection.refresh_token_encrypted)
    active_jobs = await session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "youtube_upload",
            ProcessingJob.status.in_(("queued", "processing")),
        )
    )
    for job in active_jobs:
        if (job.input_data or {}).get("connection_id") != str(connection_id):
            continue
        if job.status == "queued":
            job.status = "cancelled"
            job.error_message = "YouTube channel was disconnected."
            publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
            publication = await session.scalar(
                select(Publication).where(
                    Publication.id == publication_id,
                    Publication.owner_id == user.id,
                )
            )
            if publication is not None and publication.external_id is None:
                publication.youtube_status = "upload_cancelled"
        else:
            job.cancellation_requested = True
    await session.delete(connection)
    await session.commit()
    if refresh_token is None:
        return YouTubeDisconnectResponse(
            disconnected=True,
            provider_revoked=False,
            warning=(
                "The channel was disconnected locally, but the stored token could not be "
                "decrypted for Google revocation."
            ),
        )
    try:
        await client.revoke(refresh_token)
    except YouTubeApiError as error:
        logger.warning(
            "Google token revocation failed after local disconnect for user %s: status=%s",
            user.id,
            error.status_code,
        )
        return YouTubeDisconnectResponse(
            disconnected=True,
            provider_revoked=False,
            warning="The channel was disconnected locally, but Google token revocation failed.",
        )
    return YouTubeDisconnectResponse(disconnected=True, provider_revoked=True, warning=None)


async def _fresh_access_token(
    connection: YouTubeConnection,
    client: YouTubeApiClient,
    session: SessionDependency,
) -> str:
    if connection.status != "connected":
        raise HTTPException(status_code=409, detail="Reconnect this YouTube channel.")
    try:
        refresh_token = client.cipher.decrypt(connection.refresh_token_encrypted)
    except YouTubeOAuthNotConfigured as error:
        connection.status = "reauthorization_required"
        connection.last_error = "Token decryption failed; reconnect the channel."
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail="YouTube credentials cannot be decrypted; reconnect the channel.",
        ) from error
    try:
        token = await client.refresh_access_token(refresh_token)
    except YouTubeApiError as error:
        if error.reason == "invalid_grant":
            connection.status = "reauthorization_required"
            connection.last_error = "Google authorization expired or was revoked."
            await session.commit()
            raise HTTPException(
                status_code=409, detail="Reconnect this YouTube channel."
            ) from error
        raise HTTPException(status_code=502, detail=str(error)) from error
    return str(token["access_token"])


@router.get("/analytics", response_model=YouTubeAnalyticsPublic)
async def read_analytics(
    connection_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
    start_date: date | None = None,
    end_date: date | None = None,
) -> YouTubeAnalyticsPublic:
    client = _client(request)
    connection = await session.scalar(
        select(YouTubeConnection).where(
            YouTubeConnection.id == connection_id,
            YouTubeConnection.owner_id == user.id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="YouTube channel not found.")
    if YOUTUBE_ANALYTICS_SCOPE not in connection.granted_scopes:
        raise HTTPException(
            status_code=403,
            detail="Authorize YouTube Analytics access for this channel first.",
        )
    end = end_date or date.today()
    start = start_date or end - timedelta(days=28)
    if start > end or end > date.today() or end - start > timedelta(days=365):
        raise HTTPException(
            status_code=422,
            detail="Analytics dates must be ordered, no later than today, and within one year.",
        )
    access_token = await _fresh_access_token(connection, client, session)
    try:
        data = await client.get_analytics(
            access_token=access_token,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
    except YouTubeApiError as error:
        if error.reason in {"insufficientPermissions", "forbidden"}:
            connection.status = "reauthorization_required"
            connection.last_error = "Google denied YouTube Analytics access."
            await session.commit()
            raise HTTPException(status_code=403, detail=str(error)) from error
        raise HTTPException(status_code=502, detail=str(error)) from error
    daily = data.get("daily")
    traffic = data.get("traffic_sources")
    daily_report = daily if isinstance(daily, dict) else {}
    traffic_report = traffic if isinstance(traffic, dict) else {}
    rows = daily_report.get("rows")
    last_row = rows[-1] if isinstance(rows, list) and rows else None
    available_through = (
        str(last_row[0]) if isinstance(last_row, list) and last_row else None
    )
    return YouTubeAnalyticsPublic(
        daily=daily_report,
        traffic_sources=traffic_report,
        available_through=available_through,
    )


@router.post("/publications/{publication_id}/thumbnail")
async def upload_publication_thumbnail(
    publication_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDependency,
) -> dict[str, bool]:
    client = _client(request)
    publication = await session.scalar(
        select(Publication).where(
            Publication.id == publication_id,
            Publication.owner_id == user.id,
        )
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    if not publication.external_id:
        raise HTTPException(status_code=409, detail="Upload the video before its thumbnail.")
    if publication.thumbnail_asset_id is None:
        raise HTTPException(status_code=422, detail="Select a thumbnail for this publication.")

    upload_jobs = await session.scalars(
        select(ProcessingJob)
        .where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "youtube_upload",
            ProcessingJob.status == "completed",
        )
        .order_by(ProcessingJob.created_at.desc(), ProcessingJob.id)
    )
    completed_job = next(
        (
            job
            for job in upload_jobs
            if (job.input_data or {}).get("publication_id") == str(publication.id)
            and (job.input_data or {}).get("connection_id")
        ),
        None,
    )
    if completed_job is None:
        raise HTTPException(status_code=409, detail="No completed YouTube upload is associated.")
    try:
        connection_id = UUID(str((completed_job.input_data or {})["connection_id"]))
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=409, detail="The upload's channel association is invalid.") from error
    connection = await session.scalar(
        select(YouTubeConnection).where(
            YouTubeConnection.id == connection_id,
            YouTubeConnection.owner_id == user.id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=409, detail="Reconnect the YouTube channel to continue.")
    thumbnail = await session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == publication.thumbnail_asset_id,
            MediaAsset.owner_id == user.id,
            MediaAsset.media_type == "image",
            or_(
                MediaAsset.project_id == publication.project_id,
                MediaAsset.project_id.is_(None),
            ),
        )
    )
    if thumbnail is None:
        raise HTTPException(status_code=404, detail="Thumbnail asset not found.")
    access_token = await _fresh_access_token(connection, client, session)
    async with request.app.state.storage.local_file(thumbnail.storage_key) as thumbnail_path:
        try:
            await client.upload_thumbnail(
                access_token=access_token,
                video_id=publication.external_id,
                file_path=thumbnail_path,
                content_type=thumbnail.content_type,
            )
        except YouTubeApiError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
    completed_job.output_data = {
        **(completed_job.output_data or {}),
        "thumbnail_uploaded": True,
    }
    await session.commit()
    return {"uploaded": True}


@router.post(
    "/publications/{publication_id}/uploads",
    response_model=YouTubeUploadJobPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_upload(
    publication_id: UUID,
    payload: YouTubeUploadRequest,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    publication = await session.scalar(
        select(Publication).where(
            Publication.id == publication_id,
            Publication.owner_id == user.id,
        )
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    if publication.platform != "youtube":
        raise HTTPException(status_code=422, detail="This release is not configured for YouTube.")
    if publication.external_id:
        raise HTTPException(status_code=409, detail="This release already has a YouTube video.")
    if publication.media_asset_id is None and publication.clip_candidate_id is None:
        raise HTTPException(status_code=422, detail="Select an exported video before uploading.")
    connection = await session.scalar(
        select(YouTubeConnection).where(
            YouTubeConnection.id == payload.connection_id,
            YouTubeConnection.owner_id == user.id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="YouTube channel not found.")
    if connection.status != "connected":
        raise HTTPException(status_code=409, detail="Reconnect this YouTube channel first.")
    if not set(YOUTUBE_BASE_SCOPES).issubset(connection.granted_scopes):
        raise HTTPException(status_code=403, detail="Reconnect and authorize YouTube upload access.")
    if payload.publish_at is not None:
        if payload.privacy_status != "private":
            raise HTTPException(
                status_code=422,
                detail="YouTube native scheduling requires private visibility.",
            )
        if payload.publish_at <= datetime.now(UTC):
            raise HTTPException(status_code=422, detail="YouTube publish time must be in the future.")

    active_jobs = await session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "youtube_upload",
            ProcessingJob.status.in_(("queued", "processing")),
        )
    )
    if any(
        (job.input_data or {}).get("publication_id") == str(publication.id)
        for job in active_jobs
    ):
        raise HTTPException(
            status_code=409,
            detail="This release already has an active YouTube upload.",
        )

    asset_id = publication.media_asset_id
    if publication.clip_candidate_id is not None:
        candidate = await session.scalar(
            select(ClipCandidate).where(
                ClipCandidate.id == publication.clip_candidate_id,
                ClipCandidate.project_id == publication.project_id,
            )
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="Clip candidate not found.")
        if candidate.exported_media_asset_id is not None:
            asset_id = candidate.exported_media_asset_id
    asset = (
        await session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == asset_id,
                MediaAsset.owner_id == user.id,
                or_(
                    MediaAsset.project_id == publication.project_id,
                    MediaAsset.project_id.is_(None),
                ),
                MediaAsset.media_type == "video",
            )
        )
        if asset_id
        else None
    )
    if asset is None:
        raise HTTPException(status_code=422, detail="Select an exported video from this project.")
    try:
        metadata = _publication_metadata(publication)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Publication metadata is invalid.") from error
    if not metadata["title"]:
        raise HTTPException(status_code=422, detail="Add a title before uploading.")
    if len(metadata["description"]) > 5000:
        raise HTTPException(
            status_code=422,
            detail="The description and chapter text exceed YouTube's 5,000-character limit.",
        )
    if len(metadata["description"].encode("utf-8")) > 5000:
        raise HTTPException(
            status_code=422,
            detail="The description and chapter text exceed YouTube's 5,000-byte limit.",
        )
    if "<" in metadata["title"] or ">" in metadata["title"]:
        raise HTTPException(
            status_code=422,
            detail="YouTube titles cannot contain angle brackets.",
        )
    if metadata["category"] and not metadata["category"].isdigit():
        raise HTTPException(
            status_code=422,
            detail="YouTube category must be a numeric video category ID.",
        )
    if sum(len(tag) for tag in metadata["tags"]) > 500:
        raise HTTPException(status_code=422, detail="YouTube tags exceed the 500-character limit.")

    job = ProcessingJob(
        owner_id=user.id,
        project_id=publication.project_id,
        job_type="youtube_upload",
        status="queued",
        input_data={
            "publication_id": str(publication.id),
            "connection_id": str(connection.id),
            "privacy_status": payload.privacy_status,
            "publish_at": payload.publish_at.isoformat() if payload.publish_at else None,
        },
        max_retries=2,
    )
    publication.youtube_status = "upload_queued"
    publication.youtube_privacy_status = payload.privacy_status
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _owned_upload_job(
    job_id: UUID,
    user_id: UUID,
    session: SessionDependency,
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.owner_id == user_id,
            ProcessingJob.job_type == "youtube_upload",
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="YouTube upload job not found.")
    return job


@router.get("/uploads", response_model=list[YouTubeUploadJobPublic])
async def list_uploads(
    user: CurrentUser,
    session: SessionDependency,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ProcessingJob]:
    result = await session.scalars(
        select(ProcessingJob)
        .where(
            ProcessingJob.owner_id == user.id,
            ProcessingJob.job_type == "youtube_upload",
        )
        .order_by(ProcessingJob.created_at.desc(), ProcessingJob.id)
        .limit(limit)
    )
    return list(result.all())


@router.get("/uploads/{job_id}", response_model=YouTubeUploadJobPublic)
async def read_upload(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    return await _owned_upload_job(job_id, user.id, session)


@router.post("/uploads/{job_id}/retry", response_model=YouTubeUploadJobPublic)
async def retry_upload(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    job = await _owned_upload_job(job_id, user.id, session)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled uploads can retry.")
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=409, detail="This upload has reached its retry limit.")
    publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
    publication = await session.scalar(
        select(Publication).where(
            Publication.id == publication_id,
            Publication.owner_id == user.id,
        )
    )
    if publication is None or publication.external_id:
        raise HTTPException(status_code=409, detail="This publication can no longer be retried.")
    connection_id = UUID(str((job.input_data or {}).get("connection_id", "")))
    connection = await session.scalar(
        select(YouTubeConnection).where(
            YouTubeConnection.id == connection_id,
            YouTubeConnection.owner_id == user.id,
        )
    )
    if connection is None or connection.status != "connected":
        raise HTTPException(status_code=409, detail="Reconnect the YouTube channel before retrying.")
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    job.cancellation_requested = False
    job.retry_count += 1
    publication.youtube_status = "upload_queued"
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/uploads/{job_id}/cancel", response_model=YouTubeUploadJobPublic)
async def cancel_upload(
    job_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> ProcessingJob:
    job = await _owned_upload_job(job_id, user.id, session)
    if job.status == "queued":
        job.status = "cancelled"
        job.error_message = "YouTube upload was cancelled."
        publication_id = UUID(str((job.input_data or {}).get("publication_id", "")))
        publication = await session.scalar(
            select(Publication).where(
                Publication.id == publication_id,
                Publication.owner_id == user.id,
            )
        )
        if publication is not None and publication.external_id is None:
            publication.youtube_status = "upload_cancelled"
    elif job.status == "processing":
        job.cancellation_requested = True
    else:
        raise HTTPException(status_code=409, detail="Only queued or processing uploads can cancel.")
    await session.commit()
    await session.refresh(job)
    return job
