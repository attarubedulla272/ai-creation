"""Tests for the isolated mlx-audio-plus transcription adapter."""

import asyncio
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.voice_providers import (
    MlxAudioPlusWorkerTranscriptionProvider,
    MlxWhisperTranscriptionProvider,
    create_default_voice_providers,
)


def _write_worker_script(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    return path


def test_isolated_worker_normalizes_timestamped_segments(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio with spaces.wav"
    audio_path.write_bytes(b"test audio")
    script = _write_worker_script(
        tmp_path / "fake_worker.py",
        "import json\n"
        "print(json.dumps({'language': 'en', 'segments': "
        "[{'start': 0.25, 'end': 1.5, 'text': ' Sample transcript. '}], "
        "'metrics': {'inference_seconds': 0.5, 'chunk_count': 2}}))\n",
    )
    provider = MlxAudioPlusWorkerTranscriptionProvider(
        Path(sys.executable),
        tmp_path / "local model",
        timeout_seconds=5,
        worker_script=script,
    )

    result = asyncio.run(provider.transcribe(audio_path, "en"))

    assert provider.name == "mlx-audio-plus-worker"
    assert result.language == "en"
    assert len(result.segments) == 1
    assert result.segments[0].start_seconds == 0.25
    assert result.segments[0].end_seconds == 1.5
    assert result.segments[0].text == "Sample transcript."
    assert result.metrics == {"inference_seconds": 0.5, "chunk_count": 2}


def test_isolated_worker_streams_chunk_progress(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"test audio")
    script = _write_worker_script(
        tmp_path / "progress_worker.py",
        "import json\nimport sys\n"
        "sys.stderr.write('loading 10%\\rACS_PROGRESS:50\\n')\n"
        "sys.stderr.flush()\n"
        "print('ACS_PROGRESS:100', file=sys.stderr, flush=True)\n"
        "print(json.dumps({'language': 'en', 'segments': [], 'metrics': {}}))\n",
    )
    provider = MlxAudioPlusWorkerTranscriptionProvider(
        Path(sys.executable),
        tmp_path / "model",
        timeout_seconds=5,
        worker_script=script,
    )
    progress: list[int] = []

    async def record_progress(value: int) -> None:
        progress.append(value)

    asyncio.run(provider.transcribe(audio_path, None, on_progress=record_progress))

    assert progress == [50, 100]


def test_isolated_worker_reports_process_failure(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"test audio")
    script = _write_worker_script(
        tmp_path / "failed_worker.py",
        "import sys\nprint('failure', file=sys.stderr)\nsys.exit(1)\n",
    )
    provider = MlxAudioPlusWorkerTranscriptionProvider(
        Path(sys.executable),
        tmp_path / "model",
        timeout_seconds=5,
        worker_script=script,
    )

    with pytest.raises(RuntimeError, match="worker failed"):
        asyncio.run(provider.transcribe(audio_path, None))


def test_isolated_worker_kills_timed_out_process(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"test audio")
    script = _write_worker_script(
        tmp_path / "slow_worker.py",
        "import time\ntime.sleep(10)\n",
    )
    provider = MlxAudioPlusWorkerTranscriptionProvider(
        Path(sys.executable),
        tmp_path / "model",
        timeout_seconds=0.1,
        worker_script=script,
    )

    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(provider.transcribe(audio_path, None))


def test_isolated_worker_kills_cancelled_process(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"test audio")
    pid_path = tmp_path / "worker.pid"
    script = _write_worker_script(
        tmp_path / "cancelled_worker.py",
        "import os\nimport time\n"
        f"open({str(pid_path)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(10)\n",
    )
    provider = MlxAudioPlusWorkerTranscriptionProvider(
        Path(sys.executable),
        tmp_path / "model",
        timeout_seconds=30,
        worker_script=script,
    )

    async def cancel_worker() -> None:
        task = asyncio.create_task(provider.transcribe(audio_path, None))
        for _ in range(100):
            if pid_path.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_path.exists()
        pid = int(pid_path.read_text(encoding="utf-8"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    asyncio.run(cancel_worker())


def test_worker_requires_existing_local_model_files(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"test audio")
    model_path = tmp_path / "empty-model"
    model_path.mkdir()
    worker_script = Path(__file__).parents[1] / "mlx_audio_worker" / "transcribe.py"

    result = subprocess.run(
        [
            sys.executable,
            str(worker_script),
            "--audio-path",
            str(audio_path),
            "--model-path",
            str(model_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "local model directory is incomplete" in result.stderr


def test_factory_selects_isolated_provider_only_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    model_path = tmp_path / "model"
    model_path.mkdir()
    worker_python = tmp_path / "worker-python"
    worker_python.symlink_to(Path(sys.executable))
    for filename in ("config.json", "model.safetensors", "multilingual.tiktoken"):
        (model_path / filename).write_bytes(b"metadata only")

    providers = create_default_voice_providers(
        Settings(
            voice_transcription_provider="mlx-audio-plus",
            mlx_audio_worker_python=worker_python,
            mlx_audio_model_path=model_path,
        )
    )

    assert providers.transcription is not None
    assert providers.transcription.name == "mlx-audio-plus-worker"
    assert providers.transcription.python_executable == worker_python


def test_factory_preserves_existing_mlx_whisper_auto_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        "app.services.voice_providers.importlib.util.find_spec",
        lambda module_name: object() if module_name == "mlx_whisper" else None,
    )

    providers = create_default_voice_providers(Settings())

    assert isinstance(providers.transcription, MlxWhisperTranscriptionProvider)


def test_factory_rejects_non_apple_silicon_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")

    with pytest.raises(RuntimeError, match="native Apple Silicon"):
        create_default_voice_providers(Settings(voice_transcription_provider="mlx-audio-plus"))
