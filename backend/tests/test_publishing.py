"""Persistent SEO metadata, calendar, thumbnail, and authorization workflows."""

import asyncio
import io
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from PIL import Image

from app.models.media_asset import MediaAsset

PASSWORD = "correct-horse-battery-41"


def _account(client: TestClient, email: str) -> tuple[str, str]:
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
    return response.json()["access_token"], registered.json()["id"]


def _project(client: TestClient, token: str, name: str = "Publish project") -> str:
    response = client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _publication_payload(**overrides: object) -> dict[str, object]:
    return {
        "platform": "youtube",
        "title": "A test title",
        "description": "A locally saved release package.",
        "tags": ["education", "creative tools"],
        "hashtags": ["#learning"],
        "primary_keywords": ["creator workflow"],
        "secondary_keywords": ["local editing"],
        "chapters": [
            {"timestamp_seconds": 0, "title": "Introduction"},
            {"timestamp_seconds": 45, "title": "Workflow"},
        ],
        "language": "en",
        "category": "Education",
        "status": "draft",
        **overrides,
    }


def test_publication_metadata_revision_history_and_reload(client: TestClient) -> None:
    token, _ = _account(client, "publishing-owner@example.com")
    project_id = _project(client, token)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/publishing/projects/{project_id}/publications",
        headers=headers,
        json=_publication_payload(),
    )
    assert created.status_code == 201, created.text
    publication = created.json()
    assert publication["version"] == 1
    assert publication["metadata_json"]["tags"] == ["education", "creative tools"]
    assert publication["status"] == "draft"

    updated = client.patch(
        f"/api/v1/publishing/publications/{publication['id']}",
        headers=headers,
        json={"title": "Revised title", "category": "How-to"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["metadata_json"]["category"] == "How-to"

    reloaded = client.get(
        f"/api/v1/publishing/projects/{project_id}/publications",
        headers=headers,
    )
    revisions = client.get(
        f"/api/v1/publishing/publications/{publication['id']}/revisions",
        headers=headers,
    )
    assert reloaded.status_code == 200
    assert reloaded.json()[0]["title"] == "Revised title"
    assert [item["version"] for item in revisions.json()] == [2, 1]
    assert revisions.json()[1]["snapshot"]["title"] == "A test title"


def test_metadata_limits_chapter_order_and_future_scheduling(client: TestClient) -> None:
    from datetime import UTC, datetime, timedelta

    token, _ = _account(client, "publishing-validation@example.com")
    project_id = _project(client, token)
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = f"/api/v1/publishing/projects/{project_id}/publications"

    too_long = client.post(endpoint, headers=headers, json=_publication_payload(title="x" * 101))
    too_many_tag_chars = client.post(
        endpoint,
        headers=headers,
        json=_publication_payload(tags=["a" * 250, "b" * 251]),
    )
    unordered = client.post(
        endpoint,
        headers=headers,
        json=_publication_payload(
            chapters=[
                {"timestamp_seconds": 45, "title": "Later"},
                {"timestamp_seconds": 0, "title": "Earlier"},
            ]
        ),
    )
    assert too_long.status_code == 422
    assert too_many_tag_chars.status_code == 422
    assert unordered.status_code == 422

    planned_at = datetime.now(UTC) + timedelta(days=1)
    scheduled = client.post(
        endpoint,
        headers=headers,
        json=_publication_payload(status="scheduled", scheduled_at=planned_at.isoformat()),
    )
    assert scheduled.status_code == 201, scheduled.text
    assert scheduled.json()["status"] == "scheduled"
    assert scheduled.json()["scheduled_at"].endswith("Z") or scheduled.json()[
        "scheduled_at"
    ].endswith("+00:00")
    assert "published_at" in scheduled.json() and scheduled.json()["published_at"] is None
    metadata_edit = client.patch(
        f"/api/v1/publishing/publications/{scheduled.json()['id']}",
        headers=headers,
        json={"description": "Revised schedule note."},
    )
    assert metadata_edit.status_code == 200, metadata_edit.text
    assert metadata_edit.json()["status"] == "scheduled"

    past = client.post(
        endpoint,
        headers=headers,
        json=_publication_payload(
            status="scheduled",
            scheduled_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        ),
    )
    no_timezone = client.post(
        endpoint,
        headers=headers,
        json=_publication_payload(status="scheduled", scheduled_at="2035-01-01T10:00:00"),
    )
    assert past.status_code == 422
    assert no_timezone.status_code == 422

    calendar = client.get("/api/v1/publishing/calendar", headers=headers)
    assert calendar.status_code == 200
    assert [item["id"] for item in calendar.json()] == [scheduled.json()["id"]]

    readied = client.patch(
        f"/api/v1/publishing/publications/{scheduled.json()['id']}",
        headers=headers,
        json={"status": "ready"},
    )
    assert readied.status_code == 200
    assert readied.json()["status"] == "ready"
    assert readied.json()["scheduled_at"] is None


def test_publication_and_history_are_owner_scoped(client: TestClient) -> None:
    owner_token, _ = _account(client, "publishing-private@example.com")
    other_token, _ = _account(client, "publishing-other@example.com")
    owner_project = _project(client, owner_token)
    other_project = _project(client, other_token, "Other project")
    created = client.post(
        f"/api/v1/publishing/projects/{owner_project}/publications",
        headers={"Authorization": f"Bearer {owner_token}"},
        json=_publication_payload(),
    )
    assert created.status_code == 201
    publication_id = created.json()["id"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    hidden = client.get(
        f"/api/v1/publishing/projects/{owner_project}/publications",
        headers=other_headers,
    )
    hidden_revisions = client.get(
        f"/api/v1/publishing/publications/{publication_id}/revisions",
        headers=other_headers,
    )
    hidden_update = client.patch(
        f"/api/v1/publishing/publications/{publication_id}",
        headers=other_headers,
        json={"title": "Unauthorized edit"},
    )
    invalid_project = client.post(
        f"/api/v1/publishing/projects/{owner_project}/publications",
        headers=other_headers,
        json=_publication_payload(),
    )
    assert hidden.status_code == 404
    assert hidden_revisions.status_code == 404
    assert hidden_update.status_code == 404
    assert invalid_project.status_code == 404
    assert (
        client.get(
            f"/api/v1/publishing/projects/{other_project}/publications",
            headers=other_headers,
        ).json()
        == []
    )


def test_local_thumbnail_render_is_stored_and_owner_scoped(client: TestClient) -> None:
    token, owner_id = _account(client, "thumbnail-owner@example.com")
    other_token, _ = _account(client, "thumbnail-other@example.com")
    project_id = _project(client, token)
    asset_id = uuid4()
    storage_key = f"{owner_id}/{asset_id}.png"
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), color=(26, 36, 58)).save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    async def insert_source() -> None:
        async def chunks():
            yield image_bytes

        await client.app.state.storage.save_stream(storage_key, chunks())
        async with client.app.state.session_factory() as session:
            session.add(
                MediaAsset(
                    id=asset_id,
                    owner_id=UUID(owner_id),
                    project_id=UUID(project_id),
                    name="source.png",
                    storage_key=storage_key,
                    media_type="image",
                    content_type="image/png",
                    file_size=len(image_bytes),
                    metadata_json={},
                )
            )
            await session.commit()

    asyncio.run(insert_source())
    response = client.post(
        f"/api/v1/publishing/projects/{project_id}/thumbnails",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source_asset_id": str(asset_id),
            "title": "Locally rendered title",
            "aspect_ratio": "16:9",
            "text_position": "bottom",
            "font_size": 48,
            "text_color": "#FFFFFF",
            "crop_x": 0.5,
            "crop_y": 0.5,
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert (result["width"], result["height"]) == (1280, 720)

    download = client.get(
        f"/api/v1/media/{result['asset_id']}/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert download.status_code == 200
    with Image.open(io.BytesIO(download.content)) as rendered:
        assert rendered.size == (1280, 720)
        assert rendered.format == "PNG"

    unauthorized = client.post(
        f"/api/v1/publishing/projects/{project_id}/thumbnails",
        headers={"Authorization": f"Bearer {other_token}"},
        json={
            "source_asset_id": str(asset_id),
            "title": "Should not render",
        },
    )
    assert unauthorized.status_code == 404


def test_external_capabilities_never_claim_unconfigured_publish_or_analytics(
    client: TestClient,
) -> None:
    token, _ = _account(client, "publishing-capabilities@example.com")
    response = client.get(
        "/api/v1/publishing/capabilities",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["youtube"]["available"] is False
    assert response.json()["analytics"]["available"] is False


def test_title_ideas_are_local_templates_without_performance_claims(client: TestClient) -> None:
    response = client.post(
        "/api/v1/publishing/title-suggestions",
        json={"topic": "Plan a short documentary", "keywords": ["documentary"]},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["method"] == "local_templates"
    assert len(result["suggestions"]) == 3
    assert all(len(title) <= 100 for title in result["suggestions"])
