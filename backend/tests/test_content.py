"""Content Studio project, character, scene, provider, and continuity tests."""

import asyncio
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.models.media_asset import MediaAsset
from app.schemas.content import SceneProviderRequest, SceneWorkerJobStatus
from app.services.content_providers import (
    MockSceneGenerationProvider,
    SelfHostedHTTPSceneGenerationProvider,
)


class RetryOncePreviewProvider:
    name = "retry-once-preview"
    preview_only = True

    def __init__(self) -> None:
        self.attempts = 0

    async def submit_scene(self, job_id: str, request: SceneProviderRequest) -> str:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("Temporary worker startup failure.")
        return job_id

    async def get_job_status(self, worker_job_id: str) -> SceneWorkerJobStatus:
        return SceneWorkerJobStatus(
            status="completed",
            progress=100,
            preview_only=True,
            preview_label="MOCK GENERATED PREVIEW ONLY — retry test.",
        )

    async def cancel_job(self, worker_job_id: str) -> None:
        return None

    async def download_output(self, worker_job_id: str):
        if False:
            yield b""
        raise RuntimeError("Preview provider has no video output.")


class CancellablePreviewProvider:
    name = "cancellable-preview"
    preview_only = True

    def __init__(self) -> None:
        self.cancelled: set[str] = set()

    async def submit_scene(self, job_id: str, request: SceneProviderRequest) -> str:
        return job_id

    async def get_job_status(self, worker_job_id: str) -> SceneWorkerJobStatus:
        if worker_job_id in self.cancelled:
            return SceneWorkerJobStatus(status="cancelled", progress=0)
        return SceneWorkerJobStatus(status="processing", progress=42)

    async def cancel_job(self, worker_job_id: str) -> None:
        self.cancelled.add(worker_job_id)

    async def download_output(self, worker_job_id: str):
        if False:
            yield b""
        raise RuntimeError("Preview provider has no video output.")


class GeneratedVideoProvider:
    name = "test-gpu-worker"
    preview_only = False

    def __init__(self, video_bytes: bytes) -> None:
        self.video_bytes = video_bytes

    async def submit_scene(self, job_id: str, request: SceneProviderRequest) -> str:
        return job_id

    async def get_job_status(self, worker_job_id: str) -> SceneWorkerJobStatus:
        return SceneWorkerJobStatus(
            status="completed",
            progress=100,
            output_available=True,
            output_metadata={"model_version": "test-version-1"},
        )

    async def cancel_job(self, worker_job_id: str) -> None:
        return None

    async def download_output(self, worker_job_id: str):
        yield self.video_bytes


def register_and_login(client: TestClient, email: str) -> str:
    password = "correct-horse-battery-41"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Content Tester"},
    )
    assert response.status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def create_project(client: TestClient, token: str, name: str = "Film project") -> dict:
    response = client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def wait_for_scene_job(client: TestClient, token: str, job_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(100):
        response = client.get(f"/api/v1/content/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"Scene job {job_id} did not finish in time.")


def test_story_character_environment_and_scene_data_persist(client: TestClient) -> None:
    token = register_and_login(client, "content-owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = create_project(client, token)
    project_id = project["id"]

    story = client.put(
        f"/api/v1/projects/{project_id}/content",
        headers=headers,
        json={
            "story_idea": "A botanist helps a neighborhood garden survive winter.",
            "story_outline": "Beginning: the frost arrives.\nMiddle: neighbors cooperate.\nEnd: spring.",
            "script_text": "The first frost arrived before sunrise.",
            "visual_settings": {
                "visual_style": "documentary",
                "camera_movement": "handheld",
                "lighting": "soft natural light",
                "color_palette": "muted green and amber",
            },
        },
    )
    assert story.status_code == 200, story.text
    assert story.json()["visual_settings"]["visual_style"] == "documentary"
    assert client.get(f"/api/v1/projects/{project_id}/content", headers=headers).json()[
        "script_text"
    ] == ("The first frost arrived before sunrise.")

    character_response = client.post(
        f"/api/v1/projects/{project_id}/characters",
        headers=headers,
        json={
            "name": "Mara",
            "identity_description": "Adult botanist with dark curly hair.",
            "outfit_settings": {"default": "olive coat", "winter": "red scarf"},
            "visual_traits": {"hair": "dark curly"},
        },
    )
    assert character_response.status_code == 201, character_response.text
    character = character_response.json()
    assert (
        client.patch(
            f"/api/v1/projects/{project_id}/characters/{character['id']}",
            headers=headers,
            json={"outfit_settings": {"default": "olive coat", "winter": "red scarf"}},
        ).status_code
        == 200
    )

    environment_response = client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=headers,
        json={
            "name": "Community garden",
            "description": "Raised beds beside a brick greenhouse.",
            "visual_traits": {"season": "late winter", "weather": "frost"},
        },
    )
    assert environment_response.status_code == 201, environment_response.text
    environment = environment_response.json()

    first_scene = client.post(
        f"/api/v1/projects/{project_id}/scenes",
        headers=headers,
        json={
            "title": "The frost",
            "description": "Mara discovers the garden after a cold night.",
            "scene_prompt": "Wide documentary shot of the frosted raised beds at dawn.",
            "visual_style": "documentary",
            "camera_movement": "tracking",
            "environment_id": environment["id"],
            "character_ids": [character["id"]],
            "order_index": 0,
            "duration_seconds": 9,
        },
    )
    assert first_scene.status_code == 201, first_scene.text
    scene = first_scene.json()
    assert scene["character_ids"] == [character["id"]]
    assert scene["generation_status"] == "not_started"

    shot_response = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene['id']}/shots",
        headers=headers,
        json={
            "description": "Mara studies frost on the leaves.",
            "shot_prompt": "Close-up, frost melting in the first sunlight.",
            "order_index": 0,
            "duration_seconds": 4,
            "camera_movement": "dolly_in",
        },
    )
    assert shot_response.status_code == 201, shot_response.text
    assert shot_response.json()["shot_prompt"].startswith("Close-up")
    assert (
        client.get(f"/api/v1/projects/{project_id}/scenes", headers=headers).json()[0]["shots"][0][
            "id"
        ]
        == (shot_response.json()["id"])
    )

    invalid_style = client.put(
        f"/api/v1/projects/{project_id}/content",
        headers=headers,
        json={"visual_settings": {"visual_style": "unspecified-style"}},
    )
    assert invalid_style.status_code == 422


def test_scene_generation_is_queued_per_scene_and_preview_only(client: TestClient) -> None:
    token = register_and_login(client, "content-generation@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = create_project(client, token)
    project_id = project["id"]
    client.app.state.scene_generation_provider = MockSceneGenerationProvider()
    scenes = []
    for order, title in enumerate(("Scene one", "Scene five")):
        response = client.post(
            f"/api/v1/projects/{project_id}/scenes",
            headers=headers,
            json={
                "title": title,
                "scene_prompt": f"Distinct prompt for {title}.",
                "order_index": order * 4,
                "visual_style": "cinematic",
                "camera_movement": "dolly_in",
                "lighting": "golden hour",
            },
        )
        assert response.status_code == 201, response.text
        scenes.append(response.json())

    provider_status = client.get(
        f"/api/v1/projects/{project_id}/scene-provider",
        headers=headers,
    )
    assert provider_status.status_code == 200
    assert provider_status.json() == {
        "available": True,
        "provider": "mock-preview",
        "preview_only": True,
        "self_hosted_worker_supported": True,
    }

    queued = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scenes[1]['id']}/generate",
        headers=headers,
    )
    assert queued.status_code == 202, queued.text
    job = wait_for_scene_job(client, token, queued.json()["id"])
    assert job["status"] == "completed", job
    assert job["output_data"]["preview_only"] is True
    assert "MOCK GENERATED PREVIEW ONLY" in job["output_data"]["generated_preview_label"]

    current_scenes = {
        scene["id"]: scene
        for scene in client.get(f"/api/v1/projects/{project_id}/scenes", headers=headers).json()
    }
    assert current_scenes[scenes[0]["id"]]["generation_status"] == "not_started"
    regenerated_scene = current_scenes[scenes[1]["id"]]
    assert regenerated_scene["generation_status"] == "preview_generated"
    assert regenerated_scene["generated_media_asset_id"] is None
    assert "No image or video was generated." in regenerated_scene["generated_preview_label"]

    regeneration = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scenes[1]['id']}/generate",
        headers=headers,
    )
    assert regeneration.status_code == 202
    second_job = wait_for_scene_job(client, token, regeneration.json()["id"])
    assert second_job["status"] == "completed"
    after_regeneration = client.get(
        f"/api/v1/projects/{project_id}/scenes",
        headers=headers,
    ).json()
    assert len(after_regeneration) == 2
    assert after_regeneration[0]["id"] == scenes[0]["id"]

    approved = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scenes[1]['id']}/approval",
        headers=headers,
        json={"is_approved": True},
    )
    assert approved.status_code == 409
    assert "real uploaded video asset" in approved.json()["error"]["message"]
    assembly = client.post(f"/api/v1/projects/{project_id}/storyboard/assemble", headers=headers)
    assert assembly.status_code == 409
    assert "Preview-only" in assembly.json()["error"]["message"]


def test_content_routes_are_owner_scoped_and_provider_unavailable_is_explicit(
    client: TestClient,
) -> None:
    owner_token = register_and_login(client, "content-private@example.com")
    other_token = register_and_login(client, "content-other@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}
    project = create_project(client, owner_token, "Private project")
    scene = client.post(
        f"/api/v1/projects/{project['id']}/scenes",
        headers=owner_headers,
        json={"title": "Private scene", "scene_prompt": "A private prompt."},
    ).json()

    assert (
        client.get(f"/api/v1/projects/{project['id']}/scenes", headers=other_headers).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/projects/{project['id']}/scene-provider",
            headers=other_headers,
        ).status_code
        == 404
    )
    unavailable = client.post(
        f"/api/v1/projects/{project['id']}/scenes/{scene['id']}/generate",
        headers=owner_headers,
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "scene_generation_provider_unavailable"

    invalid_character = client.post(
        f"/api/v1/projects/{project['id']}/scenes",
        headers=owner_headers,
        json={"title": "Bad scene", "character_ids": ["b15be515-ff31-4e16-bc12-f116e469505c"]},
    )
    assert invalid_character.status_code == 404


def test_real_project_video_asset_can_be_approved_and_assembled(client: TestClient) -> None:
    token = register_and_login(client, "content-assembly@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = create_project(client, token)
    project_id = project["id"]
    user = client.get("/api/v1/auth/me", headers=headers)
    assert user.status_code == 200
    asset_id = uuid4()
    asset = MediaAsset(
        id=asset_id,
        owner_id=UUID(user.json()["id"]),
        project_id=UUID(project_id),
        name="Uploaded scene footage",
        storage_key=f"test/{asset_id}.mp4",
        media_type="video",
        content_type="video/mp4",
        file_size=100,
    )

    async def save_asset() -> None:
        async with client.app.state.session_factory() as session:
            session.add(asset)
            await session.commit()

    asyncio.run(save_asset())
    scene_response = client.post(
        f"/api/v1/projects/{project_id}/scenes",
        headers=headers,
        json={"title": "Opening", "scene_prompt": "A wide shot of the city at dawn."},
    )
    assert scene_response.status_code == 201, scene_response.text
    scene_id = scene_response.json()["id"]
    shot_response = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_id}/shots",
        headers=headers,
        json={"description": "Establishing shot", "media_asset_id": str(asset_id)},
    )
    assert shot_response.status_code == 201, shot_response.text

    approved = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_id}/approval",
        headers=headers,
        json={"is_approved": True},
    )
    assert approved.status_code == 200, approved.text
    assembled = client.post(
        f"/api/v1/projects/{project_id}/storyboard/assemble",
        headers=headers,
    )
    assert assembled.status_code == 200, assembled.text
    assert assembled.json()["video_asset_count"] == 1


def test_model_registry_and_signed_image_to_video_reference(client: TestClient) -> None:
    token = register_and_login(client, "content-reference@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = create_project(client, token)
    project_id = project["id"]
    registry = client.get("/api/v1/content/models", headers=headers)
    assert registry.status_code == 200
    operator_model = next(item for item in registry.json() if item["id"] == "operator-configured")
    assert operator_model["commercial_use_permitted"] is False
    assert "manual" in operator_model["installation_instructions"]

    user = client.get("/api/v1/auth/me", headers=headers).json()
    asset_id = uuid4()
    storage_key = f"users/{user['id']}/references/{asset_id}.png"
    asset = MediaAsset(
        id=asset_id,
        owner_id=UUID(user["id"]),
        project_id=UUID(project_id),
        name="First frame reference",
        storage_key=storage_key,
        media_type="image",
        content_type="image/png",
        file_size=13,
    )

    async def save_reference() -> None:
        async def chunks():
            yield b"safe-reference"

        await client.app.state.storage.save_stream(storage_key, chunks())
        async with client.app.state.session_factory() as session:
            session.add(asset)
            await session.commit()

    asyncio.run(save_reference())
    scene = client.post(
        f"/api/v1/projects/{project_id}/scenes",
        headers=headers,
        json={
            "title": "Image guided scene",
            "scene_prompt": "Animate the reference frame gently.",
            "first_frame_asset_id": str(asset_id),
        },
    )
    assert scene.status_code == 201, scene.text
    provider = MockSceneGenerationProvider()
    client.app.state.scene_generation_provider = provider
    queued = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene.json()['id']}/generate",
        headers=headers,
        json={"generation_mode": "image_to_video"},
    )
    assert queued.status_code == 202, queued.text
    completed = wait_for_scene_job(client, token, queued.json()["id"])
    references = provider.requests[queued.json()["id"]].reference_assets
    first_frame = next(item for item in references if item.role == "first_frame")
    assert first_frame.asset_id == asset_id
    parsed_url = urlsplit(first_frame.download_url)
    downloaded = client.get(f"{parsed_url.path}?{parsed_url.query}")
    assert downloaded.status_code == 200
    assert downloaded.content == b"safe-reference"
    assert completed["generation_mode"] == "image_to_video"


def test_scene_job_retry_and_worker_cancellation(client: TestClient) -> None:
    token = register_and_login(client, "content-retry-cancel@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = create_project(client, token)
    project_id = project["id"]
    scene = client.post(
        f"/api/v1/projects/{project_id}/scenes",
        headers=headers,
        json={"title": "Retry scene", "scene_prompt": "A test scene."},
    ).json()

    retry_provider = RetryOncePreviewProvider()
    client.app.state.scene_generation_provider = retry_provider
    queued = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene['id']}/generate",
        headers=headers,
    )
    assert queued.status_code == 202, queued.text
    failed = wait_for_scene_job(client, token, queued.json()["id"])
    assert failed["status"] == "failed"
    retried = client.post(
        f"/api/v1/content/jobs/{failed['id']}/retry",
        headers=headers,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["retry_count"] == 1
    assert wait_for_scene_job(client, token, failed["id"])["status"] == "completed"

    scene2 = client.post(
        f"/api/v1/projects/{project_id}/scenes",
        headers=headers,
        json={"title": "Cancellable scene", "scene_prompt": "Wait and cancel."},
    ).json()
    cancellable_provider = CancellablePreviewProvider()
    client.app.state.scene_generation_provider = cancellable_provider
    queued2 = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene2['id']}/generate",
        headers=headers,
    )
    assert queued2.status_code == 202, queued2.text
    for _ in range(100):
        state = client.get(f"/api/v1/content/jobs/{queued2.json()['id']}", headers=headers).json()
        if state["status"] == "processing":
            break
        time.sleep(0.05)
    assert state["status"] == "processing"
    cancellation = client.post(
        f"/api/v1/content/jobs/{queued2.json()['id']}/cancel",
        headers=headers,
    )
    assert cancellation.status_code == 200, cancellation.text
    assert cancellation.json()["cancellation_requested"] is True
    cancelled = wait_for_scene_job(client, token, queued2.json()["id"])
    assert cancelled["status"] == "cancelled"


def test_generated_clip_is_stored_and_attached_to_scene(
    client: TestClient,
    tmp_path: Path,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        import pytest

        pytest.skip("FFmpeg is required to validate the GPU worker's output video.")
    sample_path = tmp_path / "generated.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=160x90:d=1",
            "-c:v",
            "mpeg4",
            "-y",
            str(sample_path),
        ],
        check=True,
        capture_output=True,
    )
    token = register_and_login(client, "content-generated-video@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = create_project(client, token)
    scene = client.post(
        f"/api/v1/projects/{project['id']}/scenes",
        headers=headers,
        json={"title": "Generated clip", "scene_prompt": "A generated video scene."},
    ).json()
    client.app.state.scene_generation_provider = GeneratedVideoProvider(sample_path.read_bytes())
    queued = client.post(
        f"/api/v1/projects/{project['id']}/scenes/{scene['id']}/generate",
        headers=headers,
        json={"settings": {"resolution": "160x90"}},
    )
    assert queued.status_code == 202, queued.text
    completed = wait_for_scene_job(client, token, queued.json()["id"])
    assert completed["status"] == "completed", completed
    media_asset_id = completed["output_data"]["media_asset_id"]
    assert media_asset_id
    assert completed["model_version"] == "test-version-1"
    scene_after = client.get(
        f"/api/v1/projects/{project['id']}/scenes",
        headers=headers,
    ).json()[0]
    assert scene_after["generated_media_asset_id"] == media_asset_id
    media_response = client.get(f"/api/v1/media/{media_asset_id}", headers=headers)
    assert media_response.status_code == 200
    stored_path = client.app.state.storage.path_for(
        f"users/{client.get('/api/v1/auth/me', headers=headers).json()['id']}"
        f"/projects/{project['id']}/generated/{queued.json()['id']}.mp4"
    )
    assert stored_path.is_file()


def test_self_hosted_worker_http_adapter_contract() -> None:
    import httpx

    async def verify_adapter() -> None:
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path))
            if request.method == "POST" and request.url.path == "/api/v1/jobs":
                return httpx.Response(202, json={"job_id": "remote-job-1"})
            if request.url.path == "/api/v1/jobs/remote-job-1":
                return httpx.Response(
                    200,
                    json={"status": "processing", "progress": 37, "output_metadata": {}},
                )
            if request.method == "POST" and request.url.path.endswith("/cancel"):
                return httpx.Response(202, json={"status": "cancelled"})
            if request.url.path.endswith("/output"):
                return httpx.Response(200, content=b"video", headers={"content-type": "video/mp4"})
            return httpx.Response(404)

        provider = SelfHostedHTTPSceneGenerationProvider(
            base_url="http://gpu-worker.local",
            api_token="worker-secret",
            transport=httpx.MockTransport(handler),
        )
        request = SceneProviderRequest(
            project_id=uuid4(),
            scene_id=uuid4(),
            title="Adapter test",
            prompt="A scene prompt.",
            character_ids=[],
            model_name="Test model",
            model_license="Test license",
        )
        remote_id = await provider.submit_scene("local-job-1", request)
        assert remote_id == "remote-job-1"
        status = await provider.get_job_status(remote_id)
        assert status.status == "processing"
        await provider.cancel_job(remote_id)
        chunks = [chunk async for chunk in provider.download_output(remote_id)]
        assert chunks == [b"video"]
        assert ("POST", "/api/v1/jobs") in seen
        assert ("GET", "/api/v1/jobs/remote-job-1") in seen

    asyncio.run(verify_adapter())
