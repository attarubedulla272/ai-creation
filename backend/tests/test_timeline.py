"""Timeline document persistence, ownership, and FFmpeg export tests."""

import json
import math
import shutil
import struct
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.schemas.timeline import TimelineTextStyleData, TimelineTrackData
from app.services.subtitle_io import export_subtitles, parse_subtitles
from app.services.timeline_export import _effect_filters, _render_subtitle_image


def _register(client: TestClient, email: str) -> str:
    password = "correct-horse-battery-41"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Timeline Tester"},
    )
    assert response.status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _make_media(tmp_path: Path) -> tuple[bytes, bytes]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is required for timeline export tests.")
    video_path = tmp_path / "source.mp4"
    audio_path = tmp_path / "bed.wav"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=1280x720:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=700:duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(video_path),
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
            "sine=frequency=440:duration=0.5",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
    )
    return video_path.read_bytes(), audio_path.read_bytes()


def _wait_for_job(client: TestClient, headers: dict[str, str], job_id: str) -> dict:
    for _ in range(300):
        response = client.get(f"/api/v1/timeline/exports/{job_id}", headers=headers)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"Timeline export {job_id} did not finish in time.")


def _wait_for_media_job(client: TestClient, headers: dict[str, str], job_id: str) -> dict:
    for _ in range(300):
        response = client.get(f"/api/v1/media/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"Media job {job_id} did not finish in time.")


def _ffmpeg_fixture(output_path: Path, inputs: Sequence[str]) -> None:
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            *inputs,
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )


def _rendered_frame(path: Path, time_seconds: float) -> bytes:
    result = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ss",
            str(time_seconds),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    assert len(result.stdout) == 160 * 90 * 3
    return result.stdout


def _rendered_scaled_frame(path: Path, time_seconds: float) -> bytes:
    result = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(time_seconds),
            "-i",
            str(path),
            "-vf",
            "scale=160:90",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    assert len(result.stdout) == 160 * 90 * 3
    return result.stdout


def _pixel(frame: bytes, x: int, y: int) -> tuple[int, int, int]:
    offset = (y * 160 + x) * 3
    return tuple(frame[offset : offset + 3])


def _channel_means(frame: bytes) -> tuple[float, float, float]:
    pixels = len(frame) // 3
    return tuple(sum(frame[index::3]) / pixels for index in range(3))


def _horizontal_luma_difference(frame: bytes) -> float:
    differences = [
        abs(
            (frame[index] + frame[index + 1] + frame[index + 2])
            - (frame[index + 3] + frame[index + 4] + frame[index + 5])
        )
        for row in range(90)
        for column in range(159)
        for index in [((row * 160 + column) * 3)]
    ]
    return sum(differences) / len(differences)


def _audio_rms(path: Path, time_seconds: float) -> float:
    result = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ss",
            str(time_seconds),
            "-t",
            "0.1",
            "-map",
            "0:a:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "8000",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    samples = struct.unpack(f"<{len(result.stdout) // 2}h", result.stdout)
    return math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))


def test_timeline_save_reload_owner_checks_and_ffmpeg_export(
    client: TestClient, tmp_path: Path
) -> None:
    video_bytes, audio_bytes = _make_media(tmp_path)
    token = _register(client, "timeline-owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project_response = client.post(
        "/api/v1/projects", headers=headers, json={"name": "Timeline test project"}
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    video_upload = client.post(
        "/api/v1/media", headers=headers, files={"file": ("source.mp4", video_bytes, "video/mp4")}
    )
    audio_upload = client.post(
        "/api/v1/media", headers=headers, files={"file": ("bed.wav", audio_bytes, "audio/wav")}
    )
    assert video_upload.status_code == 201
    assert audio_upload.status_code == 201
    assert (
        _wait_for_media_job(client, headers, video_upload.json()["job_id"])["status"] == "completed"
    )
    assert (
        _wait_for_media_job(client, headers, audio_upload.json()["job_id"])["status"] == "completed"
    )

    initial = client.get(f"/api/v1/projects/{project_id}/timeline", headers=headers)
    assert initial.status_code == 200
    document = initial.json()["timeline_data"]
    video_track = next(track for track in document["tracks"] if track["type"] == "video")
    audio_track = next(track for track in document["tracks"] if track["type"] == "audio")
    video_clip_id = "4564e258-24e4-4a77-bf77-e5517ad5b09f"
    document["tracks"][0]["clips"] = [
        {
            "id": video_clip_id,
            "media_asset_id": video_upload.json()["asset"]["id"],
            "start": 0.5,
            "duration": 0.48,
            "source_start": 0.25,
            "source_end": 0.73,
            "label": "Source video",
        },
        {
            "id": "54ea1264-9f31-47c7-8cb7-a7f512c83c59",
            "media_asset_id": video_upload.json()["asset"]["id"],
            "start": 4,
            "duration": 1,
            "source_start": 0,
            "source_end": 1,
            "label": "Second source segment",
        },
    ]
    video_track["clips"] = document["tracks"][0]["clips"]
    audio_track["clips"] = [
        {
            "id": "fac7f957-d0f8-45e8-92bf-4c4172cf9a0a",
            "media_asset_id": audio_upload.json()["asset"]["id"],
            "start": 0,
            "duration": 0.5,
            "source_start": 0,
            "source_end": 0.5,
            "label": "Audio bed",
        }
    ]
    saved = client.put(f"/api/v1/projects/{project_id}/timeline", headers=headers, json=document)
    assert saved.status_code == 200, saved.text
    reloaded = client.get(f"/api/v1/projects/{project_id}/timeline", headers=headers)
    assert reloaded.status_code == 200
    assert reloaded.json()["timeline_data"] == saved.json()["timeline_data"]
    assert reloaded.json()["duration_seconds"] == pytest.approx(5)
    persisted_clip = reloaded.json()["timeline_data"]["tracks"][0]["clips"][0]
    assert persisted_clip["start"] == pytest.approx(0.5)
    assert persisted_clip["duration"] == pytest.approx(0.48)
    assert persisted_clip["source_start"] == pytest.approx(0.25)
    assert persisted_clip["source_end"] == pytest.approx(0.73)

    other_token = _register(client, "timeline-other@example.com")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert (
        client.get(f"/api/v1/projects/{project_id}/timeline", headers=other_headers).status_code
        == 404
    )
    invalid = {
        **document,
        "tracks": [
            {
                **video_track,
                "clips": [
                    {
                        **video_track["clips"][0],
                        "media_asset_id": "00000000-0000-0000-0000-000000000001",
                    }
                ],
            }
        ],
    }
    rejected = client.put(f"/api/v1/projects/{project_id}/timeline", headers=headers, json=invalid)
    assert rejected.status_code == 422

    queued = client.post(
        f"/api/v1/projects/{project_id}/timeline/export",
        headers=headers,
        json={"selected_clip_ids": [video_clip_id], "preset": "720p"},
    )
    assert queued.status_code == 202, queued.text
    export = _wait_for_job(client, headers, queued.json()["job_id"])
    assert export["status"] == "completed", export
    assert export["progress"] == 100
    assert export["output_data"]["duration_seconds"] == pytest.approx(0.98)
    assert export["output_data"]["width"] == 1280
    assert export["output_data"]["height"] == 720
    assert export["output_data"]["preset"] == "720p"
    assert export["output_data"]["file_size_bytes"] > 0
    downloaded = client.get(f"/api/v1/timeline/exports/{export['id']}/download", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.content[4:8] == b"ftyp"
    output_path = tmp_path / "export.mp4"
    output_path.write_bytes(downloaded.content)
    dimensions = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert dimensions.stdout.strip() == "1280x720"
    ffprobe_output = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output_metadata = json.loads(ffprobe_output.stdout)
    assert float(output_metadata["format"]["duration"]) == pytest.approx(0.98, abs=0.2)
    assert any(
        stream["codec_type"] == "video"
        and stream["codec_name"] == "h264"
        and (stream["width"], stream["height"]) == (1280, 720)
        for stream in output_metadata["streams"]
    )
    assert max(_pixel(_rendered_scaled_frame(output_path, 0.25), 80, 45)) < 15
    rendered_trim = _pixel(_rendered_scaled_frame(output_path, 0.75), 80, 45)
    assert rendered_trim[0] > 45 and rendered_trim[2] > 45

    for preset in ("1080p", "4k"):
        too_large = client.post(
            f"/api/v1/projects/{project_id}/timeline/export",
            headers=headers,
            json={"selected_clip_ids": [video_clip_id], "preset": preset},
        )
        assert too_large.status_code == 422
        assert "requires source video" in too_large.json()["error"]["message"]

    cancelled_export = client.post(
        f"/api/v1/projects/{project_id}/timeline/export",
        headers=headers,
        json={"selected_clip_ids": [video_clip_id], "preset": "720p"},
    )
    assert cancelled_export.status_code == 202
    cancel_result = client.post(
        f"/api/v1/timeline/exports/{cancelled_export.json()['job_id']}/cancel",
        headers=headers,
    )
    assert cancel_result.status_code == 200
    assert cancel_result.json()["status"] == "cancelled"
    retry_result = client.post(
        f"/api/v1/timeline/exports/{cancelled_export.json()['job_id']}/retry",
        headers=headers,
    )
    assert retry_result.status_code == 200, retry_result.text
    assert retry_result.json()["retry_count"] == 1
    assert (
        _wait_for_job(client, headers, cancelled_export.json()["job_id"])["status"] == "completed"
    )
    assert (
        client.get(
            f"/api/v1/timeline/exports/{export['id']}/download", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/timeline/exports/{cancelled_export.json()['job_id']}/cancel",
            headers=other_headers,
        ).status_code
        == 404
    )


def test_4k_preset_renders_when_source_resolution_and_encoder_allow_it(
    client: TestClient,
    tmp_path: Path,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("FFmpeg and FFprobe are required for export tests.")
    source_path = tmp_path / "source-4k.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=3840x2160:r=1:d=2",
            "-c:v",
            "mpeg4",
            "-q:v",
            "10",
            "-an",
            "-y",
            str(source_path),
        ],
        check=True,
        capture_output=True,
    )
    token = _register(client, "timeline-4k@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "4K export"})
    upload = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("source.mp4", source_path.read_bytes(), "video/mp4")},
    )
    assert project.status_code == 201
    assert upload.status_code == 201
    assert _wait_for_media_job(client, headers, upload.json()["job_id"])["status"] == "completed"

    project_id = project.json()["id"]
    timeline = client.get(f"/api/v1/projects/{project_id}/timeline", headers=headers).json()[
        "timeline_data"
    ]
    video_track = next(track for track in timeline["tracks"] if track["type"] == "video")
    video_track["clips"] = [
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b09f",
            "media_asset_id": upload.json()["asset"]["id"],
            "start": 0,
            "duration": 2,
            "source_start": 0,
            "source_end": 2,
            "brightness": -0.3,
        }
    ]
    timeline["width"] = 3840
    timeline["height"] = 2160
    timeline["frame_rate"] = 1
    saved = client.put(
        f"/api/v1/projects/{project_id}/timeline",
        headers=headers,
        json=timeline,
    )
    assert saved.status_code == 200, saved.text

    queued = client.post(
        f"/api/v1/projects/{project_id}/timeline/export",
        headers=headers,
        json={"preset": "4k"},
    )
    assert queued.status_code == 202, queued.text
    exported = _wait_for_job(client, headers, queued.json()["job_id"])
    assert exported["status"] == "completed", exported
    download = client.get(
        f"/api/v1/timeline/exports/{exported['id']}/download",
        headers=headers,
    )
    assert download.status_code == 200
    rendered = tmp_path / "rendered-4k.mp4"
    rendered.write_bytes(download.content)
    dimensions = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(rendered),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert dimensions.stdout.strip() == "3840x2160"


def test_full_timeline_composites_tracks_gaps_transitions_overlays_subtitles_and_audio(
    client: TestClient,
    tmp_path: Path,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("FFmpeg and FFprobe are required for timeline rendering tests.")

    media_paths = {
        "red": tmp_path / "red.mp4",
        "blue": tmp_path / "blue.mp4",
        "green": tmp_path / "green.mp4",
        "watermark": tmp_path / "watermark.png",
        "audio_a": tmp_path / "audio-a.wav",
        "audio_b": tmp_path / "audio-b.wav",
    }
    for name, color, duration in (
        ("red", "red", 2),
        ("blue", "blue", 1),
        ("green", "green", 0.5),
    ):
        _ffmpeg_fixture(
            media_paths[name],
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=160x90:r=10:d={duration}",
                "-an",
                "-c:v",
                "mpeg4",
                "-y",
            ],
        )
    _ffmpeg_fixture(
        media_paths["watermark"],
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=yellow:s=32x18:r=1:d=1",
            "-frames:v",
            "1",
            "-y",
        ],
    )
    for name, frequency, duration in (("audio_a", 440, 1), ("audio_b", 880, 1.5)):
        _ffmpeg_fixture(
            media_paths[name],
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:duration={duration}",
                "-c:a",
                "pcm_s16le",
                "-y",
            ],
        )

    headers = {"Authorization": f"Bearer {_register(client, 'timeline-composite@example.com')}"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Composite render"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    uploaded: dict[str, dict] = {}
    mime_types = {
        ".mp4": "video/mp4",
        ".png": "image/png",
        ".wav": "audio/wav",
    }
    for name, path in media_paths.items():
        mime_type = mime_types[path.suffix]
        upload = client.post(
            "/api/v1/media",
            headers=headers,
            files={"file": (path.name, path.read_bytes(), mime_type)},
        )
        assert upload.status_code == 201, upload.text
        job = _wait_for_media_job(client, headers, upload.json()["job_id"])
        assert job["status"] == "completed", job
        uploaded[name] = upload.json()["asset"]

    timeline = client.get(f"/api/v1/projects/{project_id}/timeline", headers=headers).json()[
        "timeline_data"
    ]
    timeline.update({"width": 160, "height": 90, "frame_rate": 10})
    timeline["tracks"] = [
        {
            "id": "00000000-0000-4000-8000-000000000101",
            "name": "V1",
            "type": "video",
            "muted": False,
            "locked": False,
            "volume": 1,
            "clips": [
                {
                    "id": "00000000-0000-4000-8000-000000000201",
                    "media_asset_id": uploaded["red"]["id"],
                    "start": 0,
                    "duration": 2,
                    "source_start": 0,
                    "source_end": 2,
                    "brightness": -0.3,
                },
                {
                    "id": "00000000-0000-4000-8000-000000000202",
                    "media_asset_id": uploaded["blue"]["id"],
                    "start": 1,
                    "duration": 1,
                    "source_start": 0,
                    "source_end": 1,
                    "transition_in": "cross_dissolve",
                    "transition_in_version": 1,
                    "transition_in_duration": 0.5,
                    "keyframes": [
                        {"time": 0, "property": "opacity", "value": 0, "interpolation": "linear"},
                        {"time": 0.5, "property": "opacity", "value": 1, "interpolation": "linear"},
                    ],
                },
            ],
        },
        {
            "id": "00000000-0000-4000-8000-000000000102",
            "name": "V2",
            "type": "video",
            "muted": False,
            "locked": False,
            "volume": 1,
            "clips": [],
        },
        {
            "id": "00000000-0000-4000-8000-000000000103",
            "name": "V3",
            "type": "video",
            "muted": False,
            "locked": False,
            "volume": 1,
            "clips": [
                {
                    "id": "00000000-0000-4000-8000-000000000203",
                    "media_asset_id": uploaded["green"]["id"],
                    "start": 1.5,
                    "duration": 0.5,
                    "source_start": 0,
                    "source_end": 0.5,
                    "transition_in": "wipe_left",
                    "transition_in_duration": 0.25,
                }
            ],
        },
        {
            "id": "00000000-0000-4000-8000-000000000108",
            "name": "Wipe right",
            "type": "video",
            "muted": False,
            "locked": False,
            "volume": 1,
            "clips": [
                {
                    "id": "00000000-0000-4000-8000-000000000208",
                    "media_asset_id": uploaded["green"]["id"],
                    "start": 2,
                    "duration": 0.5,
                    "source_start": 0,
                    "source_end": 0.5,
                    "transition_in": "wipe_right",
                    "transition_in_duration": 0.25,
                }
            ],
        },
        {
            "id": "00000000-0000-4000-8000-000000000104",
            "name": "Watermark",
            "type": "overlay",
            "muted": False,
            "locked": False,
            "volume": 1,
            "clips": [
                {
                    "id": "00000000-0000-4000-8000-000000000204",
                    "media_asset_id": uploaded["watermark"]["id"],
                    "start": 0.5,
                    "duration": 1,
                    "source_start": 0,
                    "source_end": None,
                    "position_x": 0.1,
                    "position_y": 0.1,
                    "opacity": 0.9,
                    "scale": 1,
                    "keyframes": [
                        {"time": 0, "property": "x", "value": 0.1, "interpolation": "linear"},
                        {"time": 0.4, "property": "x", "value": 0.1, "interpolation": "linear"},
                        {"time": 1, "property": "x", "value": 0.7, "interpolation": "linear"},
                        {"time": 0, "property": "scale", "value": 1, "interpolation": "linear"},
                        {"time": 1, "property": "scale", "value": 1.5, "interpolation": "linear"},
                    ],
                }
            ],
        },
        {
            "id": "00000000-0000-4000-8000-000000000105",
            "name": "A1",
            "type": "audio",
            "muted": False,
            "locked": False,
            "volume": 1,
            "clips": [
                {
                    "id": "00000000-0000-4000-8000-000000000205",
                    "media_asset_id": uploaded["audio_a"]["id"],
                    "start": 0,
                    "duration": 1,
                    "source_start": 0,
                    "source_end": 1,
                    "fade_in": 0.4,
                    "keyframes": [
                        {"time": 0, "property": "volume", "value": 1, "interpolation": "linear"},
                        {"time": 1, "property": "volume", "value": 0, "interpolation": "linear"},
                    ],
                }
            ],
        },
        {
            "id": "00000000-0000-4000-8000-000000000106",
            "name": "A2",
            "type": "audio",
            "muted": False,
            "locked": False,
            "volume": 0.7,
            "clips": [
                {
                    "id": "00000000-0000-4000-8000-000000000206",
                    "media_asset_id": uploaded["audio_b"]["id"],
                    "start": 1.5,
                    "duration": 1.5,
                    "source_start": 0,
                    "source_end": 1.5,
                    "fade_out": 0.3,
                }
            ],
        },
        {
            "id": "00000000-0000-4000-8000-000000000107",
            "name": "Subtitles",
            "type": "subtitle",
            "muted": False,
            "locked": False,
            "volume": 1,
            "clips": [
                {
                    "id": "00000000-0000-4000-8000-000000000207",
                    "media_asset_id": None,
                    "start": 0.1,
                    "duration": 0.8,
                    "source_start": 0,
                    "source_end": None,
                    "text": "RENDERED",
                    "position_y": 0.88,
                    "text_style": {"font_size": 18},
                }
            ],
        },
    ]
    saved = client.put(
        f"/api/v1/projects/{project_id}/timeline",
        headers=headers,
        json=timeline,
    )
    assert saved.status_code == 200, saved.text

    queued = client.post(
        f"/api/v1/projects/{project_id}/timeline/export",
        headers=headers,
        json={},
    )
    assert queued.status_code == 202, queued.text
    export = _wait_for_job(client, headers, queued.json()["job_id"])
    assert export["status"] == "completed", export
    downloaded = client.get(f"/api/v1/timeline/exports/{export['id']}/download", headers=headers)
    assert downloaded.status_code == 200
    output_path = tmp_path / "composited.mp4"
    output_path.write_bytes(downloaded.content)

    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(probe.stdout)
    assert float(metadata["format"]["duration"]) == pytest.approx(3, abs=0.2)
    assert any(
        stream["codec_type"] == "video" and (stream["width"], stream["height"]) == (160, 90)
        for stream in metadata["streams"]
    )
    assert any(stream["codec_type"] == "audio" for stream in metadata["streams"])

    image_frame = _rendered_frame(output_path, 0.75)
    image_pixel = _pixel(image_frame, 20, 15)
    assert image_pixel[0] > 170 and image_pixel[1] > 170
    moving_image_frame = _rendered_frame(output_path, 1.4)
    moving_image_pixel = _pixel(moving_image_frame, 90, 15)
    assert moving_image_pixel[0] > 170 and moving_image_pixel[1] > 170
    color_adjusted_pixel = _pixel(_rendered_frame(output_path, 0.25), 80, 45)
    assert color_adjusted_pixel[0] < 190
    dissolve_frame = _rendered_frame(output_path, 1.2)
    dissolve_pixel = _pixel(dissolve_frame, 80, 45)
    assert dissolve_pixel[0] > 100 and dissolve_pixel[2] > 20
    wipe_frame = _rendered_frame(output_path, 1.8)
    wipe_pixel = _pixel(wipe_frame, 80, 45)
    assert wipe_pixel[1] > wipe_pixel[0] and wipe_pixel[1] > wipe_pixel[2]
    right_wipe_frame = _rendered_frame(output_path, 2.1)
    assert _pixel(right_wipe_frame, 140, 45)[1] > 80
    assert max(_pixel(right_wipe_frame, 20, 45)) < 15
    gap_frame = _rendered_frame(output_path, 2.6)
    assert max(_pixel(gap_frame, 80, 45)) < 15
    subtitle_frame = _rendered_frame(output_path, 0.5)
    subtitle_crop = [_pixel(subtitle_frame, x, y) for y in range(60, 90) for x in range(45, 115)]
    assert (
        sum(1 for red, green, blue in subtitle_crop if red < 180 or green > 30 or blue > 30) > 100
    )

    assert _audio_rms(output_path, 0.05) < _audio_rms(output_path, 0.3)
    assert _audio_rms(output_path, 0.4) > 500
    assert _audio_rms(output_path, 0.8) < _audio_rms(output_path, 0.4)
    assert _audio_rms(output_path, 1.2) < 100
    assert _audio_rms(output_path, 1.8) > 500
    assert _audio_rms(output_path, 2.8) < _audio_rms(output_path, 2.5)


def test_effect_schema_order_and_cross_dissolve_overlap_validation() -> None:
    base = {
        "id": "4564e258-24e4-4a77-bf77-e5517ad5b09f",
        "media_asset_id": "4564e258-24e4-4a77-bf77-e5517ad5b080",
        "start": 0,
        "duration": 1,
        "source_start": 0,
        "source_end": 1,
    }
    effect_list = [
        {"id": "4564e258-24e4-4a77-bf77-e5517ad5b091", "type": "brightness", "value": 0.2},
        {"id": "4564e258-24e4-4a77-bf77-e5517ad5b092", "type": "grayscale", "value": 0.5},
        {"id": "4564e258-24e4-4a77-bf77-e5517ad5b093", "type": "blur", "value": 2},
    ]
    filters = _effect_filters({"effects": effect_list})
    assert filters[0] == "eq=brightness=0.2"
    assert filters[1] == "hue=s=0.5"
    assert filters[2].startswith("boxblur=lr='min(2,min(w,h)/2-1)'")
    assert _effect_filters({"effects": [effect_list[0] | {"enabled": False}]}) == []
    with pytest.raises(ValueError, match="blur effect value"):
        TimelineTrackData.model_validate(
            {
                "id": "4564e258-24e4-4a77-bf77-e5517ad5b094",
                "name": "V1",
                "type": "video",
                "clips": [base | {"effects": [effect_list[2] | {"value": 21}]}],
            }
        )

    incoming = base | {
        "id": "4564e258-24e4-4a77-bf77-e5517ad5b095",
        "start": 0.75,
        "duration": 1,
        "source_end": 1,
        "transition_in": "cross_dissolve",
        "transition_in_version": 1,
        "transition_in_duration": 0.2,
    }
    track = {
        "id": "4564e258-24e4-4a77-bf77-e5517ad5b096",
        "name": "V1",
        "type": "video",
        "clips": [base, incoming],
    }
    TimelineTrackData.model_validate(track)
    TimelineTrackData.model_validate(track | {"clips": [incoming | {"transition_in_version": 0}]})
    with pytest.raises(ValueError, match="overlap with the preceding clip"):
        TimelineTrackData.model_validate(track | {"clips": [base | {"duration": 0.9}, incoming]})


def test_text_style_validation_and_srt_vtt_round_trip() -> None:
    style = TimelineTextStyleData(
        font_family="serif",
        font_size=38,
        color="#F0A020",
        background_color="#102030",
        background_opacity=0.75,
        alignment="left",
        width=0.7,
    )
    assert style.font_family == "serif"
    with pytest.raises(ValueError):
        TimelineTextStyleData(color="red")
    with pytest.raises(ValueError):
        TimelineTextStyleData(font_size=301)

    srt = (
        "1\n00:00:01,250 --> 00:00:02,750\nCafé — Καλημέρα\n\n"
        "2\n00:00:03,000 --> 00:00:03,500\n字幕\n"
    )
    srt_cues = parse_subtitles(srt, "srt")
    assert [(cue.start, cue.duration, cue.text) for cue in srt_cues] == [
        (1.25, 1.5, "Café — Καλημέρα"),
        (3.0, 0.5, "字幕"),
    ]
    assert export_subtitles(srt_cues, "srt") == srt

    vtt = "WEBVTT\n\nintro\n00:01.000 --> 00:02.250 align:center\nHello\n"
    vtt_cues = parse_subtitles(vtt, "vtt")
    assert vtt_cues[0].start == pytest.approx(1)
    assert export_subtitles(vtt_cues, "vtt") == (
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.250\nHello\n"
    )
    assert export_subtitles(vtt_cues, "srt") == (
        "1\n00:00:01,000 --> 00:00:02,250\nHello\n"
    )
    with pytest.raises(ValueError, match="invalid timestamp"):
        parse_subtitles("1\n00:61:00,000 --> 00:62:00,000\nBad cue", "srt")
    with pytest.raises(ValueError, match="missing a timestamp"):
        parse_subtitles("Just text with no cue range", "vtt")


def test_subtitle_edge_cases_preserve_cues_and_precision() -> None:
    first_text = "  First line  \nSecond line"
    srt = (
        "\ufeff1\r\n23:59:59,999 --> 24:00:00,000\r\n"
        f"{first_text}\r\n\r\n"
        "2\r\n23:59:59,999 --> 24:00:00,000\r\nOverlapping cue\r\n"
    )
    cues = parse_subtitles(srt, "srt")
    assert [cue.start for cue in cues] == pytest.approx([86_399.999, 86_399.999])
    assert [cue.duration for cue in cues] == pytest.approx([0.001, 0.001])
    assert [cue.text for cue in cues] == [first_text, "Overlapping cue"]
    assert export_subtitles(cues, "srt") == (
        "1\n23:59:59,999 --> 24:00:00,000\n"
        f"{first_text}\n\n"
        "2\n23:59:59,999 --> 24:00:00,000\nOverlapping cue\n"
    )
    converted = parse_subtitles(export_subtitles(cues, "vtt"), "vtt")
    assert [cue.start for cue in converted] == pytest.approx([cue.start for cue in cues])
    assert [cue.duration for cue in converted] == pytest.approx([cue.duration for cue in cues])
    assert [cue.text for cue in converted] == [cue.text for cue in cues]
    assert parse_subtitles(
        "WEBVTT\r\n\r\nintro\r\n01:02:03.456 --> 01:02:04.007 align:start\r\n  Café\r\n",
        "vtt",
    )[0].text == "  Café"

    long_text = "é" * 10_000
    long_cue = parse_subtitles(
        f"1\n00:00:00,000 --> 00:00:01,000\n{long_text}\n",
        "srt",
    )
    assert long_cue[0].text == long_text
    with pytest.raises(ValueError, match="10,000-character limit"):
        parse_subtitles(
            f"1\n00:00:00,000 --> 00:00:01,000\n{long_text}é\n",
            "srt",
        )
    with pytest.raises(ValueError, match="no valid cues"):
        parse_subtitles("\ufeff \r\n", "vtt")
    with pytest.raises(ValueError, match="has no text"):
        parse_subtitles("1\n00:00:00,000 --> 00:00:01,000\n", "srt")
    with pytest.raises(ValueError, match="24-hour timeline limit"):
        parse_subtitles("1\n24:00:00,000 --> 24:00:00,001\nToo late", "srt")


def test_subtitle_import_export_endpoints_validate_and_enforce_ownership(
    client: TestClient,
) -> None:
    token = _register(client, "timeline-subtitles@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Subtitle IO"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    imported = client.post(
        f"/api/v1/projects/{project_id}/timeline/subtitles/import",
        headers=headers,
        files={
            "file": (
                "captions.srt",
                "1\n00:00:01,000 --> 00:00:02,000\nCafé".encode(),
                "text/plain",
            )
        },
    )
    assert imported.status_code == 200
    assert imported.json()[0]["text"] == "Café"
    timeline = client.get(f"/api/v1/projects/{project_id}/timeline", headers=headers).json()[
        "timeline_data"
    ]
    subtitle_track = next(track for track in timeline["tracks"] if track["type"] == "subtitle")
    subtitle_track["clips"] = [
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b2b1",
            **imported.json()[0],
            "source_start": 0,
        }
    ]
    imported_vtt = client.post(
        f"/api/v1/projects/{project_id}/timeline/subtitles/import",
        headers=headers,
        files={
            "file": (
                "overlap.vtt",
                (
                    b"\xef\xbb\xbfWEBVTT\r\n\r\n"
                    b"one\r\n00:00:01.500 --> 00:00:02.000\r\nVTT one\r\n\r\n"
                    b"two\r\n00:00:01.750 --> 00:00:02.250\r\nVTT two\r\n"
                ),
                "text/vtt",
            )
        },
    )
    assert imported_vtt.status_code == 200
    subtitle_track["clips"].extend(
        {
            "id": f"4564e258-24e4-4a77-bf77-e5517ad5b2b{index + 2}",
            **cue,
            "source_start": 0,
        }
        for index, cue in enumerate(imported_vtt.json())
    )
    saved = client.put(f"/api/v1/projects/{project_id}/timeline", headers=headers, json=timeline)
    assert saved.status_code == 200, saved.text
    exported = client.get(
        f"/api/v1/projects/{project_id}/timeline/subtitles/export?format=vtt",
        headers=headers,
    )
    assert exported.status_code == 200
    assert exported.text.startswith("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nCafé")
    assert "VTT one" in exported.text and "VTT two" in exported.text
    exported_srt = client.get(
        f"/api/v1/projects/{project_id}/timeline/subtitles/export?format=srt",
        headers=headers,
    )
    assert exported_srt.status_code == 200
    assert "00:00:01,500 --> 00:00:02,000\nVTT one" in exported_srt.text
    assert "00:00:01,750 --> 00:00:02,250\nVTT two" in exported_srt.text
    invalid = client.post(
        f"/api/v1/projects/{project_id}/timeline/subtitles/import",
        headers=headers,
        files={"file": ("captions.vtt", b"WEBVTT\n\nnot a cue", "text/vtt")},
    )
    assert invalid.status_code == 422
    assert "timestamp" in invalid.json()["error"]["message"].lower()
    unsupported = client.post(
        f"/api/v1/projects/{project_id}/timeline/subtitles/import",
        headers=headers,
        files={"file": ("captions.txt", b"captions", "text/plain")},
    )
    assert unsupported.status_code == 415
    invalid_utf8 = client.post(
        f"/api/v1/projects/{project_id}/timeline/subtitles/import",
        headers=headers,
        files={"file": ("captions.srt", b"\xff", "text/plain")},
    )
    assert invalid_utf8.status_code == 422
    empty = client.post(
        f"/api/v1/projects/{project_id}/timeline/subtitles/import",
        headers=headers,
        files={"file": ("empty.vtt", b"\xef\xbb\xbfWEBVTT\r\n\r\n", "text/vtt")},
    )
    assert empty.status_code == 422
    assert "no valid cues" in empty.json()["error"]["message"].lower()
    oversized = client.post(
        f"/api/v1/projects/{project_id}/timeline/subtitles/import",
        headers=headers,
        files={"file": ("large.srt", b"x" * 2_000_001, "text/plain")},
    )
    assert oversized.status_code == 413

    other_token = _register(client, "timeline-subtitles-other@example.com")
    forbidden = client.post(
        f"/api/v1/projects/{project_id}/timeline/subtitles/import",
        headers={"Authorization": f"Bearer {other_token}"},
        files={"file": ("captions.srt", b"1\n00:00:00,000 --> 00:00:01,000\nHi", "text/plain")},
    )
    assert forbidden.status_code == 404


def test_text_overlay_and_unicode_subtitles_render_in_ffmpeg(
    client: TestClient, tmp_path: Path
) -> None:
    video_bytes, _ = _make_media(tmp_path)
    token = _register(client, "timeline-text-render@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Text render"})
    upload = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": ("source.mp4", video_bytes, "video/mp4")},
    )
    assert project.status_code == 201
    assert upload.status_code == 201
    assert _wait_for_media_job(client, headers, upload.json()["job_id"])["status"] == "completed"
    project_id = project.json()["id"]
    timeline = client.get(f"/api/v1/projects/{project_id}/timeline", headers=headers).json()[
        "timeline_data"
    ]
    timeline.update({"width": 160, "height": 90, "frame_rate": 10})
    video_track = next(track for track in timeline["tracks"] if track["type"] == "video")
    overlay_track = next(track for track in timeline["tracks"] if track["type"] == "overlay")
    subtitle_track = next(track for track in timeline["tracks"] if track["type"] == "subtitle")
    video_track["clips"] = [
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b2a1",
            "media_asset_id": upload.json()["asset"]["id"],
            "start": 0,
            "duration": 1,
            "source_start": 0,
            "source_end": 1,
        }
    ]
    title = {
        "id": "4564e258-24e4-4a77-bf77-e5517ad5b2a2",
        "start": 0,
        "duration": 0.4,
        "source_start": 0,
        "text": "Opening title",
        "position_x": 0.5,
        "position_y": 0.12,
        "text_style": {
            "font_size": 18,
            "width": 0.8,
            "color": "#FFFFFF",
            "background_color": "#FF0000",
            "background_opacity": 1,
            "outline_width": 0,
        },
    }
    lower_third = {
        **title,
        "id": "4564e258-24e4-4a77-bf77-e5517ad5b2a3",
        "start": 0.2,
        "duration": 0.6,
        "text": "Speaker name",
        "position_x": 0.1,
        "position_y": 0.82,
        "text_style": {
            "font_size": 14,
            "alignment": "left",
            "width": 0.7,
            "color": "#FFFFFF",
            "background_color": "#00FF00",
            "background_opacity": 1,
            "outline_width": 0,
        },
    }
    subtitle = {
        **title,
        "id": "4564e258-24e4-4a77-bf77-e5517ad5b2a4",
        "start": 0.3,
        "duration": 0.4,
        "text": "字幕 తెలుగు हिन्दी தமிழ் ಕನ್ನಡ മലയാളം",
        "position_x": 0.5,
        "position_y": 0.12,
        "text_style": {
            "font_size": 10,
            "width": 0.8,
            "color": "#FFFFFF",
            "background_color": "#0000FF",
            "background_opacity": 1,
            "outline_width": 0,
        },
    }
    overlay_track["clips"] = [title, lower_third]
    subtitle_track["clips"] = [subtitle]
    saved = client.put(f"/api/v1/projects/{project_id}/timeline", headers=headers, json=timeline)
    assert saved.status_code == 200, saved.text

    export = client.post(f"/api/v1/projects/{project_id}/timeline/export", headers=headers, json={})
    assert export.status_code == 202, export.text
    job = _wait_for_job(client, headers, export.json()["job_id"])
    assert job["status"] == "completed", job
    output = client.get(f"/api/v1/timeline/exports/{job['id']}/download", headers=headers)
    assert output.status_code == 200
    output_path = tmp_path / "text-output.mp4"
    output_path.write_bytes(output.content)
    metadata = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (
        json.loads(metadata.stdout)["streams"][0]["width"],
        json.loads(metadata.stdout)["streams"][0]["height"],
    ) == (160, 90)
    opening = _rendered_frame(output_path, 0.15)
    overlap = _rendered_frame(output_path, 0.45)
    assert (
        sum(
            1
            for r, g, b in (tuple(opening[i : i + 3]) for i in range(0, len(opening), 3))
            if r > 180 and g < 80 and b < 80
        )
        > 20
    )
    assert (
        sum(
            1
            for r, g, b in (tuple(overlap[i : i + 3]) for i in range(0, len(overlap), 3))
            if b > 180 and r < 80 and g < 80
        )
        > 20
    )
    assert (
        sum(
            1
            for r, g, b in (tuple(overlap[i : i + 3]) for i in range(0, len(overlap), 3))
            if g > 180 and r < 80 and b < 80
        )
        > 20
    )
    assert (
        sum(
            1
            for y in range(30)
            for x in range(160)
            if (pixel := _pixel(overlap, x, y))[0] > 220 and pixel[1] > 220 and pixel[2] > 220
        )
        > 10
    )
    expired = _rendered_frame(output_path, 0.9)
    assert (
        sum(
            1
            for r, g, b in (tuple(expired[i : i + 3]) for i in range(0, len(expired), 3))
            if r > 180 and g < 80 and b < 80
        )
        < 10
    )
    overlay_track["clips"].append(
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b2a5",
            "start": 0,
            "duration": 0.7,
            "source_start": 0,
            "text": "X" * 100,
            "text_style": {"font_size": 20, "width": 0.1},
        }
    )
    oversized_text_timeline = client.put(
        f"/api/v1/projects/{project_id}/timeline",
        headers=headers,
        json=timeline,
    )
    assert oversized_text_timeline.status_code == 200, oversized_text_timeline.text
    oversized_text_export = client.post(
        f"/api/v1/projects/{project_id}/timeline/export",
        headers=headers,
        json={},
    )
    assert oversized_text_export.status_code == 422
    blocked_issue = oversized_text_export.json()["error"]["details"][0]
    assert blocked_issue["clip_id"] == "4564e258-24e4-4a77-bf77-e5517ad5b2a5"
    assert blocked_issue["message"].startswith("Text overlay wraps to")
    assert "exceeding the" in blocked_issue["message"]
    assert "split the text into multiple clips" in blocked_issue["recommendation"]

    fit_proposal = client.post(
        f"/api/v1/projects/{project_id}/timeline/text-fit",
        headers=headers,
        json={
            "timeline": timeline,
            "clip_id": "4564e258-24e4-4a77-bf77-e5517ad5b2a5",
            "operation": "fit_width",
        },
    )
    assert fit_proposal.status_code == 200, fit_proposal.text
    fitted_timeline = fit_proposal.json()["timeline"]
    fitted_clip = next(
        clip
        for track in fitted_timeline["tracks"]
        for clip in track["clips"]
        if clip["id"] == "4564e258-24e4-4a77-bf77-e5517ad5b2a5"
    )
    assert fitted_clip["text"] == "X" * 100
    assert fitted_clip["text_style"]["width"] == 1
    shrink_proposal = client.post(
        f"/api/v1/projects/{project_id}/timeline/text-fit",
        headers=headers,
        json={
            "timeline": fitted_timeline,
            "clip_id": "4564e258-24e4-4a77-bf77-e5517ad5b2a5",
            "operation": "shrink",
            "minimum_font_size": 10,
        },
    )
    assert shrink_proposal.status_code == 200, shrink_proposal.text
    fitted_timeline = shrink_proposal.json()["timeline"]
    fitted_clip = next(
        clip
        for track in fitted_timeline["tracks"]
        for clip in track["clips"]
        if clip["id"] == "4564e258-24e4-4a77-bf77-e5517ad5b2a5"
    )
    assert fitted_clip["text"] == "X" * 100
    assert 10 <= fitted_clip["text_style"]["font_size"] < 20
    assert client.put(
        f"/api/v1/projects/{project_id}/timeline",
        headers=headers,
        json=fitted_timeline,
    ).status_code == 200
    reloaded = client.get(
        f"/api/v1/projects/{project_id}/timeline", headers=headers
    ).json()["timeline_data"]
    assert next(
        clip
        for track in reloaded["tracks"]
        for clip in track["clips"]
        if clip["id"] == "4564e258-24e4-4a77-bf77-e5517ad5b2a5"
    )["text"] == "X" * 100
    fitted_export = client.post(
        f"/api/v1/projects/{project_id}/timeline/export", headers=headers, json={}
    )
    assert fitted_export.status_code == 202, fitted_export.text
    fitted_job = _wait_for_job(client, headers, fitted_export.json()["job_id"])
    assert fitted_job["status"] == "completed", fitted_job


def test_text_validation_reports_blockers_and_advisories(client: TestClient) -> None:
    token = _register(client, "timeline-text-validation@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Text validation"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    timeline = client.get(
        f"/api/v1/projects/{project_id}/timeline", headers=headers
    ).json()["timeline_data"]
    overlay_track = next(track for track in timeline["tracks"] if track["type"] == "overlay")
    subtitle_track = next(track for track in timeline["tracks"] if track["type"] == "subtitle")
    overlay_track["clips"] = [
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b2b1",
            "start": 0,
            "duration": 1,
            "source_start": 0,
            "text": "\U0010ffff",
            "effects": [
                {
                    "id": "4564e258-24e4-4a77-bf77-e5517ad5b2b4",
                    "type": "brightness",
                    "enabled": True,
                    "value": 0.1,
                }
            ],
        }
    ]
    subtitle_track["clips"] = [
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b2b2",
            "start": 0,
            "duration": 0.2,
            "source_start": 0,
            "text": "A very long subtitle that needs several rendered lines " * 20,
            "text_style": {"font_size": 24, "width": 0.2},
        }
    ]
    result = client.post(
        f"/api/v1/projects/{project_id}/timeline/text-validation",
        headers=headers,
        json={"timeline": timeline, "preset": "720p"},
    )
    assert result.status_code == 200, result.text
    issues = result.json()["issues"]
    font_issue = next(issue for issue in issues if issue["code"] == "font")
    assert font_issue["severity"] == "error"
    assert "Available font families" in font_issue["message"]
    assert any(
        issue["code"] == "unsupported_style"
        and issue["clip_id"] == "4564e258-24e4-4a77-bf77-e5517ad5b2b1"
        for issue in issues
    )
    subtitle_issues = [
        issue for issue in issues if issue["clip_id"] == "4564e258-24e4-4a77-bf77-e5517ad5b2b2"
    ]
    assert any(
        issue["code"] == "layout" and issue["severity"] == "error"
        for issue in subtitle_issues
    ), issues
    assert any(
        issue["code"] == "subtitle_duration" and issue["severity"] == "warning"
        for issue in subtitle_issues
    )

    other_token = _register(client, "timeline-text-validation-other@example.com")
    forbidden = client.post(
        f"/api/v1/projects/{project_id}/timeline/text-validation",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"timeline": timeline},
    )
    assert forbidden.status_code == 404


def test_subtitle_split_proposal_preserves_text_timing_and_persistence(
    client: TestClient,
) -> None:
    token = _register(client, "timeline-subtitle-fit@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Subtitle fit"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    timeline = client.get(
        f"/api/v1/projects/{project_id}/timeline", headers=headers
    ).json()["timeline_data"]
    subtitle_track = next(track for track in timeline["tracks"] if track["type"] == "subtitle")
    original_text = "Keep every word, punctuation mark!"
    subtitle_track["clips"] = [
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b2b3",
            "start": 2,
            "duration": 0.8,
            "source_start": 0,
            "text": original_text,
            "text_style": {"font_size": 40, "width": 0.4},
        }
    ]
    proposal = client.post(
        f"/api/v1/projects/{project_id}/timeline/text-fit",
        headers=headers,
        json={
            "timeline": timeline,
            "clip_id": "4564e258-24e4-4a77-bf77-e5517ad5b2b3",
            "operation": "split",
        },
    )
    assert proposal.status_code == 200, proposal.text
    proposed_timeline = proposal.json()["timeline"]
    cues = next(track for track in proposed_timeline["tracks"] if track["type"] == "subtitle")[
        "clips"
    ]
    cues.sort(key=lambda cue: cue["start"])
    assert len(cues) == 2
    assert "".join(cue["text"] for cue in cues) == original_text
    assert cues[0]["start"] + cues[0]["duration"] == pytest.approx(cues[1]["start"])
    assert sum(cue["duration"] for cue in cues) == pytest.approx(0.8)
    assert proposal.json()["warnings"]
    saved = client.put(
        f"/api/v1/projects/{project_id}/timeline", headers=headers, json=proposed_timeline
    )
    assert saved.status_code == 200, saved.text
    reloaded = client.get(
        f"/api/v1/projects/{project_id}/timeline", headers=headers
    ).json()["timeline_data"]
    reloaded_cues = next(
        track for track in reloaded["tracks"] if track["type"] == "subtitle"
    )["clips"]
    assert "".join(cue["text"] for cue in sorted(reloaded_cues, key=lambda cue: cue["start"])) == original_text


def test_text_renderer_supports_indic_scripts_and_reports_missing_glyphs(
    tmp_path: Path,
) -> None:
    scripts = {
        "English": "Hello",
        "Telugu": "తెలుగు",
        "Hindi": "हिन्दी",
        "Tamil": "தமிழ்",
        "Kannada": "ಕನ್ನಡ",
        "Malayalam": "മലയാളം",
    }
    for name, text in scripts.items():
        output = tmp_path / f"{name}.png"
        try:
            _render_subtitle_image(text, output, 1280, 720, {"font_size": 48})
        except RuntimeError as error:
            assert "No installed Unicode font can render every character" in str(error)
        else:
            with Image.open(output) as image:
                assert image.getchannel("A").getbbox() is not None

    with pytest.raises(RuntimeError, match="No installed Unicode font"):
        _render_subtitle_image("\U0010ffff", tmp_path / "missing-glyph.png", 1280, 720)

    emoji = tmp_path / "emoji.png"
    try:
        _render_subtitle_image("🎬✨", emoji, 1280, 720)
    except RuntimeError as error:
        assert "No installed Unicode font can render every character" in str(error)
    else:
        with Image.open(emoji) as image:
            assert image.getchannel("A").getbbox() is not None

    long_line = tmp_path / "long-line.png"
    _render_subtitle_image(
        "தமிழ் " * 100,
        long_line,
        1280,
        720,
        {"font_size": 24, "width": 0.9},
    )
    with Image.open(long_line) as image:
        assert image.getchannel("A").getbbox() is not None

    with pytest.raises(RuntimeError, match="exceeding the .*line limit"):
        _render_subtitle_image(
            "X" * 1_000,
            tmp_path / "too-many-lines.png",
            160,
            90,
            {"font_size": 20, "width": 0.1},
        )


def test_unversioned_cross_dissolve_cannot_be_added_to_a_new_timeline(
    client: TestClient,
) -> None:
    token = _register(client, "timeline-transition-validation@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post(
        "/api/v1/projects", headers=headers, json={"name": "Transition validation"}
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    timeline = client.get(f"/api/v1/projects/{project_id}/timeline", headers=headers).json()[
        "timeline_data"
    ]
    audio_track = next(track for track in timeline["tracks"] if track["type"] == "audio")
    audio_track["clips"] = [
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b097",
            "start": 0,
            "duration": 1,
            "source_start": 0,
            "transition_in": "cross_dissolve",
            "transition_in_duration": 0.5,
        }
    ]
    rejected = client.put(
        f"/api/v1/projects/{project_id}/timeline",
        headers=headers,
        json=timeline,
    )
    assert rejected.status_code == 422
    assert "new cross dissolve" in rejected.json()["error"]["message"].lower()


def test_visual_effects_and_black_fades_render_to_expected_frames(
    client: TestClient, tmp_path: Path
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and FFprobe are required for visual effect export tests.")
    source_path = tmp_path / "effect-pattern.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10:duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-y",
            str(source_path),
        ],
        check=True,
        capture_output=True,
    )
    token = _register(client, "timeline-effects@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post(
        "/api/v1/projects", headers=headers, json={"name": "Visual effects render"}
    )
    upload = client.post(
        "/api/v1/media",
        headers=headers,
        files={"file": (source_path.name, source_path.read_bytes(), "video/mp4")},
    )
    assert project.status_code == 201
    assert upload.status_code == 201
    assert _wait_for_media_job(client, headers, upload.json()["job_id"])["status"] == "completed"
    asset_id = upload.json()["asset"]["id"]
    timeline = client.get(
        f"/api/v1/projects/{project.json()['id']}/timeline", headers=headers
    ).json()["timeline_data"]
    timeline.update({"width": 160, "height": 90, "frame_rate": 10})
    effect_cases = [
        ("brightness", 0.4),
        ("contrast", 2),
        ("saturation", 0),
        ("grayscale", 1),
        ("blur", 4),
        ("baseline", None),
    ]
    clips = []
    for index, (effect_type, value) in enumerate(effect_cases):
        clip = {
            "id": f"4564e258-24e4-4a77-bf77-e5517ad5b1{index:02d}",
            "media_asset_id": asset_id,
            "start": 0.5 + index * 0.5,
            "duration": 0.5,
            "source_start": 0,
            "source_end": 2,
        }
        if effect_type == "baseline":
            clip["start"] = 3
        else:
            clip["effects"] = [
                {
                    "id": f"4564e258-24e4-4a77-bf77-e5517ad5b2{index:02d}",
                    "type": effect_type,
                    "enabled": True,
                    "value": value,
                }
            ]
        clips.append(clip)
    clips.append(
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b188",
            "media_asset_id": asset_id,
            "start": 0,
            "duration": 0.5,
            "source_start": 0,
            "source_end": 2,
            "transition_in": "fade",
            "transition_in_duration": 0.5,
        }
    )
    clips.append(
        {
            "id": "4564e258-24e4-4a77-bf77-e5517ad5b199",
            "media_asset_id": asset_id,
            "start": 3.5,
            "duration": 0.5,
            "source_start": 0,
            "source_end": 2,
            "transition_out": "fade",
            "transition_out_duration": 0.5,
        }
    )
    video_track = next(track for track in timeline["tracks"] if track["type"] == "video")
    video_track["clips"] = clips
    saved = client.put(
        f"/api/v1/projects/{project.json()['id']}/timeline",
        headers=headers,
        json=timeline,
    )
    assert saved.status_code == 200, saved.text
    restored = client.get(
        f"/api/v1/projects/{project.json()['id']}/timeline", headers=headers
    ).json()["timeline_data"]
    assert restored["tracks"][0]["clips"][1]["effects"][0]["type"] == "contrast"

    queued = client.post(
        f"/api/v1/projects/{project.json()['id']}/timeline/export",
        headers=headers,
        json={},
    )
    assert queued.status_code == 202, queued.text
    job = _wait_for_job(client, headers, queued.json()["job_id"])
    assert job["status"] == "completed", job
    output_path = tmp_path / "effect-output.mp4"
    download = client.get(f"/api/v1/timeline/exports/{job['id']}/download", headers=headers)
    assert download.status_code == 200
    output_path.write_bytes(download.content)
    metadata = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height",
            "-of",
            "json",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = json.loads(metadata.stdout)
    assert any((stream["width"], stream["height"]) == (160, 90) for stream in probe["streams"])
    assert float(probe["format"]["duration"]) == pytest.approx(4, abs=0.2)

    baseline = _rendered_frame(output_path, 3.25)
    baseline_means = _channel_means(baseline)
    bright_means = _channel_means(_rendered_frame(output_path, 0.75))
    assert sum(bright_means) / 3 > sum(baseline_means) / 3 + 20
    contrast = _rendered_frame(output_path, 1.25)
    assert contrast != baseline
    desaturated_means = _channel_means(_rendered_frame(output_path, 1.75))
    grayscale_means = _channel_means(_rendered_frame(output_path, 2.25))
    assert max(desaturated_means) - min(desaturated_means) < max(baseline_means) - min(
        baseline_means
    )
    assert max(grayscale_means) - min(grayscale_means) < 5
    blur = _rendered_frame(output_path, 2.75)
    assert _horizontal_luma_difference(blur) < _horizontal_luma_difference(baseline)
    early_fade = _rendered_frame(output_path, 0.05)
    late_fade = _rendered_frame(output_path, 0.4)
    assert sum(_channel_means(early_fade)) < sum(_channel_means(late_fade))
    early_fade_out = _rendered_frame(output_path, 3.55)
    late_fade_out = _rendered_frame(output_path, 3.85)
    assert sum(_channel_means(early_fade_out)) > sum(_channel_means(late_fade_out))
