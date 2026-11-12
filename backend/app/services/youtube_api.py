"""Official Google OAuth and YouTube Data/Analytics API client."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_BASE_SCOPES = (YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE)
YOUTUBE_ANALYTICS_SCOPES = (
    YOUTUBE_UPLOAD_SCOPE,
    YOUTUBE_READONLY_SCOPE,
    YOUTUBE_ANALYTICS_SCOPE,
)
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD_BASE_URL = "https://www.googleapis.com/upload/youtube/v3"
YOUTUBE_ANALYTICS_BASE_URL = "https://youtubeanalytics.googleapis.com/v2"
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024


class YouTubeApiError(Exception):
    """Sanitized provider failure suitable for persistence and API reporting."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.retryable = retryable


class YouTubeOAuthNotConfigured(Exception):
    """Required Google OAuth credentials or encryption key are absent."""


class YouTubeUploadAborted(Exception):
    """Raised when an owner requests cancellation during a resumable upload."""


class YouTubeTokenCipher:
    """Fernet encrypt/decrypt wrapper for Google refresh and temporary PKCE tokens."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise ValueError(
                "YOUTUBE_TOKEN_ENCRYPTION_KEY must be a URL-safe base64 Fernet key."
            ) from error

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeEncodeError) as error:
            raise YouTubeOAuthNotConfigured(
                "Stored YouTube credentials cannot be decrypted; check the encryption key."
            ) from error


class YouTubeApiClient:
    """Small async OAuth/API client that uses only official Google endpoints."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not (
            settings.youtube_oauth_client_id
            and settings.youtube_oauth_client_secret
            and settings.youtube_oauth_redirect_uri
            and settings.youtube_token_encryption_key
        ):
            raise YouTubeOAuthNotConfigured("YouTube OAuth is not configured.")
        self.settings = settings
        self.client_id = settings.youtube_oauth_client_id
        self.client_secret = settings.youtube_oauth_client_secret.get_secret_value()
        self.redirect_uri = str(settings.youtube_oauth_redirect_uri)
        self.frontend_return_url = str(settings.youtube_oauth_frontend_return_url)
        self.cipher = YouTubeTokenCipher(
            settings.youtube_token_encryption_key.get_secret_value()
        )
        self.transport = transport

    def create_authorization(
        self,
        *,
        scopes: tuple[str, ...],
        state: str,
        code_verifier: str,
        force_consent: bool,
    ) -> str:
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if force_consent:
            params["prompt"] = "consent"
        return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"

    @staticmethod
    def new_state() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def state_hash(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    @staticmethod
    def new_code_verifier() -> str:
        return secrets.token_urlsafe(64)

    async def exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        data = await self._request_json(
            "POST",
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            retry=False,
        )
        if not isinstance(data.get("access_token"), str):
            raise YouTubeApiError("Google did not return an access token.")
        return data

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        try:
            data = await self._request_json(
                "POST",
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                retry=False,
            )
        except YouTubeApiError as error:
            if error.reason == "invalid_grant":
                raise YouTubeApiError(
                    "YouTube authorization was revoked or expired. Reconnect the channel.",
                    status_code=error.status_code,
                    reason=error.reason,
                ) from error
            raise
        if not isinstance(data.get("access_token"), str):
            raise YouTubeApiError("Google did not return a refreshed access token.")
        return data

    async def get_authenticated_channel(self, access_token: str) -> dict[str, str]:
        data = await self._request_json(
            "GET",
            f"{YOUTUBE_API_BASE_URL}/channels",
            params={"part": "snippet", "mine": "true", "maxResults": "50"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        items = data.get("items")
        if not isinstance(items, list) or not items:
            raise YouTubeApiError(
                "The authorized Google account does not have an accessible YouTube channel."
            )
        if len(items) != 1:
            raise YouTubeApiError(
                "This Google account has multiple YouTube channels; explicit channel selection "
                "is not available yet."
            )
        item = items[0]
        snippet = item.get("snippet", {}) if isinstance(item, dict) else {}
        channel_id = item.get("id") if isinstance(item, dict) else None
        title = snippet.get("title") if isinstance(snippet, dict) else None
        custom_url = snippet.get("customUrl") if isinstance(snippet, dict) else None
        if not isinstance(channel_id, str) or not isinstance(title, str):
            raise YouTubeApiError("Google returned incomplete YouTube channel information.")
        channel: dict[str, str] = {"channel_id": channel_id, "channel_title": title}
        if isinstance(custom_url, str):
            channel["channel_custom_url"] = custom_url
        return channel

    async def revoke(self, token: str) -> None:
        await self._request_json(
            "POST",
            GOOGLE_REVOKE_URL,
            data={"token": token},
            expected_statuses={200},
            retry=False,
        )

    async def upload_video(
        self,
        *,
        access_token: str,
        file_path: Path,
        content_type: str,
        metadata: dict[str, Any],
        privacy_status: str,
        publish_at: datetime | None,
        progress: Callable[[int], Awaitable[None]],
        cancelled: Callable[[], Awaitable[bool]],
    ) -> dict[str, Any]:
        if publish_at is not None:
            if privacy_status != "private":
                raise YouTubeApiError(
                    "YouTube native scheduling requires private visibility before its publish time."
                )
            if publish_at.tzinfo is None:
                raise YouTubeApiError("YouTube scheduled publish time must include a timezone.")

        title = metadata.get("title")
        description = metadata.get("description") or ""
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise YouTubeApiError("YouTube titles must contain 1 to 100 characters.")
        if "<" in title or ">" in title:
            raise YouTubeApiError("YouTube titles cannot contain angle brackets.")
        if not isinstance(description, str) or len(description.encode("utf-8")) > 5000:
            raise YouTubeApiError("YouTube descriptions must not exceed 5,000 UTF-8 bytes.")

        snippet: dict[str, Any] = {
            "title": title,
            "description": description,
        }
        tags = metadata.get("tags")
        if tags:
            snippet["tags"] = tags
        category_id = metadata.get("category")
        if category_id:
            if not str(category_id).isdigit():
                raise YouTubeApiError(
                    "YouTube category must be a numeric video category ID."
                )
            snippet["categoryId"] = str(category_id)
        if metadata.get("language"):
            snippet["defaultLanguage"] = metadata["language"]
        video_resource: dict[str, Any] = {
            "snippet": snippet,
            "status": {"privacyStatus": privacy_status},
        }
        if publish_at:
            video_resource["status"]["publishAt"] = publish_at.astimezone(UTC).isoformat()

        file_size = await asyncio.to_thread(file_path.stat)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(file_size.st_size),
            "X-Upload-Content-Type": content_type,
        }
        initiation = await self._request(
            "POST",
            f"{YOUTUBE_UPLOAD_BASE_URL}/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            json=video_resource,
            retry=True,
        )
        session_url = initiation.headers.get("location")
        if not session_url:
            raise YouTubeApiError("YouTube did not return a resumable upload URL.")
        if not session_url.startswith("https://www.googleapis.com/upload/youtube/"):
            raise YouTubeApiError("YouTube returned an unexpected upload session URL.")

        uploaded = 0
        stalled_responses = 0
        with file_path.open("rb") as media_file:
            while uploaded < file_size.st_size:
                if await cancelled():
                    raise YouTubeUploadAborted
                await asyncio.to_thread(media_file.seek, uploaded)
                chunk = await asyncio.to_thread(media_file.read, UPLOAD_CHUNK_SIZE)
                if not chunk:
                    raise YouTubeApiError("The source video ended before the upload completed.")
                end = uploaded + len(chunk) - 1
                response = await self._upload_chunk(
                    session_url,
                    chunk,
                    start=uploaded,
                    end=end,
                    total=file_size.st_size,
                )
                if response.status_code in {200, 201}:
                    try:
                        result = response.json()
                    except ValueError as error:
                        raise YouTubeApiError(
                            "YouTube completed the upload but returned invalid video metadata."
                        ) from error
                    if not isinstance(result.get("id"), str):
                        raise YouTubeApiError(
                            "YouTube completed the request without a video ID."
                        )
                    return result
                if response.status_code != 308:
                    raise self._provider_error(response)
                received_range = response.headers.get("range")
                if received_range:
                    try:
                        acknowledged = int(received_range.rsplit("-", 1)[1]) + 1
                    except (IndexError, ValueError) as error:
                        raise YouTubeApiError(
                            "YouTube returned an invalid resumable-upload range."
                        ) from error
                    if not uploaded < acknowledged <= file_size.st_size:
                        raise YouTubeApiError(
                            "YouTube returned an unexpected resumable-upload offset."
                        )
                else:
                    acknowledged = 0
                if acknowledged <= uploaded:
                    stalled_responses += 1
                    if stalled_responses >= 3:
                        raise YouTubeApiError(
                            "YouTube did not acknowledge upload data.",
                            retryable=True,
                        )
                else:
                    uploaded = acknowledged
                    stalled_responses = 0
                    await progress(min(99, int(uploaded * 100 / file_size.st_size)))

        raise YouTubeApiError("The resumable upload ended without a confirmed video response.")

    async def upload_thumbnail(
        self,
        *,
        access_token: str,
        video_id: str,
        file_path: Path,
        content_type: str,
    ) -> None:
        file_size = await asyncio.to_thread(file_path.stat)
        if file_size.st_size > 2 * 1024 * 1024:
            raise YouTubeApiError("YouTube thumbnails must be 2 MB or smaller.")
        if content_type not in {"image/jpeg", "image/png"}:
            raise YouTubeApiError("YouTube thumbnails must be JPEG or PNG images.")
        with file_path.open("rb") as handle:
            content = await asyncio.to_thread(handle.read)
        await self._request(
            "POST",
            f"{YOUTUBE_UPLOAD_BASE_URL}/thumbnails/set",
            params={"videoId": video_id},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": content_type,
            },
            content=content,
            retry=True,
        )

    async def get_analytics(
        self,
        *,
        access_token: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        common = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
        }
        headers = {"Authorization": f"Bearer {access_token}"}
        daily = await self._request_json(
            "GET",
            f"{YOUTUBE_ANALYTICS_BASE_URL}/reports",
            params={
                **common,
                "metrics": (
                    "views,estimatedMinutesWatched,averageViewDuration,likes,comments,"
                    "subscribersGained"
                ),
                "dimensions": "day",
                "sort": "day",
            },
            headers=headers,
        )
        traffic = await self._request_json(
            "GET",
            f"{YOUTUBE_ANALYTICS_BASE_URL}/reports",
            params={
                **common,
                "metrics": "views",
                "dimensions": "insightTrafficSourceType",
                "sort": "-views",
            },
            headers=headers,
        )
        return {"daily": daily, "traffic_sources": traffic}

    async def _upload_chunk(
        self,
        session_url: str,
        chunk: bytes,
        *,
        start: int,
        end: int,
        total: int,
    ) -> httpx.Response:
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(transport=self.transport, timeout=180) as client:
                    response = await client.put(
                        session_url,
                        content=chunk,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {start}-{end}/{total}",
                        },
                    )
            except httpx.RequestError as error:
                if attempt == 2:
                    raise YouTubeApiError(
                        "The YouTube upload connection failed.",
                        retryable=True,
                    ) from error
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code >= 500 and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code in {200, 201, 308}:
                return response
            raise self._provider_error(response)
        raise YouTubeApiError("The YouTube upload connection failed.", retryable=True)

    async def _request_json(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = await self._request(method, url, **kwargs)
        if response.status_code == 204:
            return {}
        try:
            result = response.json()
        except ValueError as error:
            raise YouTubeApiError("Google returned an invalid response.") from error
        if not isinstance(result, dict):
            raise YouTubeApiError("Google returned an invalid response.")
        return result

    async def _request(
        self,
        method: str,
        url: str,
        *,
        expected_statuses: set[int] | None = None,
        retry: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        expected = expected_statuses or {200}
        for attempt in range(3 if retry else 1):
            try:
                async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
                    response = await client.request(method, url, **kwargs)
            except httpx.RequestError as error:
                if attempt + 1 >= (3 if retry else 1):
                    raise YouTubeApiError(
                        "The connection to Google failed.",
                        retryable=retry,
                    ) from error
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code in expected:
                return response
            if retry and response.status_code >= 500 and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            raise self._provider_error(response)
        raise YouTubeApiError("The Google API request failed.", retryable=retry)

    @staticmethod
    def _provider_error(response: httpx.Response) -> YouTubeApiError:
        reason = None
        try:
            body = response.json()
            error = body.get("error", {})
            if isinstance(error, str):
                reason = error
            errors = error.get("errors", []) if isinstance(error, dict) else []
            if errors and isinstance(errors[0], dict):
                reason = errors[0].get("reason")
            reason = reason or (error.get("status") if isinstance(error, dict) else None)
        except (ValueError, AttributeError, IndexError):
            pass
        quota_error = reason in {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}
        sanitized = (
            "YouTube API quota or rate limit was reached."
            if quota_error
            else f"Google API request failed with HTTP {response.status_code}."
        )
        return YouTubeApiError(
            sanitized,
            status_code=response.status_code,
            reason=reason,
            retryable=response.status_code >= 500
            or response.status_code == 429
            or reason == "rateLimitExceeded",
        )
