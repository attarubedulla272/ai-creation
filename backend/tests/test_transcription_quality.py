"""Audio normalization, chunk-boundary, and language-aware metric tests."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.services.transcription_evaluation import character_error_rate, word_error_rate

WORKER_PATH = Path(__file__).parents[1] / "mlx_audio_worker" / "transcribe.py"


@pytest.fixture(scope="module")
def worker() -> ModuleType:
    specification = importlib.util.spec_from_file_location("acs_mlx_audio_worker", WORKER_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("Could not import the isolated MLX worker helpers.")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is required for audio normalization tests.")
    return executable


@pytest.fixture
def sample_media(tmp_path: Path) -> dict[str, Path]:
    ffmpeg = _ffmpeg()
    wav = tmp_path / "source.wav"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.2",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    mp3 = tmp_path / "source.mp3"
    m4a = tmp_path / "source.m4a"
    video = tmp_path / "source.mp4"
    subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(wav), "-c:a", "libmp3lame", "-y", str(mp3)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(wav), "-c:a", "aac", "-y", str(m4a)],
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
            "color=c=black:s=320x240:r=24:d=2.2",
            "-i",
            str(wav),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    return {"wav": wav, "mp3": mp3, "m4a": m4a, "video": video}


@pytest.mark.parametrize("format_name", ["wav", "mp3", "m4a", "video"])
def test_audio_formats_and_video_audio_are_normalized(
    worker: ModuleType,
    sample_media: dict[str, Path],
    tmp_path: Path,
    format_name: str,
) -> None:
    source = sample_media[format_name]
    duration = worker._media_duration(source)
    assert duration == pytest.approx(2.2, abs=0.15)
    output = tmp_path / f"{format_name}-normalized.wav"
    worker._normalize_chunk(source, output, 0.2, 1.8)
    probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    audio_stream = json.loads(probe.stdout)["streams"][0]
    assert audio_stream == {
        "codec_name": "pcm_s16le",
        "sample_rate": "16000",
        "channels": 1,
    }


def test_worker_keeps_json_output_clean_when_model_prints(
    sample_media: dict[str, Path],
    tmp_path: Path,
) -> None:
    fake_root = tmp_path / "fake"
    module_dir = fake_root / "mlx_audio" / "stt" / "models"
    module_dir.mkdir(parents=True)
    for package in (
        fake_root / "mlx_audio",
        fake_root / "mlx_audio" / "stt",
        module_dir,
    ):
        (package / "__init__.py").write_text("", encoding="utf-8")
    (module_dir / "whisper.py").write_text(
        "class Model:\n"
        "    @classmethod\n"
        "    def from_pretrained(cls, path):\n"
        "        print('model loading banner')\n"
        "        return cls()\n"
        "    def generate(self, path, **options):\n"
        "        print('Detected language: English')\n"
        "        return type('Result', (), {'language': 'en', "
        "'segments': [{'start': 0, 'end': 0.5, 'text': 'hello'}]})()\n",
        encoding="utf-8",
    )
    model_path = tmp_path / "model"
    model_path.mkdir()
    for filename in ("config.json", "model.safetensors", "multilingual.tiktoken"):
        (model_path / filename).write_bytes(b"test")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(fake_root) + os.pathsep + environment.get("PYTHONPATH", "")

    completed = subprocess.run(
        [
            sys.executable,
            str(WORKER_PATH),
            "--audio-path",
            str(sample_media["wav"]),
            "--model-path",
            str(model_path),
        ],
        capture_output=True,
        check=True,
        env=environment,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["language"] == "en"
    assert result["segments"] == [{"start": 0.0, "end": 0.5, "text": "hello"}]
    assert "Detected language: English" in completed.stderr
    assert "ACS_PROGRESS:100" in completed.stderr


def test_chunk_windows_include_overlap_without_gaps(worker: ModuleType) -> None:
    windows = worker._chunk_windows(130, chunk_seconds=60, overlap_seconds=4)
    assert windows == [
        (0.0, 64.0, 0.0, 60.0),
        (56.0, 124.0, 60.0, 120.0),
        (116.0, 130, 120.0, 130),
    ]


def test_chunk_segments_receive_global_timestamps_and_keep_core_owner(
    worker: ModuleType,
) -> None:
    merged = worker._merge_chunk_segments(
        [
            (
                0,
                13,
                0,
                10,
                False,
                [
                    {"start": 8, "end": 9, "text": "first chunk"},
                    {"start": 10, "end": 12, "text": "outside first core"},
                ],
            ),
            (
                7,
                20,
                10,
                17,
                True,
                [
                    {"start": 1, "end": 2, "text": "outside second core"},
                    {"start": 4, "end": 5, "text": "second chunk"},
                ],
            ),
        ]
    )
    assert merged == [
        {"start": 8.0, "end": 9.0, "text": "first chunk"},
        {"start": 11.0, "end": 12.0, "text": "second chunk"},
    ]


def test_overlapping_chunk_text_deduplicates_boundary_words(worker: ModuleType) -> None:
    merged = worker._merge_chunk_segments(
        [
            (
                0,
                13,
                0,
                10,
                False,
                [{"start": 8, "end": 10.1, "text": "We verified the transcript"}],
            ),
            (
                7,
                20,
                10,
                17,
                True,
                [{"start": 2.8, "end": 4, "text": "transcript with reliable timestamps"}],
            ),
        ]
    )
    assert merged == [
        {"start": 8.0, "end": 10.1, "text": "We verified the transcript"},
        {"start": 9.8, "end": 11.0, "text": "with reliable timestamps"},
    ]


@pytest.mark.parametrize(
    ("reference", "hypothesis", "expected_wer", "expected_cer"),
    [
        ("the quick brown fox", "the quick fox", 0.25, 5 / 16),
        ("नमस्ते दुनिया", "नमस्ते दुनियाँ", 0.5, 1 / 12),
        ("హలో ప్రపంచం", "హలో ప్రపంచము", 0.5, 2 / 10),
    ],
)
def test_unicode_word_and_character_error_rates(
    reference: str,
    hypothesis: str,
    expected_wer: float,
    expected_cer: float,
) -> None:
    assert word_error_rate(reference, hypothesis) == pytest.approx(expected_wer)
    assert character_error_rate(reference, hypothesis) == pytest.approx(expected_cer)


def test_error_rate_rejects_empty_reference() -> None:
    with pytest.raises(ValueError, match="reference transcript"):
        word_error_rate("  ", "transcript")
    with pytest.raises(ValueError, match="reference transcript"):
        character_error_rate("", "transcript")
