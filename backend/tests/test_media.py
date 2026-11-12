"""Media upload, ownership, and FFmpeg processing tests."""

import errno
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.storage import LocalStorage


def register_and_login(client: TestClient, email: str) -> str:
    password = "correct-horse-battery-41"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Media Tester"},
    )
    assert response.status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture
def sample_video(tmp_path: Path) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is required to generate sample test media.")
    sample_path = tmp_path / "tiny.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=160x90:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(sample_path),
        ],
        check=True,
        capture_output=True,
    )
    return sample_path.read_bytes()


def wait_for_job(client: TestClient, token: str, job_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(100):
        response = client.get(f"/api/v1/media/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"Media job {job_id} did not finish in time.")


def test_upload_runs_ffmpeg_derivatives_and_owner_scoped_management(
    client: TestClient,
    sample_video: bytes,
) -> None:
    owner_token = register_and_login(client, "media-owner@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    upload = client.post(
        "/api/v1/media",
        headers=owner_headers,
        files={"file": ("../../unsafe.mp4", sample_video, "video/mp4")},
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    asset = body["asset"]
    job_id = body["job_id"]
    asset_id = asset["id"]
    assert asset["name"] == "unsafe.mp4"
    assert asset["media_type"] == "video"
    assert asset["file_size"] == len(sample_video)

    job = wait_for_job(client, owner_token, job_id)
    assert job["status"] == "completed", job
    assert job["progress"] == 100

    retrieved = client.get(f"/api/v1/media/{asset_id}", headers=owner_headers)
    assert retrieved.status_code == 200
    saved_asset = retrieved.json()
    assert saved_asset["duration_seconds"] == pytest.approx(1, abs=0.1)
    assert saved_asset["metadata_json"]["probe"]["width"] == 160
    assert saved_asset["metadata_json"]["probe"]["height"] == 90
    assert saved_asset["metadata_json"]["probe"]["frame_rate"] == pytest.approx(25)
    assert saved_asset["metadata_json"]["probe"]["video_codec"] == "mpeg4"
    assert saved_asset["metadata_json"]["probe"]["audio_streams"][0]["codec"] == "aac"
    assert set(saved_asset["metadata_json"]["derivatives"]) == {
        "thumbnail",
        "proxy",
        "extracted_audio",
        "waveform",
    }

    for derivative in ("thumbnail", "proxy", "extracted_audio", "waveform"):
        response = client.get(
            f"/api/v1/media/{asset_id}/derivatives/{derivative}",
            headers=owner_headers,
        )
        assert response.status_code == 200
        assert len(response.content) > 0

    original = client.get(f"/api/v1/media/{asset_id}/download", headers=owner_headers)
    assert original.status_code == 200
    assert original.content == sample_video
    assert [
        item["id"]
        for item in client.get("/api/v1/media?media_type=video", headers=owner_headers).json()
    ] == [asset_id]
    assert client.get("/api/v1/media?media_type=audio", headers=owner_headers).json() == []

    other_token = register_and_login(client, "media-other@example.com")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert client.get(f"/api/v1/media/{asset_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/media/jobs/{job_id}", headers=other_headers).status_code == 404
    assert client.delete(f"/api/v1/media/{asset_id}", headers=other_headers).status_code == 404
    assert client.get("/api/v1/media", headers=other_headers).json() == []

    storage: LocalStorage = client.app.state.storage
    assert len([path for path in storage.root.rglob("*") if path.is_file()]) == 5
    deleted = client.delete(f"/api/v1/media/{asset_id}", headers=owner_headers)
    assert deleted.status_code == 204
    assert not [path for path in storage.root.rglob("*") if path.is_file()]
    assert client.get(f"/api/v1/media/{asset_id}", headers=owner_headers).status_code == 404


def test_audio_waveform_and_image_thumbnail_processing(client: TestClient, tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is required to generate sample test media.")
    audio_path = tmp_path / "tone.wav"
    image_path = tmp_path / "frame.png"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=cyan:s=64x64:d=0.1",
            "-frames:v",
            "1",
            "-y",
            str(image_path),
        ],
        check=True,
        capture_output=True,
    )
    token = register_and_login(client, "audio-image@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    audio_response = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("tone.wav", audio_path.read_bytes(), "audio/wav")},
    )
    image_response = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("frame.png", image_path.read_bytes(), "image/png")},
    )
    assert audio_response.status_code == 201
    assert image_response.status_code == 201

    audio_job = wait_for_job(client, token, audio_response.json()["job_id"])
    image_job = wait_for_job(client, token, image_response.json()["job_id"])
    assert audio_job["status"] == "completed", audio_job
    assert image_job["status"] == "completed", image_job

    audio_asset = client.get(
        f"/api/v1/media/{audio_response.json()['asset']['id']}",
        headers=headers,
    ).json()
    image_asset = client.get(
        f"/api/v1/media/{image_response.json()['asset']['id']}",
        headers=headers,
    ).json()
    assert set(audio_asset["metadata_json"]["derivatives"]) == {"waveform"}
    assert set(image_asset["metadata_json"]["derivatives"]) == {"thumbnail"}


def test_upload_rejects_mime_extension_and_signature_mismatches(client: TestClient) -> None:
    token = register_and_login(client, "media-validation@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    unsupported = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("payload.exe", b"not media", "application/octet-stream")},
    )
    wrong_mime = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("payload.mp4", b"\x00\x00\x00\x18ftypisom", "image/jpeg")},
    )
    wrong_signature = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("payload.mp4", b"not an mp4 file", "video/mp4")},
    )

    assert unsupported.status_code == 415
    assert wrong_mime.status_code == 415
    assert wrong_signature.status_code == 415
    assert client.get("/api/v1/media", headers=headers).json() == []
    assert not [path for path in client.app.state.storage.root.rglob("*") if path.is_file()]


def test_upload_requires_owned_project(client: TestClient, sample_video: bytes) -> None:
    project_owner = register_and_login(client, "media-project-owner@example.com")
    project = client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {project_owner}"},
        json={"name": "Private project"},
    )
    uploader = register_and_login(client, "media-project-uploader@example.com")
    response = client.post(
        "/api/v1/media",
        headers={"Authorization": f"Bearer {uploader}"},
        params={"project_id": project.json()["id"]},
        files={"file": ("sample.mp4", sample_video, "video/mp4")},
    )

    assert response.status_code == 404
    assert client.app.state.storage.root.exists()
    assert not [path for path in client.app.state.storage.root.rglob("*") if path.is_file()]


def test_upload_limit_cleans_partial_storage(client: TestClient) -> None:
    token = register_and_login(client, "media-size@example.com")
    client.app.state.settings.max_upload_size_bytes = 16
    response = client.post(
        "/api/v1/media",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("tiny.png", b"\x89PNG\r\n\x1a\nmore-than-16-bytes", "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert not [path for path in client.app.state.storage.root.rglob("*") if path.is_file()]


def test_upload_reports_insufficient_disk_space(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_and_login(client, "media-disk-full@example.com")

    async def fail_for_full_disk(key, chunks):
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(client.app.state.storage, "save_stream", fail_for_full_disk)
    response = client.post(
        "/api/v1/media",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sample.mp4", b"\x00\x00\x00\x18ftypisom", "video/mp4")},
    )

    assert response.status_code == 507
    assert response.json()["error"]["code"] == "insufficient_storage"


def test_undecodable_upload_is_reported_as_failed_and_keeps_original(client: TestClient) -> None:
    token = register_and_login(client, "media-failure@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("broken.mp4", b"\x00\x00\x00\x18ftypisomnot-a-container", "video/mp4")},
    )
    assert response.status_code == 201
    upload = response.json()

    job = wait_for_job(client, token, upload["job_id"])
    assert job["status"] == "failed"
    assert job["progress"] < 100
    assert "invalid or uses an unsupported" in job["error_message"]
    assert len([path for path in client.app.state.storage.root.rglob("*") if path.is_file()]) == 1
    original = client.get(
        f"/api/v1/media/{upload['asset']['id']}/download",
        headers=headers,
    )
    assert original.status_code == 200


def test_media_job_retry_limit_and_owner_scoped_lifecycle(
    client: TestClient,
) -> None:
    token = register_and_login(client, "media-retry@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    upload = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("broken.mp4", b"\x00\x00\x00\x18ftypisombad", "video/mp4")},
    )
    assert upload.status_code == 201
    job_id = upload.json()["job_id"]
    assert wait_for_job(client, token, job_id)["status"] == "failed"

    other_token = register_and_login(client, "media-retry-other@example.com")
    assert (
        client.post(
            f"/api/v1/media/jobs/{job_id}/retry",
            headers={"Authorization": f"Bearer {other_token}"},
        ).status_code
        == 404
    )

    for expected_retry_count in (1, 2):
        retried = client.post(f"/api/v1/media/jobs/{job_id}/retry", headers=headers)
        assert retried.status_code == 200, retried.text
        assert retried.json()["status"] == "queued"
        assert retried.json()["retry_count"] == expected_retry_count
        assert wait_for_job(client, token, job_id)["status"] == "failed"

    exhausted = client.post(f"/api/v1/media/jobs/{job_id}/retry", headers=headers)
    assert exhausted.status_code == 409


def test_queued_media_job_can_be_cancelled(client: TestClient, sample_video: bytes) -> None:
    token = register_and_login(client, "media-cancel@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    upload = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("cancel.mp4", sample_video, "video/mp4")},
    )
    assert upload.status_code == 201
    job_id = upload.json()["job_id"]

    cancelled = client.post(f"/api/v1/media/jobs/{job_id}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    job = wait_for_job(client, token, job_id)
    assert job["status"] == "cancelled"
    assert job["cancellation_requested"] is True


def test_storage_rejects_traversal_and_absolute_keys(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "objects")
    for key in ("../outside.txt", "/etc/passwd", "user\\..\\outside.txt"):
        with pytest.raises(ValueError):
            storage.path_for(key)
