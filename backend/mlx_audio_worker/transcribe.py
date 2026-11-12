"""Local-only, chunked transcription adapter for the mlx-audio-plus Whisper model."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import platform
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SAMPLE_RATE = 16_000
DEFAULT_CHUNK_SECONDS = 60.0
DEFAULT_OVERLAP_SECONDS = 3.0
MAX_AUDIO_SECONDS = 86_400.0
WORD_PATTERN = re.compile(r"\w+", re.UNICODE)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe local audio using MLX Audio.")
    parser.add_argument("--audio-path", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--language")
    parser.add_argument("--chunk-seconds", type=float, default=DEFAULT_CHUNK_SECONDS)
    parser.add_argument("--overlap-seconds", type=float, default=DEFAULT_OVERLAP_SECONDS)
    return parser


def _validate_local_inputs(audio_path: Path, model_path: Path) -> tuple[Path, Path]:
    audio = audio_path.expanduser().resolve(strict=True)
    model = model_path.expanduser().resolve(strict=True)
    if not audio.is_file():
        raise ValueError("The supplied media path is not a file.")
    if not model.is_dir():
        raise ValueError("The model must be an already-downloaded local directory.")
    required_model_files = ("config.json", "model.safetensors", "multilingual.tiktoken")
    if any(not (model / filename).is_file() for filename in required_model_files):
        raise ValueError("The local model directory is incomplete.")
    return audio, model


def _run_command(arguments: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{Path(arguments[0]).name} exceeded its time limit.") from error


def _media_duration(audio_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError("FFprobe is required to inspect local audio and video.")
    result = _run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(audio_path),
        ],
        timeout_seconds=120,
    )
    if result.returncode:
        raise RuntimeError("FFprobe could not inspect the supplied media.")
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
        has_audio = any(
            stream.get("codec_type") == "audio" for stream in payload.get("streams", [])
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "The supplied media has no readable audio stream or duration."
        ) from error
    if not has_audio or not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("The supplied media must contain a non-empty audio stream.")
    if duration > MAX_AUDIO_SECONDS:
        raise RuntimeError("Audio longer than 24 hours is not supported.")
    return duration


def _chunk_windows(
    duration: float,
    chunk_seconds: float,
    overlap_seconds: float,
) -> list[tuple[float, float, float, float]]:
    if not math.isfinite(chunk_seconds) or chunk_seconds <= 0:
        raise ValueError("Chunk duration must be a positive finite number.")
    if not math.isfinite(overlap_seconds) or overlap_seconds < 0:
        raise ValueError("Chunk overlap must be a non-negative finite number.")
    if overlap_seconds * 2 >= chunk_seconds:
        raise ValueError("Chunk overlap must be less than half the chunk duration.")

    windows = []
    core_start = 0.0
    while core_start < duration:
        core_end = min(duration, core_start + chunk_seconds)
        decode_start = max(0.0, core_start - overlap_seconds)
        decode_end = min(duration, core_end + overlap_seconds)
        windows.append((decode_start, decode_end, core_start, core_end))
        core_start = core_end
    return windows


def _normalize_chunk(
    source_path: Path,
    output_path: Path,
    decode_start: float,
    decode_end: float,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required to normalize audio for transcription.")
    result = _run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{decode_start:.6f}",
            "-i",
            str(source_path),
            "-t",
            f"{decode_end - decode_start:.6f}",
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            "-y",
            str(output_path),
        ],
        timeout_seconds=max(120.0, (decode_end - decode_start) * 4),
    )
    if result.returncode or not output_path.is_file() or output_path.stat().st_size <= 44:
        raise RuntimeError("FFmpeg could not normalize the audio chunk.")


def _result_payload(result: Any) -> dict[str, Any]:
    raw_segments = getattr(result, "segments", None)
    if not isinstance(raw_segments, list):
        raise TypeError("The MLX Audio model returned no segment list.")
    segments = []
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(
                "The MLX Audio model returned invalid segment timestamps."
            ) from error
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise RuntimeError("The MLX Audio model returned invalid segment timestamps.")
        segments.append({"start": start, "end": end, "text": text.strip()})
    language = getattr(result, "language", None)
    if language is not None and not isinstance(language, str):
        raise ValueError("The MLX Audio model returned an invalid language.")
    return {"language": language, "segments": segments}


def _word_tokens(text: str) -> list[re.Match[str]]:
    return list(WORD_PATTERN.finditer(text))


def _deduplicate_boundary_text(
    previous_text: str,
    current_text: str,
    allow_single_word: bool = False,
) -> str:
    previous_words = _word_tokens(previous_text)
    current_words = _word_tokens(current_text)
    max_overlap = min(len(previous_words), len(current_words))
    duplicate_count = 0
    for count in range(max_overlap, 0, -1):
        previous_suffix = [match.group().casefold() for match in previous_words[-count:]]
        current_prefix = [match.group().casefold() for match in current_words[:count]]
        if previous_suffix == current_prefix:
            duplicate_count = count
            break
    if duplicate_count == 0:
        return current_text
    if (
        duplicate_count < 2
        and not allow_single_word
        and not (
            len(previous_words) == len(current_words) == 1
            and previous_words[0].group().casefold() == current_words[0].group().casefold()
        )
    ):
        return current_text
    remainder = current_text[current_words[duplicate_count - 1].end() :]
    return remainder.lstrip(" \t\r\n,.;:!?，。！？、")


def _merge_chunk_segments(
    chunks: list[tuple[float, float, float, float, bool, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Shift chunk-relative times, select each segment's owning core, and deduplicate seams."""
    merged: list[tuple[dict[str, Any], int]] = []
    for chunk_index, (decode_start, _, core_start, core_end, is_last, raw_segments) in enumerate(
        chunks
    ):
        for raw in raw_segments:
            start = decode_start + float(raw["start"])
            end = decode_start + float(raw["end"])
            midpoint = (start + end) / 2
            if midpoint < core_start or (midpoint > core_end if is_last else midpoint >= core_end):
                continue
            merged.append(
                (
                    {
                        "start": max(0.0, start),
                        "end": max(start, end),
                        "text": str(raw["text"]).strip(),
                    },
                    chunk_index,
                )
            )

    merged.sort(key=lambda item: (item[0]["start"], item[0]["end"], item[1]))
    deduplicated: list[tuple[dict[str, Any], int]] = []
    for current, chunk_index in merged:
        current_text = current["text"]
        for previous, previous_chunk in reversed(deduplicated[-4:]):
            if previous_chunk == chunk_index:
                continue
            overlaps_in_time = (
                current["start"] < previous["end"] and current["end"] > previous["start"]
            )
            near_boundary = abs(current["start"] - previous["end"]) <= 1.0
            if not overlaps_in_time and not near_boundary:
                continue
            current_text = _deduplicate_boundary_text(
                previous["text"],
                current_text,
                allow_single_word=overlaps_in_time,
            )
            if not current_text:
                break
        if current_text:
            current["text"] = current_text
            deduplicated.append((current, chunk_index))
    return [segment for segment, _ in deduplicated]


def transcribe(
    audio_path: Path,
    model_path: Path,
    language: str | None,
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
) -> dict[str, Any]:
    audio, model_directory = _validate_local_inputs(audio_path, model_path)
    total_started = time.perf_counter()
    duration = _media_duration(audio)
    windows = _chunk_windows(duration, chunk_seconds, overlap_seconds)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required to normalize audio for transcription.")

    with contextlib.redirect_stdout(sys.stderr):
        from mlx_audio.stt.models.whisper import Model

        model_load_started = time.perf_counter()
        model = Model.from_pretrained(str(model_directory))
        model_load_seconds = time.perf_counter() - model_load_started

    chunks = []
    detected_languages: list[str] = []
    normalization_seconds = 0.0
    inference_seconds = 0.0
    with tempfile.TemporaryDirectory(prefix="acs-mlx-audio-") as directory:
        temporary = Path(directory)
        for index, (decode_start, decode_end, core_start, core_end) in enumerate(windows):
            chunk_path = temporary / f"chunk-{index:05d}.wav"
            normalization_started = time.perf_counter()
            _normalize_chunk(audio, chunk_path, decode_start, decode_end)
            normalization_seconds += time.perf_counter() - normalization_started

            inference_started = time.perf_counter()
            with contextlib.redirect_stdout(sys.stderr):
                result = model.generate(
                    str(chunk_path),
                    language=language,
                    verbose=False,
                    condition_on_previous_text=False,
                )
            inference_seconds += time.perf_counter() - inference_started
            payload = _result_payload(result)
            if payload["language"]:
                detected_languages.append(payload["language"])
            chunks.append(
                (
                    decode_start,
                    decode_end,
                    core_start,
                    core_end,
                    index == len(windows) - 1,
                    payload["segments"],
                )
            )
            progress = round((index + 1) / len(windows) * 100)
            print(f"ACS_PROGRESS:{progress}", file=sys.stderr, flush=True)

    merge_input = [
        (decode_start, decode_end, core_start, core_end, is_last, segments)
        for decode_start, decode_end, core_start, core_end, is_last, segments in chunks
    ]
    segments = _merge_chunk_segments(merge_input)
    if detected_languages:
        language_counts = {code: detected_languages.count(code) for code in set(detected_languages)}
        selected_language = max(language_counts, key=language_counts.get)
    else:
        selected_language = language
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() != "Darwin":
        peak_rss *= 1024
    return {
        "language": selected_language,
        "segments": segments,
        "metrics": {
            "audio_duration_seconds": duration,
            "chunk_count": len(windows),
            "chunk_seconds": chunk_seconds,
            "overlap_seconds": overlap_seconds,
            "model_load_seconds": model_load_seconds,
            "inference_seconds": inference_seconds,
            "normalization_seconds": normalization_seconds,
            "total_seconds": time.perf_counter() - total_started,
            "peak_process_rss_bytes": peak_rss,
            "detected_languages": detected_languages,
            "timestamp_precision": "segment",
        },
    }


def main() -> int:
    arguments = create_parser().parse_args()
    audio, model = _validate_local_inputs(arguments.audio_path, arguments.model_path)
    payload = transcribe(
        audio,
        model,
        arguments.language,
        arguments.chunk_seconds,
        arguments.overlap_seconds,
    )
    print(json.dumps(payload, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Transcription failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
