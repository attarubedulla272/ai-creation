"""Smart Clipper ranking, authorization, scene, transcript, and export tests."""

import asyncio
import json
import shutil
import subprocess
import time
from collections.abc import AsyncIterable
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.models.clip_candidate import ClipCandidate
from app.models.media_asset import MediaAsset
from app.models.project import Project
from app.models.transcript import Transcript, TranscriptSegment
from app.services.smart_clipper import (
    _render_candidate,
    align_transcript_to_scenes,
    build_candidate_windows,
    detect_scenes_sync,
    detect_silences,
    rank_transcript_window,
)


def register_and_login(client: TestClient, email: str) -> str:
    password = "correct-horse-battery-41"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Clipper Tester"},
    )
    assert response.status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def make_test_video(path: Path, duration: float = 5) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "FFmpeg is required for Smart Clipper integration tests."
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=12:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )


def test_ranking_and_transcript_scene_alignment_are_explainable() -> None:
    segments = [
        {
            "start_seconds": 4.0,
            "end_seconds": 18.0,
            "text": "Here's why this matters? The key lesson is that people can make a better choice.",
        }
    ]
    score, factors, explanation = rank_transcript_window(segments)
    assert 0 < score <= 100
    assert factors["interesting_opening"] == 1
    assert factors["question_or_answer"] == 1
    assert factors["key_insight"] == 1
    assert "configured opening phrase" in explanation
    aligned = align_transcript_to_scenes(segments, [(0, 7), (7, 24)])
    assert aligned[0]["scene_index"] == 1
    score, factors, explanation = rank_transcript_window(
        segments,
        clip_start=4,
        clip_end=18,
        scene_ranges=[(0, 7), (7, 24)],
        silence_ranges=[(3.5, 4.2), (17.7, 18.2)],
    )
    assert 0 < score <= 100
    assert factors["scene_changes"] == 0.5
    assert factors["silence_boundaries"] == 1
    assert factors["sentence_completeness"] == 1
    assert "scene change" in explanation
    assert factors["speech_activity"] == 1


def test_candidate_windows_keep_sentence_boundaries_and_support_scene_only() -> None:
    segments = [
        {"start_seconds": 0, "end_seconds": 8, "text": "The first complete sentence."},
        {"start_seconds": 8, "end_seconds": 16, "text": "The second complete sentence."},
        {"start_seconds": 16, "end_seconds": 24, "text": "The third complete sentence."},
    ]
    windows = build_candidate_windows(segments, [], [], 15, 30, 30, [15])
    assert windows
    for window, start, end in windows:
        assert end - start >= 15
        assert window[-1]["text"].endswith(".")

    scene_windows = build_candidate_windows(
        [], [(0, 10), (10, 20)], [(4, 5), (14, 15)], 3, 10, 20, [5]
    )
    assert scene_windows
    assert all(not window and 3 <= end - start <= 10 for window, start, end in scene_windows)


def test_ffmpeg_silencedetect_finds_real_silence_intervals(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "FFmpeg is required for silence-detection tests."
    audio = tmp_path / "speech-with-pause.wav"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-af",
            "volume=0:enable='between(t,1,1.6)'",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    ranges = asyncio.run(detect_silences(audio, 3))
    assert any(start <= 1.1 and end >= 1.5 for start, end in ranges)


def test_vertical_caption_render_has_requested_output_dimensions(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg and ffprobe, "FFmpeg and FFprobe are required for clip rendering tests."
    source = tmp_path / "black-source.mp4"
    output = tmp_path / "vertical-caption.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=12:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    candidate = ClipCandidate(
        start_seconds=0,
        end_seconds=1,
        caption_data=[
            {
                "start_seconds": 0.1,
                "end_seconds": 0.9,
                "text": "REAL CAPTION",
                "highlighted_words": [],
            }
        ],
    )
    asyncio.run(
        _render_candidate(
            source,
            output,
            candidate,
            {
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "captions": True,
                "caption_position": "bottom",
                "caption_theme": "boxed",
                "caption_font_size": 30,
                "caption_color": "#FFFFFF",
                "caption_background_color": "#000000",
                "caption_outline_color": "#000000",
            },
        )
    )
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    video_stream = next(stream for stream in streams if stream["codec_type"] == "video")
    assert (video_stream["width"], video_stream["height"]) == (720, 1280)
    assert any(
        stream["codec_type"] == "subtitle" and stream["codec_name"] == "mov_text"
        for stream in streams
    )
    frame = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-ss",
            "0.5",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-vf",
            "format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    assert sum(value > 220 for value in frame) > 100


def test_pyscenedetect_finds_real_cut_boundaries(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "FFmpeg is required for scene-detection tests."
    sample = tmp_path / "cuts.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=64x64:r=10:d=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            str(sample),
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    scenes = detect_scenes_sync(sample)
    assert len(scenes) >= 2
    assert scenes[0][0] == 0
    assert scenes[-1][1] > 3


def test_candidate_authorization_boundaries_ranking_and_caption_timing(
    client: TestClient,
) -> None:
    token = register_and_login(client, "clip-owner@example.com")
    outsider = register_and_login(client, "clip-outsider@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Clip project"},
    )
    assert project_response.status_code == 201
    project_id = UUID(project_response.json()["id"])
    owner_response = client.get("/api/v1/auth/me", headers=headers)
    owner_id = UUID(owner_response.json()["id"])
    asset_id = uuid4()
    candidate_id = uuid4()

    async def seed_records() -> None:
        async with client.app.state.session_factory() as session:
            session.add(
                MediaAsset(
                    id=asset_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    name="Interview.mp4",
                    storage_key=f"test/{asset_id}.mp4",
                    media_type="video",
                    content_type="video/mp4",
                    file_size=1024,
                    duration_seconds=60,
                )
            )
            session.add(
                ClipCandidate(
                    id=candidate_id,
                    project_id=project_id,
                    source_asset_id=asset_id,
                    start_seconds=10,
                    end_seconds=20,
                    score=60,
                    scoring_factors={"key_insight": 1.0, "pacing": 0.5},
                    transcript_text="The key insight is here.",
                    caption_data=[
                        {
                            "start_seconds": 10.5,
                            "end_seconds": 12,
                            "text": "The key insight is here.",
                            "highlighted_words": ["insight"],
                        }
                    ],
                    status="candidate",
                )
            )
            await session.commit()

    asyncio.run(seed_records())
    candidate_url = f"/api/v1/clipper/candidates/{candidate_id}"
    assert (
        client.get(candidate_url, headers={"Authorization": f"Bearer {outsider}"}).status_code
        == 404
    )
    edited = client.patch(
        candidate_url,
        headers=headers,
        json={"start_seconds": 11, "end_seconds": 19},
    )
    assert edited.status_code == 200
    invalid = client.patch(
        candidate_url,
        headers=headers,
        json={"start_seconds": 12, "end_seconds": 61},
    )
    assert invalid.status_code == 422
    invalid_caption = client.patch(
        f"{candidate_url}/captions",
        headers=headers,
        json={"captions": [{"start_seconds": 10, "end_seconds": 13, "text": "Outside clip"}]},
    )
    assert invalid_caption.status_code == 422
    captions = client.get(f"{candidate_url}/captions?format=srt", headers=headers)
    assert captions.status_code == 200
    assert "00:00:00,000 --> 00:00:01,000" in captions.text
    ranked = client.patch(
        f"/api/v1/clipper/projects/{project_id}/ranking",
        headers=headers,
        json={"preferences": {"key_insight": 3, "pacing": 0}},
    )
    assert ranked.status_code == 200
    assert ranked.json()[0]["score"] >= 0
    approved = client.post(f"{candidate_url}/approve", headers=headers)
    assert approved.status_code == 200


def test_analysis_and_ffmpeg_batch_export_use_saved_transcript(
    client: TestClient,
    tmp_path: Path,
) -> None:
    token = register_and_login(client, "clip-export@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Shorts project"},
    )
    project_id = UUID(project_response.json()["id"])
    user_response = client.get("/api/v1/auth/me", headers=headers)
    owner_id = UUID(user_response.json()["id"])
    source_path = tmp_path / "source.mp4"
    make_test_video(source_path)
    asset_id = uuid4()
    storage_key = f"users/{owner_id}/projects/{project_id}/{asset_id}.mp4"

    async def save_source() -> None:
        async def chunks() -> AsyncIterable[bytes]:
            yield await asyncio.to_thread(source_path.read_bytes)

        await client.app.state.storage.save_stream(storage_key, chunks())
        async with client.app.state.session_factory() as session:
            project = await session.get(Project, project_id)
            assert project is not None
            asset = MediaAsset(
                id=asset_id,
                owner_id=owner_id,
                project_id=project_id,
                name="Source interview.mp4",
                storage_key=storage_key,
                media_type="video",
                content_type="video/mp4",
                file_size=source_path.stat().st_size,
                duration_seconds=5,
            )
            transcript = Transcript(
                project_id=project_id,
                media_asset_id=asset_id,
                language="en",
                status="completed",
            )
            transcript.segments = [
                TranscriptSegment(
                    order_index=0,
                    start_seconds=0.1,
                    end_seconds=4.8,
                    text="Here's why small changes matter. The key is to begin with one simple step.",
                    speaker_label="Speaker A",
                )
            ]
            session.add_all([asset, transcript])
            await session.commit()

    asyncio.run(save_source())
    analysis = client.post(
        "/api/v1/clipper/analyses",
        headers=headers,
        json={
            "project_id": str(project_id),
            "source_media_asset_id": str(asset_id),
            "minimum_duration_seconds": 3,
            "maximum_duration_seconds": 5,
        },
    )
    assert analysis.status_code == 202, analysis.text
    analysis_job_id = analysis.json()["id"]
    for _ in range(300):
        state = client.get(f"/api/v1/clipper/analyses/{analysis_job_id}", headers=headers).json()
        if state["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    assert state["status"] == "completed", state
    assert state["output_data"]["transcript_provider"] == "reused transcript"
    candidates_response = client.get(
        f"/api/v1/clipper/projects/{project_id}/candidates",
        headers=headers,
    )
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["scoring_factors"]["interesting_opening"] == 1
    assert candidate["caption_data"][0]["speaker_label"] == "Speaker A"
    candidate_id = candidate["id"]
    assert (
        client.post(
            f"/api/v1/clipper/candidates/{candidate_id}/approve",
            headers=headers,
        ).status_code
        == 200
    )
    animated_captions = client.post(
        "/api/v1/clipper/exports",
        headers=headers,
        json={
            "candidate_ids": [candidate_id],
            "captions": True,
            "animated_highlighting": True,
        },
    )
    assert animated_captions.status_code == 422
    assert "word-level timestamps" in animated_captions.json()["error"]["message"]
    export = client.post(
        "/api/v1/clipper/exports",
        headers=headers,
        json={
            "candidate_ids": [candidate_id],
            "aspect_ratio": "1:1",
            "resolution": "720p",
            "captions": True,
            "caption_font_size": 30,
            "caption_position": "bottom",
            "watermark": "TEST",
        },
    )
    assert export.status_code == 202, export.text
    export_id = export.json()["id"]
    for _ in range(300):
        export_state = client.get(f"/api/v1/clipper/jobs/{export_id}", headers=headers).json()
        if export_state["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    assert export_state["status"] == "completed", export_state
    assert export_state["progress"] == 100
    exported_asset_id = export_state["output_data"]["media_asset_ids"][0]
    download = client.get(f"/api/v1/media/{exported_asset_id}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"


def test_scene_analysis_continues_without_transcription_or_fabricated_captions(
    client: TestClient,
    tmp_path: Path,
) -> None:
    client.app.state.voice_providers.transcription = None
    token = register_and_login(client, "clip-no-transcription@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Scene-only analysis"},
    )
    project_id = UUID(project.json()["id"])
    owner_id = UUID(client.get("/api/v1/auth/me", headers=headers).json()["id"])
    source_path = tmp_path / "source-without-transcript.mp4"
    make_test_video(source_path)
    asset_id = uuid4()
    storage_key = f"users/{owner_id}/projects/{project_id}/{asset_id}.mp4"

    async def seed_source() -> None:
        async def chunks() -> AsyncIterable[bytes]:
            yield await asyncio.to_thread(source_path.read_bytes)

        await client.app.state.storage.save_stream(storage_key, chunks())
        async with client.app.state.session_factory() as session:
            session.add(
                MediaAsset(
                    id=asset_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    name="Scene-only.mp4",
                    storage_key=storage_key,
                    media_type="video",
                    content_type="video/mp4",
                    file_size=source_path.stat().st_size,
                    duration_seconds=5,
                )
            )
            await session.commit()

    asyncio.run(seed_source())
    response = client.post(
        "/api/v1/clipper/analyses",
        headers=headers,
        json={
            "project_id": str(project_id),
            "source_media_asset_id": str(asset_id),
            "minimum_duration_seconds": 3,
            "maximum_duration_seconds": 5,
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    for _ in range(300):
        state = client.get(f"/api/v1/clipper/analyses/{job_id}", headers=headers).json()
        if state["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    assert state["status"] == "completed", state
    assert state["output_data"]["transcript_provider"] == "unavailable"
    assert state["output_data"]["analysis_mode"] == "scene_and_silence"
    assert state["output_data"]["word_timestamps_available"] is False
    candidates = client.get(
        f"/api/v1/clipper/projects/{project_id}/candidates",
        headers=headers,
    ).json()
    assert len(candidates) == 1
    assert candidates[0]["transcript_text"] is None
    assert candidates[0]["caption_data"] is None
    assert candidates[0]["scene_ranges"]
    assert "scene_changes" in candidates[0]["scoring_factors"]
    assert "Heuristic" in candidates[0]["explanation"]
    candidate_id = candidates[0]["id"]
    assert (
        client.post(
            f"/api/v1/clipper/candidates/{candidate_id}/approve",
            headers=headers,
        ).status_code
        == 200
    )
    captions_without_transcript = client.post(
        "/api/v1/clipper/exports",
        headers=headers,
        json={"candidate_ids": [candidate_id], "captions": True},
    )
    assert captions_without_transcript.status_code == 409
    assert "no transcript timing" in captions_without_transcript.json()["error"]["message"]


def test_export_failure_retry_and_queued_cancellation(client: TestClient) -> None:
    token = register_and_login(client, "clip-job-controls@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Job control project"},
    )
    project_id = UUID(project_response.json()["id"])
    owner_id = UUID(client.get("/api/v1/auth/me", headers=headers).json()["id"])
    asset_id = uuid4()
    candidate_id = uuid4()

    async def seed_records() -> None:
        async with client.app.state.session_factory() as session:
            session.add_all(
                [
                    MediaAsset(
                        id=asset_id,
                        owner_id=owner_id,
                        project_id=project_id,
                        name="Missing file.mp4",
                        storage_key=f"missing/{asset_id}.mp4",
                        media_type="video",
                        content_type="video/mp4",
                        file_size=20,
                        duration_seconds=10,
                    ),
                    ClipCandidate(
                        id=candidate_id,
                        project_id=project_id,
                        source_asset_id=asset_id,
                        start_seconds=1,
                        end_seconds=5,
                        status="approved",
                        caption_data=[],
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed_records())
    base_payload = {
        "candidate_ids": [str(candidate_id)],
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "captions": False,
    }
    cancelled = client.post("/api/v1/clipper/exports", headers=headers, json=base_payload)
    assert cancelled.status_code == 202
    cancelled_job = client.post(
        f"/api/v1/clipper/jobs/{cancelled.json()['id']}/cancel",
        headers=headers,
    )
    assert cancelled_job.status_code == 200
    assert cancelled_job.json()["status"] == "cancelled"

    failed = client.post("/api/v1/clipper/exports", headers=headers, json=base_payload)
    assert failed.status_code == 202
    failed_id = failed.json()["id"]
    for _ in range(100):
        state = client.get(f"/api/v1/clipper/jobs/{failed_id}", headers=headers).json()
        if state["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    assert state["status"] == "failed"
    assert state["error_message"]
    retried = client.post(f"/api/v1/clipper/jobs/{failed_id}/retry", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["retry_count"] == 1
    cancelled_retry = client.post(
        f"/api/v1/clipper/jobs/{failed_id}/cancel",
        headers=headers,
    )
    assert cancelled_retry.status_code == 200
    assert cancelled_retry.json()["status"] in {"cancelled", "processing"}
