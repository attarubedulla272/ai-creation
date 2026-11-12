"""Provider contracts for transcription, translation, and speech synthesis."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import math
import os
import platform
import re
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int], Awaitable[None]]


@dataclass(frozen=True)
class TranscriptWordSegment:
    """One timestamped piece of recognized speech."""

    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    """Normalized output from a speech-to-text provider."""

    language: str | None
    segments: list[TranscriptWordSegment]
    metrics: dict[str, object] | None = None


@dataclass(frozen=True)
class TranslationResult:
    """Translation text and the model provenance that produced it."""

    text: str
    provider: str
    model: str
    model_version: str
    model_license: str


class TranscriptionProvider(Protocol):
    """Speech-to-text provider contract."""

    name: str

    async def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResult: ...


class TranslationProvider(Protocol):
    """Text translation provider contract, independent from transcription."""

    name: str

    async def translate(
        self,
        text: str,
        source_language: str | None,
        target_language: str,
        glossary: list[dict[str, str]],
    ) -> TranslationResult: ...


class TextToSpeechProvider(Protocol):
    """Speech synthesis provider contract, independent from translation."""

    name: str

    async def synthesize(
        self,
        text: str,
        *,
        voice_reference: Path,
        language: str,
        output_path: Path,
        speech_rate: float,
    ) -> None: ...


class MlxWhisperTranscriptionProvider:
    """Optional native Apple Silicon transcription adapter."""

    name = "mlx-whisper"

    def __init__(self, model: str) -> None:
        self.model = model
        self._transcription_lock = asyncio.Lock()

    async def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        async with self._transcription_lock:
            return await asyncio.to_thread(self._transcribe_sync, audio_path, language)

    def _transcribe_sync(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        import mlx_whisper

        started = time.perf_counter()
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=self.model,
            **({"language": language} if language else {}),
        )
        segments = [
            TranscriptWordSegment(
                start_seconds=max(0.0, float(item["start"])),
                end_seconds=max(float(item["start"]), float(item["end"])),
                text=str(item["text"]).strip(),
            )
            for item in result.get("segments", [])
            if isinstance(item, dict) and item.get("text", "").strip()
        ]
        return TranscriptionResult(
            language=result.get("language"),
            segments=segments,
            metrics={
                "inference_seconds": time.perf_counter() - started,
                "chunk_count": 1,
                "timestamp_precision": "segment",
            },
        )


class MlxAudioPlusWorkerTranscriptionProvider:
    """Run mlx-audio-plus in a separate, operator-managed Python environment."""

    name = "mlx-audio-plus-worker"

    def __init__(
        self,
        python_executable: Path,
        model_path: Path,
        timeout_seconds: int,
        worker_script: Path | None = None,
    ) -> None:
        self.python_executable = python_executable
        self.model_path = model_path
        self.timeout_seconds = timeout_seconds
        self.worker_script = worker_script or (
            Path(__file__).resolve().parents[2] / "mlx_audio_worker" / "transcribe.py"
        )
        self._transcription_lock = asyncio.Lock()

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None,
        on_progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        if not audio_path.is_file():
            raise RuntimeError("The transcription worker input audio file does not exist.")
        command = [
            str(self.python_executable),
            str(self.worker_script),
            "--audio-path",
            str(audio_path.resolve()),
            "--model-path",
            str(self.model_path),
        ]
        if language:
            command.extend(["--language", language])

        async with self._transcription_lock:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            if process.stdout is None or process.stderr is None:
                raise RuntimeError("The MLX Audio worker pipes could not be opened.")

            async def read_stdout() -> bytes:
                return await process.stdout.read()

            async def read_stderr() -> bytes:
                tail = bytearray()
                while line := await process.stderr.readline():
                    if on_progress is not None:
                        for match in re.finditer(rb"ACS_PROGRESS:(\d+)", line):
                            await on_progress(min(100, int(match.group(1))))
                    tail.extend(line)
                    if len(tail) > 10_000:
                        del tail[:-10_000]
                return bytes(tail)

            stdout_task = asyncio.create_task(read_stdout())
            stderr_task = asyncio.create_task(read_stderr())
            communicate_task = asyncio.gather(stdout_task, stderr_task)
            try:
                stdout, stderr = await asyncio.wait_for(
                    communicate_task, timeout=self.timeout_seconds
                )
            except TimeoutError:
                self._kill_worker_process_group(process)
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                await process.wait()
                raise RuntimeError("The MLX Audio transcription worker timed out.") from None
            except asyncio.CancelledError:
                self._kill_worker_process_group(process)
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                await process.wait()
                raise
            except Exception:
                self._kill_worker_process_group(process)
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                await process.wait()
                raise

            return_code = await process.wait()
        if return_code:
            logger.error(
                "MLX Audio worker exited with status %s: %s",
                return_code,
                stderr.decode("utf-8", errors="replace")[-2000:],
            )
            raise RuntimeError("The MLX Audio transcription worker failed.")

        try:
            payload = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeError("The MLX Audio worker returned invalid JSON.") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
            raise TypeError("The MLX Audio worker returned an invalid transcript.")

        segments: list[TranscriptWordSegment] = []
        for item in payload["segments"]:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise TypeError("The MLX Audio worker returned an invalid transcript segment.")
            try:
                start = float(item["start"])
                end = float(item["end"])
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError(
                    "The MLX Audio worker returned invalid segment timestamps."
                ) from error
            text = item["text"].strip()
            if not text:
                continue
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                raise RuntimeError("The MLX Audio worker returned invalid segment timestamps.")
            segments.append(TranscriptWordSegment(start, end, text))

        result_language = payload.get("language")
        if result_language is not None and not isinstance(result_language, str):
            raise RuntimeError("The MLX Audio worker returned an invalid language.")
        metrics = payload.get("metrics")
        if metrics is not None and not isinstance(metrics, dict):
            raise RuntimeError("The MLX Audio worker returned invalid processing metrics.")
        return TranscriptionResult(
            language=result_language,
            segments=segments,
            metrics=metrics,
        )

    @staticmethod
    def _kill_worker_process_group(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


class HttpTranslationWorkerProvider:
    """Send text only to an explicitly configured local translation worker."""

    name = "indictrans2-worker"
    supported_languages: tuple[str, ...] = ()

    def __init__(
        self,
        worker_url: str,
        api_token: str,
        timeout_seconds: int,
    ) -> None:
        self.worker_url = worker_url.rstrip("/")
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds

    async def translate(
        self,
        text: str,
        source_language: str | None,
        target_language: str,
        glossary: list[dict[str, str]],
    ) -> TranslationResult:
        if source_language is None:
            raise ValueError("The source transcript language must be set before translation.")
        import httpx

        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(
                    f"{self.worker_url}/translate",
                    headers={"Authorization": f"Bearer {self.api_token}"},
                    json={
                        "text": text,
                        "source_language": source_language,
                        "target_language": target_language,
                        "glossary": glossary,
                    },
                )
                response.raise_for_status()
            except httpx.TimeoutException as error:
                raise RuntimeError("The local translation worker timed out.") from error
            except httpx.HTTPStatusError as error:
                try:
                    error_payload = error.response.json()
                except ValueError:
                    error_payload = {}
                detail = (
                    error_payload.get("detail", "Translation worker request failed.")
                    if isinstance(error_payload, dict)
                    else "Translation worker request failed."
                )
                raise RuntimeError(str(detail)) from error
            except httpx.HTTPError as error:
                raise RuntimeError("The local translation worker could not be reached.") from error

        try:
            payload = response.json()
            translated_text = payload["translated_text"]
            provider = payload["provider"]
            model = payload["model"]
            model_version = payload["model_version"]
            model_license = payload["model_license"]
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("The translation worker returned an invalid response.") from error
        if any(
            not isinstance(value, str) or not value.strip() for value in (translated_text, model)
        ):
            raise RuntimeError(
                "The translation worker returned an empty translation or model name."
            )
        if not all(isinstance(value, str) for value in (provider, model_version, model_license)):
            raise RuntimeError("The translation worker omitted model provenance.")
        return TranslationResult(
            text=translated_text.strip(),
            provider=provider,
            model=model,
            model_version=model_version,
            model_license=model_license,
        )


@dataclass
class VoiceProviderRegistry:
    """Installed providers; absent adapters are reported, never simulated."""

    transcription: TranscriptionProvider | None = None
    translation: TranslationProvider | None = None
    synthesis: TextToSpeechProvider | None = None

    def capability_status(self) -> dict[str, dict[str, object]]:
        return {
            "transcription": {
                "available": self.transcription is not None,
                "provider": self.transcription.name if self.transcription else None,
                "runs_locally": True,
            },
            "translation": {
                "available": self.translation is not None,
                "provider": self.translation.name if self.translation else None,
                "runs_locally": None,
                "supported_languages": list(getattr(self.translation, "supported_languages", ())),
                "candidate_languages": ["en", "hi", "te", "ta", "kn", "ml"],
            },
            "text_to_speech": {
                "available": self.synthesis is not None,
                "provider": self.synthesis.name if self.synthesis else None,
                "runs_locally": None,
            },
            "speaker_diarization": {
                "available": False,
                "provider": None,
                "runs_locally": None,
            },
        }


def create_default_voice_providers(settings: Settings) -> VoiceProviderRegistry:
    """Enable the explicitly selected local provider on supported native hardware."""

    supported_hardware = platform.system() == "Darwin" and platform.machine() in {
        "arm64",
        "aarch64",
    }
    mlx_installed = importlib.util.find_spec("mlx_whisper") is not None
    if settings.voice_transcription_provider == "mlx-audio-plus":
        if not supported_hardware:
            raise RuntimeError("The MLX Audio provider requires native Apple Silicon macOS.")
        if settings.mlx_audio_worker_python is None or settings.mlx_audio_model_path is None:
            raise ValueError(
                "MLX_AUDIO_WORKER_PYTHON and MLX_AUDIO_MODEL_PATH are required "
                "for the mlx-audio-plus provider."
            )
        python_executable = settings.mlx_audio_worker_python.expanduser().absolute()
        model_path = settings.mlx_audio_model_path.expanduser().resolve(strict=True)
        if not python_executable.is_file() or not model_path.is_dir():
            raise ValueError(
                "The configured MLX worker Python or local model directory is invalid."
            )
        required_model_files = ("config.json", "model.safetensors", "multilingual.tiktoken")
        if any(not (model_path / filename).is_file() for filename in required_model_files):
            raise ValueError("The configured local MLX Audio model directory is incomplete.")
        transcription = MlxAudioPlusWorkerTranscriptionProvider(
            python_executable,
            model_path,
            settings.mlx_audio_worker_timeout_seconds,
        )
        if not transcription.worker_script.is_file():
            raise RuntimeError("The isolated MLX Audio worker script is missing.")
    elif settings.voice_transcription_provider == "mlx-whisper":
        if not supported_hardware or not mlx_installed:
            raise RuntimeError(
                "The explicitly selected MLX Whisper provider is not installed "
                "on supported Apple Silicon macOS."
            )
        transcription = MlxWhisperTranscriptionProvider(settings.mlx_whisper_model)
    else:
        transcription = (
            MlxWhisperTranscriptionProvider(settings.mlx_whisper_model)
            if supported_hardware and mlx_installed
            else None
        )
    translation = None
    if settings.translation_worker_url is not None:
        if settings.translation_worker_api_token is None:
            raise ValueError(
                "TRANSLATION_WORKER_API_TOKEN is required when the translation worker URL is set."
            )
        translation = HttpTranslationWorkerProvider(
            str(settings.translation_worker_url),
            settings.translation_worker_api_token.get_secret_value(),
            settings.translation_worker_timeout_seconds,
        )
    return VoiceProviderRegistry(transcription=transcription, translation=translation)
