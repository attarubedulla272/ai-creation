"""Official YouTube OAuth, resumable-upload, ownership, and analytics tests."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter
from pydantic.networks import AnyHttpUrl

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from app.services.youtube_api import (
    GOOGLE_TOKEN_URL,
    YOUTUBE_ANALYTICS_SCOPE,
    YOUTUBE_BASE_SCOPES,
    YOUTUBE_UPLOAD_BASE_URL,
    YouTubeApiClient,
    YouTubeTokenCipher,
)

PASSWORD = "correct-horse-battery-41"
CALLBACK = "http://localhost:8000/api/v1/publishing/youtube/oauth/callback"
RETURN_URL = "http://localhost:3000/seo-publish"
MP4_HEADER = b"\x00\x00\x00\x18ftypisomtest-media"


def _account(client: TestClient, email: str) -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert registered.status_code == 201
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _settings(tmp_path, *, with_youtube: bool) -> Settings:
    values = {
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'youtube-test.db'}",
        "jwt_secret_key": SecretStr("test-only-secret-key-not-for-production-123"),
        "environment": "test",
        "storage_path": tmp_path / "storage",
    }
    if with_youtube:
        values.update(
            {
                "youtube_oauth_client_id": "test-client-id",
                "youtube_oauth_client_secret": SecretStr("test-client-secret"),
                "youtube_oauth_redirect_uri": TypeAdapter(AnyHttpUrl).validate_python(CALLBACK),
                "youtube_oauth_frontend_return_url": TypeAdapter(AnyHttpUrl).validate_python(
                    RETURN_URL
                ),
                "youtube_token_encryption_key": SecretStr(
                    Fernet.generate_key().decode("ascii")
                ),
            }
        )
    return Settings(**values)


def _provider_handler(request: httpx.Request) -> httpx.Response:
    if request.url == httpx.URL(GOOGLE_TOKEN_URL):
        body = parse_qs(request.content.decode())
        if body.get("grant_type") == ["authorization_code"]:
            scopes = " ".join(YOUTUBE_BASE_SCOPES)
            if body.get("code") == ["test-analytics-code"]:
                scopes = " ".join((*YOUTUBE_BASE_SCOPES, YOUTUBE_ANALYTICS_SCOPE))
            return httpx.Response(
                200,
                json={
                    "access_token": "test-access-token",
                    "refresh_token": "test-refresh-token",
                    "scope": scopes,
                },
            )
        return httpx.Response(200, json={"access_token": "refreshed-access-token"})
    if str(request.url).startswith("https://www.googleapis.com/youtube/v3/channels"):
        assert request.headers["authorization"] == "Bearer test-access-token"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UC-test-channel",
                        "snippet": {"title": "Authorized Test Channel", "customUrl": "@test"},
                    }
                ]
            },
        )
    if str(request.url).startswith("https://youtubeanalytics.googleapis.com/v2/reports"):
        if "insightTrafficSourceType" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "columnHeaders": [
                        {"name": "insightTrafficSourceType"},
                        {"name": "views"},
                    ],
                    "rows": [["YT_SEARCH", 12]],
                },
            )
        return httpx.Response(
            200,
            json={
                "columnHeaders": [
                    {"name": "day"},
                    {"name": "views"},
                    {"name": "estimatedMinutesWatched"},
                    {"name": "averageViewDuration"},
                    {"name": "likes"},
                    {"name": "comments"},
                    {"name": "subscribersGained"},
                ],
                "rows": [["2026-11-11", 12, 4, 20, 2, 1, 1]],
            },
        )
    if str(request.url).startswith(f"{YOUTUBE_UPLOAD_BASE_URL}/videos"):
        return httpx.Response(
            200,
            headers={
                "Location": (
                    "https://www.googleapis.com/upload/youtube/v3/session?upload_id=test-session"
                )
            },
        )
    if str(request.url).startswith("https://www.googleapis.com/upload/youtube/v3/session"):
        return httpx.Response(201, json={"id": "video-confirmed-123"})
    if str(request.url) == "https://oauth2.googleapis.com/revoke":
        return httpx.Response(200)
    raise AssertionError(f"Unexpected test provider request: {request.method} {request.url}")


def _connect(client: TestClient, token: str) -> dict[str, str]:
    start = client.post("/api/v1/publishing/youtube/connect", headers=_headers(token))
    assert start.status_code == 200, start.text
    authorization = urlsplit(start.json()["authorization_url"])
    state = parse_qs(authorization.query)["state"][0]
    callback = client.get(
        CALLBACK,
        params={"state": state, "code": "test-authorization-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert parse_qs(urlsplit(callback.headers["location"]).query)["youtube_connection"] == [
        "connected"
    ]
    connections = client.get(
        "/api/v1/publishing/youtube/connections",
        headers=_headers(token),
    )
    assert connections.status_code == 200
    return connections.json()[0]


def test_token_cipher_never_stores_plaintext() -> None:
    cipher = YouTubeTokenCipher(Fernet.generate_key().decode("ascii"))
    encrypted = cipher.encrypt("provider-refresh-token")
    assert encrypted != "provider-refresh-token"
    assert "provider-refresh-token" not in encrypted
    assert cipher.decrypt(encrypted) == "provider-refresh-token"


def test_youtube_is_optional_but_production_redirects_must_be_https() -> None:
    settings = Settings(
        environment="production",
        jwt_secret_key=SecretStr("test-only-secret-key-not-for-production-123"),
    )
    assert settings.youtube_oauth_client_id is None

    with pytest.raises(ValueError, match="frontend return URL must use HTTPS"):
        Settings(
            environment="production",
            jwt_secret_key=SecretStr("test-only-secret-key-not-for-production-123"),
            youtube_oauth_client_id="test-client-id",
            youtube_oauth_client_secret=SecretStr("test-client-secret"),
            youtube_oauth_redirect_uri=TypeAdapter(AnyHttpUrl).validate_python(
                "https://api.example.test/callback"
            ),
            youtube_token_encryption_key=SecretStr(Fernet.generate_key().decode("ascii")),
        )


def test_oauth_state_is_single_use_and_tokens_stay_server_side(client: TestClient) -> None:
    settings = _settings_from_existing(client)
    transport = httpx.MockTransport(_provider_handler)
    client.app.state.settings = settings
    client.app.state.youtube_client = YouTubeApiClient(settings, transport=transport)
    token = _account(client, "youtube-oauth-owner@example.com")

    channel = _connect(client, token)
    assert channel["channel_title"] == "Authorized Test Channel"
    assert channel["status"] == "connected"
    assert channel["analytics_enabled"] is False
    assert "refresh_token" not in str(channel)
    assert "test-refresh-token" not in str(channel)

    start = client.post("/api/v1/publishing/youtube/connect", headers=_headers(token))
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    replay = client.get(
        CALLBACK,
        params={"state": state, "code": "test-authorization-code"},
        follow_redirects=False,
    )
    assert replay.status_code == 303
    assert parse_qs(urlsplit(replay.headers["location"]).query)["youtube_connection"] == [
        "connected"
    ]
    replayed = client.get(
        CALLBACK,
        params={"state": state, "code": "test-authorization-code"},
        follow_redirects=False,
    )
    assert parse_qs(urlsplit(replayed.headers["location"]).query)["youtube_connection"] == [
        "expired_state"
    ]


def _settings_from_existing(client: TestClient) -> Settings:
    original = client.app.state.settings
    return original.model_copy(
        update={
            "youtube_oauth_client_id": "test-client-id",
            "youtube_oauth_client_secret": SecretStr("test-client-secret"),
            "youtube_oauth_redirect_uri": TypeAdapter(AnyHttpUrl).validate_python(CALLBACK),
            "youtube_oauth_frontend_return_url": TypeAdapter(AnyHttpUrl).validate_python(
                RETURN_URL
            ),
            "youtube_token_encryption_key": SecretStr(Fernet.generate_key().decode("ascii")),
        }
    )


def test_oauth_endpoints_are_authenticated_and_owner_scoped(client: TestClient) -> None:
    settings = _settings_from_existing(client)
    client.app.state.settings = settings
    client.app.state.youtube_client = YouTubeApiClient(
        settings,
        transport=httpx.MockTransport(_provider_handler),
    )
    owner_token = _account(client, "youtube-owner@example.com")
    other_token = _account(client, "youtube-other@example.com")
    connection = _connect(client, owner_token)

    unauthenticated = client.post("/api/v1/publishing/youtube/connect")
    hidden = client.post(
        f"/api/v1/publishing/youtube/connections/{connection['id']}/analytics/authorize",
        headers=_headers(other_token),
    )
    assert unauthenticated.status_code == 401
    assert hidden.status_code == 404

    analytics_start = client.post(
        f"/api/v1/publishing/youtube/connections/{connection['id']}/analytics/authorize",
        headers=_headers(owner_token),
    )
    assert analytics_start.status_code == 200
    authorization = urlsplit(analytics_start.json()["authorization_url"])
    assert YOUTUBE_ANALYTICS_SCOPE in parse_qs(authorization.query)["scope"][0]
    analytics_state = parse_qs(authorization.query)["state"][0]
    analytics_callback = client.get(
        CALLBACK,
        params={"state": analytics_state, "code": "test-analytics-code"},
        follow_redirects=False,
    )
    assert analytics_callback.status_code == 303
    analytics = client.get(
        "/api/v1/publishing/youtube/analytics",
        headers=_headers(owner_token),
        params={"connection_id": connection["id"]},
    )
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["daily"]["rows"][0][1] == 12

    denied = client.get(
        CALLBACK,
        params={"state": "forged-state", "code": "test-authorization-code"},
        follow_redirects=False,
    )
    assert parse_qs(urlsplit(denied.headers["location"]).query)["youtube_connection"] == [
        "invalid_state"
    ]

    project = client.post(
        "/api/v1/projects",
        headers=_headers(owner_token),
        json={"name": "Owned upload project"},
    )
    media = client.post(
        "/api/v1/media",
        headers=_headers(owner_token),
        data={"project_id": project.json()["id"]},
        files={"file": ("sample.mp4", MP4_HEADER, "video/mp4")},
    )
    publication = client.post(
        f"/api/v1/publishing/projects/{project.json()['id']}/publications",
        headers=_headers(owner_token),
        json={
            "platform": "youtube",
            "title": "Owned release",
            "media_asset_id": media.json()["asset"]["id"],
        },
    )
    upload_url = (
        f"/api/v1/publishing/youtube/publications/{publication.json()['id']}/uploads"
    )
    queued = client.post(
        upload_url,
        headers=_headers(owner_token),
        json={"connection_id": connection["id"], "privacy_status": "private"},
    )
    duplicate = client.post(
        upload_url,
        headers=_headers(owner_token),
        json={"connection_id": connection["id"], "privacy_status": "private"},
    )
    other_read = client.get(
        f"/api/v1/publishing/youtube/uploads/{queued.json()['id']}",
        headers=_headers(other_token),
    )
    edit_during_upload = client.patch(
        f"/api/v1/publishing/publications/{publication.json()['id']}",
        headers=_headers(owner_token),
        json={"title": "Changed during upload"},
    )
    assert queued.status_code == 202
    assert queued.json()["input_data"]["publish_at"] is None
    assert duplicate.status_code == 409
    assert other_read.status_code == 404
    assert edit_during_upload.status_code == 409

    cancelled = client.post(
        f"/api/v1/publishing/youtube/uploads/{queued.json()['id']}/cancel",
        headers=_headers(owner_token),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    retry = client.post(
        f"/api/v1/publishing/youtube/uploads/{queued.json()['id']}/retry",
        headers=_headers(owner_token),
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"

def test_resumable_upload_handles_partial_chunk_acknowledgement(tmp_path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = request.content.decode()
            assert '"privacyStatus":"private"' in body
            assert request.headers["x-upload-content-type"] == "video/mp4"
            return httpx.Response(
                200,
                headers={
                    "Location": (
                        "https://www.googleapis.com/upload/youtube/v3/session?upload_id=partial"
                    )
                },
            )
        requests.append(request.headers["content-range"])
        if len(requests) == 1:
            return httpx.Response(308, headers={"Range": "bytes=0-4"})
        return httpx.Response(201, json={"id": "video-confirmed-123"})

    settings = _settings_from_existing_settings(tmp_path)
    client = YouTubeApiClient(settings, transport=httpx.MockTransport(handler))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"0123456789")

    async def report_progress(_: int) -> None:
        return None

    async def not_cancelled() -> bool:
        return False

    result = asyncio.run(
        client.upload_video(
            access_token="test-access-token",
            file_path=source,
            content_type="video/mp4",
            metadata={"title": "Test upload"},
            privacy_status="private",
            publish_at=None,
            progress=report_progress,
            cancelled=not_cancelled,
        )
    )
    assert result["id"] == "video-confirmed-123"
    assert requests == ["bytes 0-9/10", "bytes 5-9/10"]


def _settings_from_existing_settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'unused.db'}",
        jwt_secret_key=SecretStr("test-only-secret-key-not-for-production-123"),
        environment="test",
        storage_path=tmp_path / "storage",
        youtube_oauth_client_id="test-client-id",
        youtube_oauth_client_secret=SecretStr("test-client-secret"),
        youtube_oauth_redirect_uri=TypeAdapter(AnyHttpUrl).validate_python(CALLBACK),
        youtube_oauth_frontend_return_url=TypeAdapter(AnyHttpUrl).validate_python(RETURN_URL),
        youtube_token_encryption_key=SecretStr(Fernet.generate_key().decode("ascii")),
    )


def test_confirmed_mock_upload_persists_in_background_worker(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, with_youtube=True)
    application = create_app(settings)

    async def create_schema() -> None:
        async with application.state.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    youtube_client = YouTubeApiClient(
        settings,
        transport=httpx.MockTransport(_provider_handler),
    )
    application.state.youtube_client = youtube_client
    with TestClient(application) as test_client:
        token = _account(test_client, "youtube-worker-owner@example.com")
        project = test_client.post(
            "/api/v1/projects",
            headers=_headers(token),
            json={"name": "Upload worker project"},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]
        connection = _connect(test_client, token)
        media = test_client.post(
            "/api/v1/media",
            headers=_headers(token),
            data={"project_id": project_id},
            files={"file": ("sample.mp4", MP4_HEADER, "video/mp4")},
        )
        assert media.status_code == 201, media.text
        asset_id = media.json()["asset"]["id"]
        publication = test_client.post(
            f"/api/v1/publishing/projects/{project_id}/publications",
            headers=_headers(token),
            json={
                "platform": "youtube",
                "title": "Worker confirmation test",
                "description": "A test description",
                "media_asset_id": asset_id,
                "status": "ready",
            },
        )
        assert publication.status_code == 201, publication.text
        queued = test_client.post(
            f"/api/v1/publishing/youtube/publications/{publication.json()['id']}/uploads",
            headers=_headers(token),
            json={"connection_id": connection["id"], "privacy_status": "private"},
        )
        assert queued.status_code == 202, queued.text

        deadline = time.monotonic() + 8
        result = queued.json()
        while result["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.1)
            response = test_client.get(
                f"/api/v1/publishing/youtube/uploads/{queued.json()['id']}",
                headers=_headers(token),
            )
            result = response.json()
        assert result["status"] == "completed", result
        assert result["output_data"]["youtube_video_id"] == "video-confirmed-123"
        reloaded = test_client.get(
            f"/api/v1/publishing/projects/{project_id}/publications",
            headers=_headers(token),
        ).json()[0]
        assert reloaded["external_id"] == "video-confirmed-123"
        assert reloaded["youtube_status"] == "uploaded"
        assert reloaded["youtube_url"] == "https://www.youtube.com/watch?v=video-confirmed-123"

        async def fail_upload(_client, **_kwargs):
            raise FileNotFoundError("/private/media/library/video.mp4")

        monkeypatch.setattr(YouTubeApiClient, "upload_video", fail_upload)
        retry_publication = test_client.post(
            f"/api/v1/publishing/projects/{project_id}/publications",
            headers=_headers(token),
            json={
                "platform": "youtube",
                "title": "Missing local media test",
                "media_asset_id": asset_id,
                "status": "ready",
            },
        )
        failed_job = test_client.post(
            f"/api/v1/publishing/youtube/publications/{retry_publication.json()['id']}/uploads",
            headers=_headers(token),
            json={"connection_id": connection["id"], "privacy_status": "private"},
        )
        deadline = time.monotonic() + 8
        result = failed_job.json()
        while result["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.1)
            result = test_client.get(
                f"/api/v1/publishing/youtube/uploads/{failed_job.json()['id']}",
                headers=_headers(token),
            ).json()
        assert result["status"] == "failed"
        assert "/private/media/library/video.mp4" not in result["error_message"]
        assert "local video or thumbnail file" in result["error_message"]

        monkeypatch.undo()

        def revoked_handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL(GOOGLE_TOKEN_URL):
                body = parse_qs(request.content.decode())
                if body.get("grant_type") == ["refresh_token"]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
            return _provider_handler(request)

        youtube_client.transport = httpx.MockTransport(revoked_handler)
        revoked_publication = test_client.post(
            f"/api/v1/publishing/projects/{project_id}/publications",
            headers=_headers(token),
            json={
                "platform": "youtube",
                "title": "Revoked authorization test",
                "media_asset_id": asset_id,
                "status": "ready",
            },
        )
        revoked_job = test_client.post(
            f"/api/v1/publishing/youtube/publications/{revoked_publication.json()['id']}/uploads",
            headers=_headers(token),
            json={"connection_id": connection["id"], "privacy_status": "private"},
        )
        deadline = time.monotonic() + 8
        result = revoked_job.json()
        while result["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.1)
            result = test_client.get(
                f"/api/v1/publishing/youtube/uploads/{revoked_job.json()['id']}",
                headers=_headers(token),
            ).json()
        refreshed_connection = test_client.get(
            "/api/v1/publishing/youtube/connections",
            headers=_headers(token),
        ).json()[0]
        assert result["status"] == "failed"
        assert refreshed_connection["status"] == "reauthorization_required"
