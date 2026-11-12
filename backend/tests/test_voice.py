"""Voice Studio consent, owner isolation, transcript, and export tests."""

import asyncio
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.services.voice_providers import (
    TranscriptionResult,
    TranscriptWordSegment,
    TranslationResult,
)


def register_and_login(client: TestClient, email: str) -> str:
    password = "correct-horse-battery-41"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Voice Tester"},
    )
    assert response.status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture
def sample_audio(tmp_path: Path) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is required for voice audio tests.")
    sample_path = tmp_path / "short-speech.wav"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(sample_path),
        ],
        check=True,
        capture_output=True,
    )
    return sample_path.read_bytes()


@pytest.fixture
def sample_video(tmp_path: Path) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is required for voice video export tests.")
    sample_path = tmp_path / "source-video.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=24:d=0.5",
            "-an",
            "-c:v",
            "mpeg4",
            "-y",
            str(sample_path),
        ],
        check=True,
        capture_output=True,
    )
    return sample_path.read_bytes()


def upload_audio(client: TestClient, token: str, sample_audio: bytes) -> str:
    response = client.post(
        "/api/v1/media",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("voice-reference.wav", sample_audio, "audio/wav")},
    )
    assert response.status_code == 201, response.text
    uploaded = response.json()
    wait_for_media_job(client, token, uploaded["job_id"])
    return uploaded["asset"]["id"]


def upload_video(
    client: TestClient,
    token: str,
    project_id: str,
    sample_video: bytes,
) -> str:
    response = client.post(
        f"/api/v1/media?project_id={project_id}",
        headers={"Authorization": "Bearer " + token},
        files={"file": ("source-video.mp4", sample_video, "video/mp4")},
    )
    assert response.status_code == 201, response.text
    uploaded = response.json()
    wait_for_media_job(client, token, uploaded["job_id"])
    return uploaded["asset"]["id"]


def wait_for_media_job(client: TestClient, token: str, job_id: str) -> dict:
    headers = {"Authorization": "Bearer " + token}
    for _ in range(100):
        response = client.get(f"/api/v1/media/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed"}:
            assert job["status"] == "completed", job
            return job
        time.sleep(0.1)
    raise AssertionError(f"Media processing job {job_id} did not finish in time.")


def wait_for_voice_job(client: TestClient, token: str, job_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(100):
        response = client.get(f"/api/v1/voice/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"Voice job {job_id} did not finish in time.")


class FakeTranscriber:
    name = "test-transcriber"

    async def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        assert audio_path.is_file()
        return TranscriptionResult(
            language=language or "en",
            segments=[TranscriptWordSegment(0.0, 0.8, "A real saved test transcript.")],
            metrics={"inference_seconds": 0.125, "chunk_count": 1},
        )


class FailingTranscriber:
    name = "test-failing-transcriber"

    async def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        raise RuntimeError("Test transcription failure.")


class SlowTranscriber:
    name = "test-slow-transcriber"

    async def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        await asyncio.sleep(30)
        return TranscriptionResult(language=language or "en", segments=[])


class LanguageTranscriber:
    name = "test-language-transcriber"

    def __init__(self, language: str) -> None:
        self.language = language

    async def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        assert audio_path.is_file()
        return TranscriptionResult(
            language=self.language,
            segments=[
                TranscriptWordSegment(1.25, 2.75, "A complete source sentence."),
                TranscriptWordSegment(3.0, 4.0, "A second source sentence."),
            ],
        )


class FakeTranslationProvider:
    name = "test-translation-provider"
    supported_languages: tuple[str, ...] = ()

    def __init__(self, *, fail_first: bool = False, delay_seconds: float = 0) -> None:
        self.fail_first = fail_first
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[str, str | None, str, list[dict[str, str]]]] = []
        self.started = threading.Event()

    async def translate(
        self,
        text: str,
        source_language: str | None,
        target_language: str,
        glossary: list[dict[str, str]],
    ) -> TranslationResult:
        self.calls.append((text, source_language, target_language, glossary))
        self.started.set()
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("Translation worker unavailable.")
        return TranslationResult(
            text=f"{target_language}: translated sentence.",
            provider=self.name,
            model="ai4bharat/indictrans2-test",
            model_version="test-snapshot",
            model_license="MIT",
        )


def create_dubbing_plan_for_translation(
    client: TestClient,
    sample_audio: bytes,
    *,
    email: str,
    source_language: str,
    target_language: str,
) -> tuple[str, str, dict]:
    token = register_and_login(client, email)
    headers = {"Authorization": "Bearer " + token}
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Translation test project"},
    ).json()
    media_asset_id = upload_audio(client, token, sample_audio)
    client.app.state.voice_providers.transcription = LanguageTranscriber(source_language)
    transcription = client.post(
        "/api/v1/voice/transcriptions",
        headers=headers,
        json={"project_id": project["id"], "media_asset_id": media_asset_id},
    )
    assert transcription.status_code == 202, transcription.text
    transcribed_job = wait_for_voice_job(client, token, transcription.json()["id"])
    assert transcribed_job["status"] == "completed", transcribed_job
    created = client.post(
        "/api/v1/voice/dubbing-projects",
        headers=headers,
        json={
            "transcript_id": transcribed_job["output_data"]["transcript_id"],
            "target_language": target_language,
        },
    )
    assert created.status_code == 201, created.text
    return token, created.json()["id"], created.json()


def test_transcription_is_queued_saved_editable_and_exported(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token = register_and_login(client, "voice-transcription@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Voice test project"},
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    asset_id = upload_audio(client, token, sample_audio)
    client.app.state.voice_providers.transcription = FakeTranscriber()

    queued = client.post(
        "/api/v1/voice/transcriptions",
        headers=headers,
        json={"project_id": project_id, "media_asset_id": asset_id, "language": "en"},
    )
    assert queued.status_code == 202, queued.text
    job = wait_for_voice_job(client, token, queued.json()["id"])
    assert job["status"] == "completed", job
    assert job["output_data"]["provider"] == "test-transcriber"
    assert job["output_data"]["metrics"]["inference_seconds"] == 0.125
    assert job["output_data"]["elapsed_seconds"] >= 0

    transcript_id = job["output_data"]["transcript_id"]
    transcript_response = client.get(f"/api/v1/voice/transcripts/{transcript_id}", headers=headers)
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    segment = transcript["segments"][0]
    assert segment["text"] == "A real saved test transcript."
    assert segment["start_seconds"] == 0
    other_token = register_and_login(client, "voice-transcript-other@example.com")
    other_response = client.get(
        f"/api/v1/voice/transcripts/{transcript_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert other_response.status_code == 404

    updated = client.patch(
        f"/api/v1/voice/transcripts/{transcript_id}/segments/{segment['id']}",
        headers=headers,
        json={
            "text": "Edited transcript text.",
            "speaker_label": "Speaker 1",
            "translated_text": "Manual translation.",
        },
    )
    assert updated.status_code == 200, updated.text
    updated_segment = updated.json()["segments"][0]
    assert updated_segment["translated_text"] == "Manual translation."
    assert updated_segment["start_seconds"] == segment["start_seconds"]
    assert updated_segment["end_seconds"] == segment["end_seconds"]
    revisions = client.get(
        f"/api/v1/voice/transcripts/{transcript_id}/revisions",
        headers=headers,
    )
    assert revisions.status_code == 200
    assert len(revisions.json()) == 1
    snapshot_segment = revisions.json()[0]["snapshot"][0]
    assert snapshot_segment["text"] == "A real saved test transcript."
    assert snapshot_segment["start_seconds"] == segment["start_seconds"]
    assert snapshot_segment["end_seconds"] == segment["end_seconds"]
    subtitles = client.get(
        f"/api/v1/voice/transcripts/{transcript_id}/subtitles/vtt",
        headers=headers,
    )
    assert subtitles.status_code == 200
    assert subtitles.text.startswith("WEBVTT\n\n")
    assert "Edited transcript text." in subtitles.text


def test_voice_profiles_require_owned_reference_and_active_consent(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token = register_and_login(client, "voice-owner@example.com")
    other_token = register_and_login(client, "voice-other@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}
    asset_id = upload_audio(client, token, sample_audio)
    profile_payload = {
        "name": "Authorized voice",
        "language": "en",
        "consent_id": str(UUID(int=1)),
        "reference_asset_id": asset_id,
    }

    missing_consent = client.post("/api/v1/voice/profiles", headers=headers, json=profile_payload)
    assert missing_consent.status_code == 422

    consent_response = client.post(
        "/api/v1/voice/consents",
        headers=headers,
        json={
            "accepted": True,
            "authorization_basis": "self_attestation",
            "consent_text_version": "voice-consent-v1",
        },
    )
    assert consent_response.status_code == 201, consent_response.text
    profile_payload["consent_id"] = consent_response.json()["id"]
    profile_response = client.post("/api/v1/voice/profiles", headers=headers, json=profile_payload)
    assert profile_response.status_code == 201, profile_response.text
    assert profile_response.json()["status"] == "reference_only"

    foreign_asset = client.post(
        "/api/v1/voice/consents",
        headers=other_headers,
        json={
            "accepted": True,
            "authorization_basis": "authorized_person",
            "consent_text_version": "voice-consent-v1",
        },
    )
    assert foreign_asset.status_code == 201
    foreign_profile = client.post(
        "/api/v1/voice/profiles",
        headers=other_headers,
        json={**profile_payload, "consent_id": foreign_asset.json()["id"]},
    )
    assert foreign_profile.status_code == 404
    assert client.get("/api/v1/voice/profiles", headers=other_headers).json() == []

    revoked = client.post(
        f"/api/v1/voice/consents/{consent_response.json()['id']}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None
    assert client.get("/api/v1/voice/profiles", headers=headers).json() == []


def test_dubbing_plan_manual_subtitles_and_user_audio_assembly(
    client: TestClient,
    sample_audio: bytes,
    sample_video: bytes,
    tmp_path: Path,
) -> None:
    token = register_and_login(client, "voice-dubbing@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Dubbing test project"},
    )
    project_id = project_response.json()["id"]
    source_asset_id = upload_audio(client, token, sample_audio)
    source_video_asset_id = upload_video(client, token, project_id, sample_video)
    client.app.state.voice_providers.transcription = FakeTranscriber()
    transcription = client.post(
        "/api/v1/voice/transcriptions",
        headers=headers,
        json={"project_id": project_id, "media_asset_id": source_asset_id},
    )
    job = wait_for_voice_job(client, token, transcription.json()["id"])
    assert job["status"] == "completed", job
    transcript_id = job["output_data"]["transcript_id"]

    created = client.post(
        "/api/v1/voice/dubbing-projects",
        headers=headers,
        json={"transcript_id": transcript_id, "target_language": "hi"},
    )
    assert created.status_code == 201, created.text
    dubbing = created.json()
    segment = dubbing["segments_data"][0]
    invalid_translation_approval = client.patch(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}",
        headers=headers,
        json={"segments": [{"id": segment["id"], "translation_approved": True}]},
    )
    assert invalid_translation_approval.status_code == 422
    invalid_audio_approval = client.patch(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}",
        headers=headers,
        json={
            "segments": [
                {
                    "id": segment["id"],
                    "translated_text": "Manual test translation.",
                    "segment_approved": True,
                }
            ]
        },
    )
    assert invalid_audio_approval.status_code == 422
    regenerate = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}/segments/{segment['id']}/regenerate",
        headers=headers,
    )
    assert regenerate.status_code == 503
    assert regenerate.json()["error"]["code"] == "synthesis_provider_unavailable"
    incomplete_export = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}/export",
        headers=headers,
    )
    assert incomplete_export.status_code == 409
    updated = client.patch(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}",
        headers=headers,
        json={
            "segments": [
                {
                    "id": segment["id"],
                    "translated_text": "Manually translated audio.",
                    "audio_asset_id": source_asset_id,
                    "start_seconds": 0.05,
                    "end_seconds": 0.7,
                    "speech_rate": 1.1,
                }
            ],
            "glossary": [{"source": "Studio", "translation": "स्टूडियो", "notes": "Product name"}],
        },
    )
    assert updated.status_code == 200, updated.text
    updated_segment = updated.json()["segments_data"][0]
    assert updated_segment["audio_source"] == "user_supplied"
    assert updated_segment["audio_duration_seconds"] > 0
    assert updated_segment["timing_conflict"] is True
    assert updated.json()["glossary"] == [
        {"source": "Studio", "translation": "स्टूडियो", "notes": "Product name"}
    ]

    approved = client.patch(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}",
        headers=headers,
        json={
            "segments": [
                {
                    "id": segment["id"],
                    "translation_approved": True,
                    "segment_approved": True,
                }
            ]
        },
    )
    assert approved.status_code == 200, approved.text
    approved_segment = approved.json()["segments_data"][0]
    assert approved_segment["translation_approved"] is True
    assert approved_segment["segment_approved"] is True
    saved_approval = client.patch(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}",
        headers=headers,
        json={
            "segments": [
                {
                    "id": segment["id"],
                    "translated_text": approved_segment["translated_text"],
                    "audio_asset_id": approved_segment["audio_asset_id"],
                    "start_seconds": approved_segment["start_seconds"],
                    "end_seconds": approved_segment["end_seconds"],
                    "speech_rate": approved_segment["speech_rate"],
                    "translation_approved": approved_segment["translation_approved"],
                    "segment_approved": approved_segment["segment_approved"],
                }
            ],
            "glossary": approved.json()["glossary"],
        },
    )
    assert saved_approval.status_code == 200, saved_approval.text
    assert saved_approval.json()["segments_data"][0]["translation_approved"] is True
    assert saved_approval.json()["segments_data"][0]["segment_approved"] is True

    subtitles = client.get(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}/subtitles/srt",
        headers=headers,
    )
    assert subtitles.status_code == 200
    assert "Manually translated audio." in subtitles.text
    subtitle_end = subtitles.text.splitlines()[1].split(" --> ")[1]
    minutes, seconds = subtitle_end.split(":")[1:]
    subtitle_end_seconds = int(minutes) * 60 + float(seconds.replace(",", "."))
    expected_audio_end = (
        approved_segment["start_seconds"]
        + approved_segment["audio_duration_seconds"] / approved_segment["speech_rate"]
    )
    assert subtitle_end_seconds == pytest.approx(expected_audio_end, abs=0.001)
    assert subtitle_end_seconds > approved_segment["end_seconds"]

    export = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}/export",
        headers=headers,
        json={"source_video_asset_id": source_video_asset_id},
    )
    assert export.status_code == 202, export.text
    exported_job = wait_for_voice_job(client, token, export.json()["id"])
    assert exported_job["status"] == "completed", exported_job
    media_asset_id = exported_job["output_data"]["media_asset_id"]
    output = client.get(f"/api/v1/media/{media_asset_id}/download", headers=headers)
    assert output.status_code == 200
    assert output.content[:4] == b"\x00\x00\x00\x18" or b"ftyp" in output.content[:32]
    assert (
        client.get("/api/v1/voice/dubbing-projects", headers=headers).json()[0]["id"]
        == dubbing["id"]
    )
    other_token = register_and_login(client, "voice-dubbing-other@example.com")
    foreign_plan = client.get(
        f"/api/v1/voice/dubbing-projects/{dubbing['id']}",
        headers={"Authorization": "Bearer " + other_token},
    )
    assert foreign_plan.status_code == 404
    video_asset_id = exported_job["output_data"]["video_asset_id"]
    assert video_asset_id
    video_asset_response = client.get(
        f"/api/v1/media/{video_asset_id}",
        headers=headers,
    )
    assert video_asset_response.status_code == 200
    assert video_asset_response.json()["metadata_json"]["video_stream_copied"] is True
    video_download = client.get(
        f"/api/v1/media/{video_asset_id}/download",
        headers=headers,
    )
    assert video_download.status_code == 200
    exported_video = tmp_path / "dubbed-video.mp4"
    exported_video.write_bytes(video_download.content)
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("FFprobe is required to inspect the exported video streams.")
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,duration",
            "-of",
            "json",
            str(exported_video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    assert {stream["codec_type"] for stream in streams} == {"video", "audio"}
    video_stream = next(stream for stream in streams if stream["codec_type"] == "video")
    audio_stream = next(stream for stream in streams if stream["codec_type"] == "audio")
    assert video_stream["codec_name"] == "mpeg4"
    assert float(audio_stream["duration"]) >= expected_audio_end - 0.02


def test_expensive_features_report_unavailable_without_provider(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token = register_and_login(client, "voice-unavailable@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    client.app.state.voice_providers.transcription = None
    capabilities = client.get("/api/v1/voice/providers", headers=headers).json()
    assert capabilities["transcription"]["available"] is False
    project = client.post("/api/v1/projects", headers=headers, json={"name": "No provider"}).json()
    source = upload_audio(client, token, sample_audio)
    response = client.post(
        "/api/v1/voice/transcriptions",
        headers=headers,
        json={"project_id": project["id"], "media_asset_id": source},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "transcription_provider_unavailable"


def test_transcription_worker_marks_provider_failure_on_job(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token = register_and_login(client, "voice-failed-job@example.com")
    headers = {"Authorization": "Bearer " + token}
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Failed voice job"},
    ).json()
    media_asset_id = upload_audio(client, token, sample_audio)
    client.app.state.voice_providers.transcription = FailingTranscriber()
    queued = client.post(
        "/api/v1/voice/transcriptions",
        headers=headers,
        json={"project_id": project["id"], "media_asset_id": media_asset_id},
    )
    assert queued.status_code == 202, queued.text
    job = wait_for_voice_job(client, token, queued.json()["id"])
    assert job["status"] == "failed"
    assert (
        job["error_message"]
        == "Voice processing failed. Verify the input and installed local tools."
    )


def test_processing_transcription_can_be_cancelled(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token = register_and_login(client, "voice-cancel-job@example.com")
    headers = {"Authorization": "Bearer " + token}
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Cancelled voice job"},
    ).json()
    media_asset_id = upload_audio(client, token, sample_audio)
    client.app.state.voice_providers.transcription = SlowTranscriber()
    queued = client.post(
        "/api/v1/voice/transcriptions",
        headers=headers,
        json={"project_id": project["id"], "media_asset_id": media_asset_id},
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["id"]

    processing = None
    for _ in range(50):
        response = client.get(f"/api/v1/voice/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        processing = response.json()
        if processing["status"] == "processing":
            break
        time.sleep(0.02)
    assert processing is not None
    assert processing["status"] == "processing"

    cancelled = client.post(f"/api/v1/voice/jobs/{job_id}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    job = wait_for_voice_job(client, token, job_id)
    assert job["status"] == "cancelled"
    assert job["error_message"] == "Voice processing was cancelled."


@pytest.mark.parametrize(
    ("source_language", "target_language"),
    [("en", "hi"), ("en", "te"), ("hi", "en"), ("te", "en")],
)
def test_translation_job_persists_segment_provenance_and_timestamps(
    client: TestClient,
    sample_audio: bytes,
    source_language: str,
    target_language: str,
) -> None:
    email = f"translation-{source_language}-{target_language}@example.com"
    token, dubbing_id, plan = create_dubbing_plan_for_translation(
        client,
        sample_audio,
        email=email,
        source_language=source_language,
        target_language=target_language,
    )
    headers = {"Authorization": "Bearer " + token}
    provider = FakeTranslationProvider()
    client.app.state.voice_providers.translation = provider
    initial = plan["segments_data"][0]

    queued = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}/translate",
        headers=headers,
        json={"regenerate_existing": False},
    )
    assert queued.status_code == 202, queued.text
    job = wait_for_voice_job(client, token, queued.json()["id"])

    assert job["status"] == "completed", job
    assert job["output_data"]["completed_segment_ids"] == [
        segment["id"] for segment in plan["segments_data"]
    ]
    saved = client.get(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}",
        headers=headers,
    ).json()["segments_data"][0]
    assert saved["source_text"] == initial["source_text"]
    assert saved["start_seconds"] == initial["start_seconds"] == 1.25
    assert saved["end_seconds"] == initial["end_seconds"] == 2.75
    assert saved["translated_text"] == f"{target_language}: translated sentence."
    assert saved["translation_status"] == "completed"
    assert saved["translation_provider"] == "test-translation-provider"
    assert saved["translation_model"] == "ai4bharat/indictrans2-test"
    assert saved["translation_model_version"] == "test-snapshot"
    assert saved["translation_model_license"] == "MIT"
    assert saved["translation_approved"] is False
    assert provider.calls[0][1:3] == (source_language, target_language)

    manual = client.patch(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}",
        headers=headers,
        json={
            "segments": [
                {
                    "id": saved["id"],
                    "translated_text": "Creator-corrected translation.",
                }
            ]
        },
    )
    assert manual.status_code == 200, manual.text
    updated = manual.json()["segments_data"][0]
    assert updated["translated_text"] == "Creator-corrected translation."
    assert updated["translation_status"] == "manual"
    assert updated["translation_approved"] is False
    assert updated["translation_model"] is None


def test_failed_translation_retries_only_failed_segments(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token, dubbing_id, _ = create_dubbing_plan_for_translation(
        client,
        sample_audio,
        email="translation-retry@example.com",
        source_language="en",
        target_language="hi",
    )
    headers = {"Authorization": "Bearer " + token}
    provider = FakeTranslationProvider(fail_first=True)
    client.app.state.voice_providers.translation = provider
    queued = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}/translate",
        headers=headers,
        json={},
    )
    failed = wait_for_voice_job(client, token, queued.json()["id"])
    assert failed["status"] == "failed"
    project = client.get(f"/api/v1/voice/dubbing-projects/{dubbing_id}", headers=headers).json()
    assert project["segments_data"][0]["translation_status"] == "failed"
    assert project["segments_data"][0]["translation_error"]

    retry = client.post(f"/api/v1/voice/jobs/{failed['id']}/retry", headers=headers)
    assert retry.status_code == 200, retry.text
    completed = wait_for_voice_job(client, token, retry.json()["id"])
    assert completed["status"] == "completed", completed
    assert len(provider.calls) == 3
    assert retry.json()["retry_count"] == 1
    saved_segments = client.get(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}",
        headers=headers,
    ).json()["segments_data"]
    assert all(segment["translation_status"] == "completed" for segment in saved_segments)


def test_translation_queue_requires_worker_and_checks_ownership(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token, dubbing_id, _ = create_dubbing_plan_for_translation(
        client,
        sample_audio,
        email="translation-owner@example.com",
        source_language="en",
        target_language="hi",
    )
    queued_without_provider = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}/translate",
        headers={"Authorization": "Bearer " + token},
        json={},
    )
    assert queued_without_provider.status_code == 503

    other_token = register_and_login(client, "translation-other@example.com")
    client.app.state.voice_providers.translation = FakeTranslationProvider(delay_seconds=0.5)
    foreign_request = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}/translate",
        headers={"Authorization": "Bearer " + other_token},
        json={},
    )
    assert foreign_request.status_code == 404
    own_request = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}/translate",
        headers={"Authorization": "Bearer " + token},
        json={},
    )
    assert own_request.status_code == 202
    duplicate = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}/translate",
        headers={"Authorization": "Bearer " + token},
        json={},
    )
    assert duplicate.status_code == 409
    assert token
    assert other_token


def test_segment_translation_only_updates_selected_segment(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token, dubbing_id, plan = create_dubbing_plan_for_translation(
        client,
        sample_audio,
        email="translation-segment@example.com",
        source_language="en",
        target_language="te",
    )
    headers = {"Authorization": "Bearer " + token}
    provider = FakeTranslationProvider()
    client.app.state.voice_providers.translation = provider

    queued = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}/segments/{plan['segments_data'][0]['id']}/translate",
        headers=headers,
    )
    assert queued.status_code == 202, queued.text
    completed = wait_for_voice_job(client, token, queued.json()["id"])
    assert completed["status"] == "completed", completed
    saved = client.get(f"/api/v1/voice/dubbing-projects/{dubbing_id}", headers=headers).json()
    assert saved["segments_data"][0]["translation_status"] == "completed"
    assert saved["segments_data"][1]["translation_status"] == "not_translated"
    assert saved["segments_data"][1]["translated_text"] == ""


def test_translation_job_cancellation_updates_queued_segments(
    client: TestClient,
    sample_audio: bytes,
) -> None:
    token, dubbing_id, _ = create_dubbing_plan_for_translation(
        client,
        sample_audio,
        email="translation-cancel@example.com",
        source_language="en",
        target_language="hi",
    )
    headers = {"Authorization": "Bearer " + token}
    provider = FakeTranslationProvider(delay_seconds=30)
    client.app.state.voice_providers.translation = provider
    queued = client.post(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}/translate",
        headers=headers,
        json={},
    )
    assert queued.status_code == 202, queued.text
    assert provider.started.wait(timeout=2)

    cancelled = client.post(
        f"/api/v1/voice/jobs/{queued.json()['id']}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    completed = wait_for_voice_job(client, token, queued.json()["id"])
    assert completed["status"] == "cancelled"
    saved_segments = client.get(
        f"/api/v1/voice/dubbing-projects/{dubbing_id}",
        headers=headers,
    ).json()["segments_data"]
    assert all(segment["translation_status"] == "cancelled" for segment in saved_segments)
