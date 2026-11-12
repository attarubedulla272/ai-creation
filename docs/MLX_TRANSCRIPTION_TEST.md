# MLX Audio Plus transcription test

## Result

Real transcription succeeded on the native Apple Silicon Mac using the
`mlx-audio-plus` worker, not a mock provider.

| Item | Result |
|---|---|
| Model | `mlx-community/whisper-tiny-fp16` |
| Model snapshot | `c8c5417d20aca5049e6a6b07bede74a316618542` |
| Model license | Apache-2.0, as declared in the Hugging Face model metadata and card |
| Model files | 74,386,126-byte `model.safetensors`, 816,730-byte `multilingual.tiktoken`, and small configuration files; about 75.2 MB / 71.7 MiB total |
| Runtime | `mlx-audio-plus` 0.1.8, MLX 0.32.4, Python 3.13.9 |
| Hardware | Apple Silicon Mac M2, 8 GB unified memory |
| Selected provider | `mlx-audio-plus-worker` |
| Direct provider audio duration | 10.818875 seconds |
| Direct provider call | 2.866 seconds, including worker startup and model loading; warm local runtime/cache |
| FastAPI integration audio duration | 19.097 seconds |
| FastAPI transcription job | 3.619 seconds from enqueue through completed job and persisted transcript |
| Outcome | Real inference completed; both runs returned timestamped segments |

The Apache-2.0 declaration applies to this converted model repository. The
runtime package separately declares MIT; these are distinct licenses. Preserve
model notices when redistributing and review upstream attribution obligations
for commercial distribution.

## Installation versus model download

The worker's locked Python environment is separate from the FastAPI
environment at `backend/mlx_audio_worker/.venv`. It uses
`mlx-audio-plus==0.1.8`; the backend environment was not modified. The
`mlx-audio-plus` wheel's published dependency metadata also names
`mlx-audio[all]`, which installs overlapping `mlx_audio` modules. The worker
project excludes that conflicting distribution and uses the bundled Whisper
implementation directly. The locked worker environment contains 66 installed
distributions on this machine.

The Python dependency install did not fetch model weights. After explicit
approval, only the model's `config.json`, `model.safetensors`, and
`multilingual.tiktoken` files were downloaded to the local Hugging Face cache.
The model was not copied into the repository. No paid API was used.

Provider selection was separately verified by constructing the backend
registry with `VOICE_TRANSCRIPTION_PROVIDER=mlx-audio-plus` and local paths for
the worker interpreter and model directory. The registry selected
`mlx-audio-plus-worker`; the configured backend subprocess then performed the
actual inference.

## FastAPI upload, processing, and persistence verification

A second, locally generated 19.097-second speech WAV was submitted through
the application flow using a temporary SQLite database:

1. The authenticated media API accepted the WAV and stored 611,176 bytes in
   the configured local storage service.
2. `POST /api/v1/voice/transcriptions` enqueued a transcription job.
3. The application worker selected the isolated `mlx-audio-plus-worker`
   provider and ran real MLX inference against the cached local model.
4. The job completed in 3.619 seconds from enqueue to completion.
5. `GET /api/v1/voice/transcripts/{transcript_id}` returned the persisted
   transcript and five timestamped segments.

Detected language was English (`en`). The actual stored transcript was:

| Start | End | Recognized text |
|---:|---:|---|
| 0.00 s | 4.24 s | This is a longer and two-end transcription test for AI Creator Studio. |
| 4.24 s | 8.20 s | The speech recording is created locally on this Apple Silicon Mac. |
| 8.20 s | 14.28 s | Uploaded only to the local development API, processed by the isolated MLX audio worker, |
| 14.28 s | 16.60 s | and saved as a timestamped transcript. |
| 16.60 s | 19.08 s | No audio is sent to any external service. |

This confirms the isolated adapter, FastAPI queue/worker path, local asset
storage, and transcript database persistence work together. Language detection
was used for this run rather than forcing a language. The temporary SQLite
database, storage, and test recording were removed after verification; the
approved model remains cached locally.

## Local test audio and transcription

The 10.8-second test WAV was generated locally with macOS `say` and converted
to mono 16 kHz PCM with FFmpeg. It was not uploaded or sent to an external
service. Spoken test text:

> This is a local transcription test for AI Creator Studio. The quick brown
> fox jumps over the lazy dog. Please transcribe this sentence and return
> accurate timestamps for the spoken words.

Actual result, including segment timing:

| Start | End | Recognized text |
|---:|---:|---|
| 0.00 s | 6.32 s | This is a local transcription test for AI Creator Studio, the Quick Brown Fox jumps over the lazy dog. |
| 6.32 s | 10.88 s | Please transcribe this sentencing return accurate timestamps for the spoken words. |

The recognized phrase “this sentencing return” differs from the spoken
“this sentence and return”; the short test confirms execution and timestamped
output, not perfect recognition accuracy. The output segments are chunk-level
timestamps, not word-level alignment.

## Integration findings

Initial real runs exposed two packaging/runtime issues, both corrected before
the successful run:

- The Plus and upstream `mlx-audio` wheels shared the `mlx_audio` namespace;
  the upstream wheel overwrote the Plus STT module. The isolated worker lock
  now excludes the conflicting upstream distribution.
- Resolving the worker's `.venv/bin/python` symlink changed it to the system
  Python and lost the isolated packages. The backend now preserves the
  configured interpreter path.
- The model card's example `from mlx_audio.stt import transcribe` does not
  match the published 0.1.8 wheel. The worker calls the bundled Whisper
  `Model.from_pretrained` implementation with the validated local model
  directory, so it does not pass a Hub repo ID to inference.

No error occurred in the final measured provider runs. Each test WAV was kept
local for the run and then removed; the approved model remains in the local
Hugging Face cache. Backend dependencies and the backend lockfile were not
modified for the isolated runtime.
