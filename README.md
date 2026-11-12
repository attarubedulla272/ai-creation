# AI Creator Studio

AI Creator Studio is a modular-monolith foundation for an audio and video
production workspace. The current milestones provide a responsive studio dashboard, a
FastAPI/PostgreSQL foundation for accounts and user-owned projects, authenticated
local media uploads with FFmpeg metadata/derivative processing, a browser timeline
editor with a basic MP4 export, and a provider-backed Voice Studio foundation.
Text-to-speech and voice cloning are not implemented. Translation has an
optional isolated worker integration, but no model weights are installed and no real
translation result or supported language has been verified. No generated AI
results are presented as real.

## Project layout

```text
frontend/       Next.js App Router application
backend/        FastAPI application and Python project configuration
storage/        Local user-asset storage (kept out of source control)
docs/           Product and architecture documentation
infrastructure/ Reserved for local/deployment infrastructure
```

The backend is organized as one modular monolith with versioned API routes,
SQLAlchemy models, and Alembic migrations. PostgreSQL-backed persistence,
registration, bearer-token authentication, and project ownership are wired.
Media processing and timeline export run in separate lightweight asynchronous
worker loops alongside the API process and persist job progress in PostgreSQL.
Redis and Celery are reserved for a future separately deployed worker.

## Run locally

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Run `npm run lint` and
`npm run build` to validate the frontend.

### Backend

Python 3.11 or newer is required. From the `backend` directory, install the
project and its development tools with `uv sync --extra dev`, then start the
API. Install uv first if it is not available (`brew install uv` on macOS).
FFmpeg and FFprobe are required for media processing (`brew install ffmpeg`
on macOS).
Create a PostgreSQL database, copy `.env.example` to `.env`, then set
`DATABASE_URL` to that database and set `JWT_SECRET_KEY` to a random secret of
at least 32 characters (for example, generate one with `openssl rand -hex 32`):

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

If `uv` is not installed, create a new virtual environment and use pip instead:

```bash
cd backend
python3 -m venv .venv-media
source .venv-media/bin/activate
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Keep the API running while using server uploads. Set `CORS_ORIGINS` in `.env`
to include the exact frontend origin (for example
`http://127.0.0.1:3101` if Next.js is running on port 3101). The media page can
register/sign in to the local API; its short-lived bearer token is held only in
the current browser session.

The liveness endpoints are available at
[http://localhost:8000/health](http://localhost:8000/health) and
[http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health).
Interactive API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs).
The liveness check does not imply database readiness; database-backed requests
return a structured service-unavailable error if `DATABASE_URL` is unset.

Authentication endpoints are `POST /api/v1/auth/register`,
`POST /api/v1/auth/login`, and `GET /api/v1/auth/me`. Login returns a
short-lived bearer token. Create, list, and retrieve projects with
`/api/v1/projects`; every project operation is scoped to the authenticated
owner. Use the `Authorize` control in `/docs` to test protected endpoints.

Media endpoints are `POST /api/v1/media` (multipart upload), `GET
/api/v1/media`, `GET /api/v1/media/{id}`, `GET /api/v1/media/{id}/download`,
`DELETE /api/v1/media/{id}`, and `GET /api/v1/media/jobs/{job_id}`. The API
checks extension, declared MIME type, file signature, and the configurable
`MAX_UPLOAD_SIZE_BYTES` limit. Each accepted upload gets a generated storage
key and a queued job; FFprobe metadata, video thumbnails, lower-resolution
proxies, extracted audio, and audio waveform images are produced asynchronously
when applicable. Generated outputs can be fetched from
`/api/v1/media/{id}/derivatives/{thumbnail|proxy|extracted_audio|waveform}`.
Storage defaults to `../storage` from the backend working directory. All file
and job access is restricted to their owner.

The Video Studio connects to the local API and loads authenticated projects
and media. Timeline documents are saved as structured JSON on the project's
timeline record with a 750 ms autosave delay. The editor supports clip
placement, movement, splitting, trimming, deleting, track mute/lock, snapping,
zoom, playhead preview, and undo/redo. Timeline endpoints are
`GET|PUT /api/v1/projects/{project_id}/timeline`,
`POST /api/v1/projects/{project_id}/timeline/export`, and
`GET /api/v1/timeline/exports/{job_id}`. Export downloads use
`GET /api/v1/timeline/exports/{job_id}/download`.

The current MP4 renderer concatenates the selected video clip, or all
video-track clips when nothing is selected, normalizes them to the timeline's
frame size/rate, and optionally adds the first unmuted audio-track clip. It
does not render overlays, subtitles,
effects, transitions, source-video audio, or timeline gaps/overlaps. FFmpeg
must be installed locally; export status is available from the job endpoint.

### Voice Studio

The Voice Studio is available at `/voice-studio` after signing in to the local
backend. Its API is under `/api/v1/voice`. Voice references require an explicit
user authorization attestation and an owned audio asset. The attestation is
not independent identity or permission verification; revoked consent removes
the profile from future assignments. A saved profile is reference metadata
only, not a cloned voice.

On Apple Silicon macOS, install the optional native transcription provider
from `backend` with:

```bash
uv sync --extra dev --extra voice-mlx
```

The `voice-mlx` extra is limited to Apple Silicon macOS; Linux and Docker
installations do not install MLX packages. The standard backend setup remains
`uv sync --extra dev`. When syncing again on your Mac, include both extras or
uv will remove optional packages that were not selected. MLX must run directly
on macOS, not in Linux Docker. This installs the Python provider dependencies
only; it does not download Whisper model weights. The app queues audio
transcription as a background job, saves timestamped segments, permits manual
transcript and speaker-label editing, and exports SRT/VTT subtitles. Video
transcription is available after the media worker has extracted its audio.
The optional IndicTrans2 translation worker is implemented separately from
the main backend and MLX transcription environment. It has no model weights
or translation packages installed by default, downloads no weights
automatically, and reports no verified supported languages. Translation text
can still be entered and reviewed manually. Candidate targets are English,
Hindi, Telugu, Tamil, Kannada, and Malayalam; the selected distilled
checkpoints cover English↔Indic only, not Indic↔Indic. Speaker diarization
remains unavailable.

To provision the separate translation worker, first review
[`docs/TRANSLATION_QUALITY_REPORT.md`](docs/TRANSLATION_QUALITY_REPORT.md) and
[`docs/MODEL_LICENSE_AUDIT.md`](docs/MODEL_LICENSE_AUDIT.md). The selected
AI4Bharat IndicTrans2 checkpoints are gated; accept Hugging Face's access
conditions yourself. Their pinned Safetensors files total about 1.87 GiB,
before tokenizer/code files and inference memory. The isolated worker
dependencies have been provisioned in `backend/translation_worker/.venv`
after approval; the model weights have not been downloaded. The main backend
and MLX environments were not changed. Recreate the isolated environment with:

```bash
uv sync --project backend/translation_worker
```

Download each pinned snapshot manually to a directory named by its revision
SHA. Audit the included custom model Python code before loading it with
`trust_remote_code`:

```bash
hf download ai4bharat/indictrans2-en-indic-dist-200M \
  --revision 2cfd0a20057756d756bf3e53528f492afc52f91a \
  --local-dir "$HOME/.cache/acs-translations/2cfd0a20057756d756bf3e53528f492afc52f91a" \
  --include '*.json' '*.py' 'model.*' 'LICENSE' \
  --exclude 'pytorch_model.bin'
hf download ai4bharat/indictrans2-indic-en-dist-200M \
  --revision d66a2122ad6d28184f3dc3797b652bd80ae3f65f \
  --local-dir "$HOME/.cache/acs-translations/d66a2122ad6d28184f3dc3797b652bd80ae3f65f" \
  --include '*.json' '*.py' 'model.*' 'LICENSE' \
  --exclude 'pytorch_model.bin'
```

After auditing the files, set the two local snapshot paths and a strong shared
worker token in the worker process environment. Set the same token and
`TRANSLATION_WORKER_URL=http://127.0.0.1:8010` in `backend/.env`, then run the
worker from `backend/translation_worker` bound to localhost:

```bash
export INDICTRANS_EN_INDIC_MODEL_PATH="$HOME/.cache/acs-translations/2cfd0a20057756d756bf3e53528f492afc52f91a"
export INDICTRANS_INDIC_EN_MODEL_PATH="$HOME/.cache/acs-translations/d66a2122ad6d28184f3dc3797b652bd80ae3f65f"
export TRANSLATION_WORKER_API_TOKEN='use-the-same-random-token-as-backend-env'
uv run uvicorn app:app --host 127.0.0.1 --port 8010
```

The worker's `/health` endpoint reports configured model directions, not
translation quality. The frontend continues to label languages as candidates
until real translation tests pass. API routes include
`POST /api/v1/voice/dubbing-projects/{id}/translate`,
`POST /api/v1/voice/dubbing-projects/{id}/segments/{segment_id}/translate`,
and the existing voice-job status, cancel, and retry endpoints. Translation
jobs preserve timestamps and source text, persist provenance and per-segment
status, and allow manual corrections and approvals. Backend tests use a fake
provider and do not establish translation quality. See the quality report for
reference-data and real-inference limitations.
The attempted real-inference setup and authentication blocker are recorded in
[`docs/INDICTRANS2_REAL_INFERENCE_REPORT.md`](docs/INDICTRANS2_REAL_INFERENCE_REPORT.md).

Dubbing projects persist translated text, approved reference assignments,
timing adjustments, and a speech-rate control. There is no TTS/voice-cloning
provider or generated speech preview. The current FFmpeg audio export only
assembles audio files uploaded and assigned by the user; it does not translate
or synthesize speech. Output metadata identifies it as user-supplied audio.
Export uses the complete supplied clips instead of truncating them to planned
segment slots, reports timing conflicts, and can optionally mux the assembled
audio into an owned project video while copying its video stream. The original
video audio is replaced; subtitles remain separate SRT/VTT downloads. See the
[Voice Studio and dubbing architecture](docs/VOICE_DUBBING_ARCHITECTURE.md) for
provider boundaries, persistence, API routes, and verified limitations.

Native MLX test on an M2 Mac with 8 GB unified memory (Python 3.13,
`mlx-whisper` 0.4.3, `mlx` 0.32.4): a locally generated short English speech WAV produced the
recognized text “This is a test of short English speech recognition.” with one
timestamped segment. `mlx-whisper` package metadata declares MIT. The upstream
`openai/whisper-tiny` model card declares Apache-2.0, but the tested
`mlx-community/whisper-tiny` conversion card does not declare a license; verify
the converted weights' provenance and commercial-use terms before commercial
deployment. The upstream Apache-2.0 license permits commercial use subject to
its terms and notice requirements; those terms cannot be assumed for the
converted weights without confirmation. The tiny model is downloaded separately
and is not bundled with the application.

The alternative `mlx-community/whisper-tiny-fp16` model uses `mlx-audio-plus`,
not `mlx-whisper`. Its model card declares Apache-2.0 and its repository files
total about 71.7 MiB. The optional adapter is isolated from the FastAPI
environment because the published `mlx-audio-plus` dependencies are broad and
can downgrade packages used by the backend. On Apple Silicon macOS, install
its separate environment from the repository root with:

```bash
uv sync --project backend/mlx_audio_worker
```

This is a separate, optional environment. On this Mac, its dry run resolved
78 packages and the installed environment contains 66 distributions. Review
its dependency footprint before installing; it does not affect the FastAPI
environment. The worker project excludes the conflicting upstream
`mlx-audio[all]` wheel, which otherwise overwrites the Plus package's STT
module. Installing Python packages does not fetch model weights. The worker only accepts a
complete local model directory and never accepts a Hugging Face repository
ID. To opt in after installing the worker dependencies, set these values in
`backend/.env` (paths are relative to the backend working directory unless
absolute):

```dotenv
VOICE_TRANSCRIPTION_PROVIDER=mlx-audio-plus
MLX_AUDIO_WORKER_PYTHON=mlx_audio_worker/.venv/bin/python
MLX_AUDIO_MODEL_PATH=/path/to/local/whisper-tiny-fp16
```

The alternate worker passed a real 10.8-second local speech inference on an
M2 Mac. Its actual transcription and timing are documented in
[`docs/MLX_TRANSCRIPTION_TEST.md`](docs/MLX_TRANSCRIPTION_TEST.md). The model
card declares Apache-2.0; the approved weights remain in the local Hugging Face
cache and are not bundled with the application. Review license details and
limitations in [`docs/MODEL_LICENSE_AUDIT.md`](docs/MODEL_LICENSE_AUDIT.md).

### Content Studio and Script-to-Film

The Content Studio at `/content-studio` uses authenticated project data from the
local backend. It persists the project idea, outline, script, visual settings,
character identities and outfits, character image references, environments,
scene plans, shot lists, camera and lighting directions, first/last-frame
references, approval state, and continuity notes. Use the existing Media
Library to upload reference images and real video assets. Content Studio can
attach uploaded images and use uploaded videos on shots; storyboard assembly
creates a saved Video Studio timeline only from approved scenes with real,
owned video assets. It does not render the final video; use the existing
timeline export workflow.

The supported style presets are realistic, cinematic, documentary, 2D
animation, 3D animation, anime, cartoon, map animation, and product commercial.
Scene generation is queued one scene at a time, so regenerating one scene does
not replace other scenes. No real video generation provider is configured by
default. The optional mock provider requires `ENABLE_MOCK_SCENE_PREVIEW=true`;
it only returns explicitly labeled text preview data and never creates image
or video media. A self-hosted GPU worker can later implement the
`SceneGenerationProvider` contract. AI research, script writing, storyboard
image generation, and final video assembly rendering are not implemented.

Content endpoints are under `/api/v1/projects/{project_id}`: `GET|PUT
/content`, character and environment CRUD, scene and shot CRUD,
`POST /scenes/{scene_id}/generate`, `GET /continuity`, and
`POST /storyboard/assemble`. Poll scene jobs at
`GET /api/v1/content/jobs/{job_id}`. Existing unassigned user media and media
assigned to the current project can be used as references; assets assigned to
another project are rejected.

### Smart Clipper

The authenticated workspace at `/smart-clipper` analyzes a project-owned
source video without modifying it. Analysis is queued and uses FFprobe,
PySceneDetect, and an existing completed project transcript; if no transcript
exists, it uses the optional local transcription provider when installed.
Transcript windows are ranked with editable, explainable heuristic factors;
they are suggestions, not predictions of virality. Users can edit boundaries,
review captions, manually set crop position, approve/reject candidates, find
matching footage in the same project, and queue batch MP4 exports.

The API is under `/api/v1/clipper`: `POST /analyses`,
`GET /analyses/{job_id}`, `GET /projects/{project_id}/candidates`,
`PATCH /projects/{project_id}/ranking`, candidate boundary/status/caption/
framing endpoints, `GET /projects/{project_id}/b-roll`, `POST /exports`,
`GET /jobs/{job_id}`, and job retry/cancel endpoints. Analysis and export
status is persisted in the existing `processing_jobs` table. Candidate scores,
scene associations, captions, framing, and exported-asset references are
stored in `clip_candidates`; apply the Alembic migrations before use.

Exports use FFmpeg in the background and produce owned project media assets.
Captions are selectable MP4 `mov_text` subtitles; this FFmpeg build does not
burn styled captions into the video, and caption appearance controls are saved
as metadata rather than rendered styling. Watermarks are overlaid into the
video. Face-aware tracking, automatic translation, and model-based highlight
analysis are not implemented; manual crop positioning and transcript-based
heuristics are used instead.

### SEO & Publish Studio

The authenticated workspace at `/seo-publish` saves project release metadata,
version history, and local planned publication dates. It supports title and
description editing, tags/hashtags/keywords, ordered chapters, language and
category fields, and associations to owned video, clip, and thumbnail assets.
Rule-based title ideas are generated from user-supplied text; they are not AI
outputs and do not include search-volume or ranking claims.

Thumbnail images can be uploaded to the media library and rendered locally
with Pillow at 1280×720, 1080×1080, or 1080×1920. Crop center, title text,
size, color, and position can be adjusted. Calendar entries are local plans;
they are not published to a social platform.

The `/api/v1/publishing` API provides publication create/list/update, revisions, calendar,
capability status, title suggestions, and thumbnail rendering. Optional YouTube
OAuth, resumable uploads, thumbnail upload, and channel analytics use official
Google endpoints. Configure `YOUTUBE_OAUTH_CLIENT_ID`,
`YOUTUBE_OAUTH_CLIENT_SECRET`, the exact registered
`YOUTUBE_OAUTH_REDIRECT_URI`, `YOUTUBE_OAUTH_FRONTEND_RETURN_URL`, and a stable
Fernet `YOUTUBE_TOKEN_ENCRYPTION_KEY` in the backend environment. The values in
`.env.example` are blank placeholders; never put real credentials in source
control. The Google callback URI must match the Google Cloud OAuth client
exactly. Uploads and analytics remain unavailable until the backend is
configured and the user grants channel-specific consent. No external OAuth,
upload, or analytics flow has been manually verified for this workspace.

The YouTube API stores refresh tokens encrypted in the backend, uses a
single-use PKCE-protected OAuth state, uploads only when the user explicitly
queues a release, and records the external video ID only after Google confirms
the upload. Local calendar dates are not treated as platform schedules.
See the [YouTube integration report](./docs/YOUTUBE_INTEGRATION_REPORT.md) for
scopes, setup, endpoints, quota limits, verification status, and limitations.

### AI video generation worker

The backend runs a persisted job coordinator independent of the frontend.
Scene jobs retain queued, processing, completed, failed, and cancelled state,
progress, retry counts, model name/version/license, commercial-use status,
generation mode/settings, worker job ID, and output metadata. Text-to-video
and image-to-video requests use one provider contract; image-to-video requires
an uploaded first-frame image. Reference images (including character and
environment references) are sent to the configured worker as short-lived,
project/asset-scoped signed backend URLs. A completed MP4 is streamed back to
local storage, size-limited, FFprobe-validated, and attached to its scene as
an owned project media asset.

The mock worker only simulates the job lifecycle and emits a labeled text
preview; it never creates media. To connect a separately deployed GPU worker,
set `GENERATION_WORKER_URL`, optionally set `GENERATION_WORKER_API_TOKEN`, and
set `PUBLIC_API_BASE_URL` to a backend address reachable by the worker. Model
weights are installed manually on the external worker; the backend does not
download large weights or run them on the development Mac. The registry marks
operator-configured model licensing and commercial use as unverified/disabled
until checked. See [the worker API contract](./docs/gpu-worker-contract.md) for
the request, polling, cancellation, reference-download, and MP4-output format.

Run backend tests and lint from `backend` with `uv run pytest` and
`uv run ruff check app migrations tests`. Tests use isolated SQLite databases;
the application itself expects PostgreSQL. The Python dependencies are also
installable with `python -m pip install -e ".[dev]"` from `backend`.

To create a follow-up migration after changing models, set `DATABASE_URL` in
`.env` and run `uv run alembic revision --autogenerate -m "describe change"`,
then inspect the generated migration before applying it with
`uv run alembic upgrade head`.

## Local-first constraints

- The foundation requires no paid AI API or provider credentials.
- Keep large video-generation models off the development Mac; advanced
  generation will be an optional external GPU-worker integration.
- Local media belongs in `storage/`, not in application source.
- Before integrating a model, document its code/model licenses, commercial-use
  terms, hardware needs, and attribution requirements.
- MLX Whisper is an optional native macOS dependency; it is not installed for
  the standard backend setup and must not run inside Linux Docker.

## Project audit

See the [Milestones 1–8 project audit](./docs/PROJECT_AUDIT.md),
[test report](./docs/MILESTONES_1_TO_8_TEST_REPORT.md), and
[model/license audit](./docs/MODEL_LICENSE_AUDIT.md) for verified scope,
limitations, and remaining work.
