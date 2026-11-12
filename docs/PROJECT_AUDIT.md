# AI Creator Studio: Milestones 1–8 project audit

Audit performed on 2026-11-12 against the repository in this workspace. The
workspace is not a Git repository, so tracked/untracked status and a complete
pre-existing change list could not be established.

## Architecture found

- **Frontend:** Next.js App Router, React, TypeScript, Lucide, and global CSS.
  The ten studio routes share a persistent shell. Several foundation and
  publishing views are explicitly demonstration-only; the Video, Voice,
  Content, Media, and Smart Clipper workspaces have backend clients.
- **Backend:** FastAPI application factory in `backend/app/main.py`; the
  `/api/v1` router includes health, auth, projects, media, timeline, voice,
  content, generation model registry, and Smart Clipper endpoints. FastAPI
  OpenAPI contains 70 paths with no duplicate paths.
- **Persistence:** Async SQLAlchemy 2 models are imported by
  `backend/app/models/__init__.py`; Alembic's `migrations/env.py` loads their
  metadata. The registry exposes 19 tables. PostgreSQL is the configured
  application database; isolated API tests use SQLite.
- **Background processing:** Media, timeline export, voice, content, and Smart
  Clipper jobs are persisted as `ProcessingJob` rows and handled by
  application-lifespan asyncio polling workers. Celery/Redis packages and a
  `REDIS_URL` setting exist, but no active Celery worker or Redis broker
  integration was found.
- **Media:** `LocalStorage` uses application-generated relative keys and
  rejects traversal. FFprobe/FFmpeg handle metadata, derivatives, transcript
  audio, timeline export, and Smart Clipper export. Local media lives under
  `storage/`.
- **AI/provider boundaries:** MLX Whisper is an optional native macOS
  transcription provider. Translation and speech synthesis are interfaces
  without providers. Scene generation has an optional external HTTP worker
  adapter and an explicitly labeled text-only development mock. No paid AI
  provider is mandatory.
- **Infrastructure:** `infrastructure/` has no files; no Dockerfile or Compose
  configuration was found. The repository has no frontend end-to-end test
  runner configured.

## Milestone 1–8 implementation status

`COMPLETE` means the scoped implementation has test evidence; `PARTIAL` means
important requested behavior is absent, demonstration-only, or blocked;
`MISSING` means no implementation was found; `BLOCKED` means it could not be
verified because a required dependency, credential, service, or hardware
resource is unavailable.

| Milestone | Status | Evidence and remaining scope |
|---|---|---|
| 1 — Responsive frontend foundation | PARTIAL | All ten routes load; project demo creation works in browser storage; responsive route smoke checks pass at 390/768/1280 px after the tablet fix. Dashboard samples, account/settings, storage use, and publishing are not connected to backend persistence. |
| 2 — FastAPI/PostgreSQL foundation | PARTIAL | Auth, ownership, projects, schemas, API errors, 19 models, and six migrations are present; SQLite API tests and migration round-trip pass. PostgreSQL service accepts TCP, but the configured login is rejected (`SQLSTATE 28000`); PostgreSQL migration/integration is not verified. |
| 3 — Media and FFmpeg | COMPLETE | Video/audio/image upload, extension/MIME/signature/size checks, generated storage keys, ownership, FFprobe, derivatives, status, failure handling, and traversal tests pass with local FFmpeg. |
| 4 — Video editor | PARTIAL | Timeline JSON persists and reloads; editor controls and an FFmpeg timeline export are implemented and covered. Renderer explicitly omits overlays, subtitles, effects, transitions, source-video audio, gaps, and overlaps; export uses only its supported compatible clip/audio path. |
| 5 — Voice Studio | PARTIAL | Transcript jobs, editable timestamped segments, consent/reference records, user-supplied audio assembly, and subtitle export are tested. Translation, diarization, TTS, voice conversion/cloning, and generated speech are unavailable. A prior local MLX Whisper inference is documented in the README; it was not rerun in this audit. |
| 6 — Content Studio / Script-to-Film | PARTIAL | Project scripts/settings, characters, environments, scenes, shots, approvals, continuity review, and scene-isolated job snapshots persist and are tested. Research, script generation, storyboard image generation, guaranteed visual consistency, and final video rendering are not implemented. |
| 7 — GPU-worker architecture | PARTIAL | Worker contract, mock lifecycle, signed reference access, retry/cancel, output validation, and valid MP4 attachment have tests. The external worker is not configured or tested; model licensing is operator supplied and defaults unverified/disabled. |
| 8 — Smart Clipper | PARTIAL | Scene detection, transcript reuse/alignment, explainable heuristic scoring, candidate editing/approval, captions, manual framing, B-roll metadata matching, batch FFmpeg export, ownership, failure/retry/cancel are tested. Face tracking, translation, model-based highlights, and styled burned-in captions are unavailable. |

## Cross-cutting component status

| Component | Status | Evidence |
|---|---|---|
| Auth, user ownership, and project API | COMPLETE | SQLite tests cover credentials, tokens, structured validation, duplicate registration, ownership, and projects. |
| Frontend project persistence | PARTIAL | The dashboard's New Project flow creates browser-local drafts; the Video/Content workspaces use the backend project API separately. |
| SEO/publishing backend | MISSING | `Publication` is a database model, but no publishing API router, platform integration, or backend workflow is registered. |
| PostgreSQL integration | BLOCKED | Local server is listening, but the configured login is rejected; SQLite is the validated test/migration database. |
| Redis/Celery worker deployment | MISSING | Dependencies/settings are present but no active Celery app/worker or Compose configuration was found; current job workers poll from the API lifespan. |
| Real external GPU worker | BLOCKED | No worker URL/credentials are configured; adapter contract and local mock tests are available. |
| Translation, TTS, diarization | MISSING | Provider protocols exist, but no concrete provider is configured. |
| S3-compatible storage | MISSING | Only the local storage service implementation is present. |

## Application and integration checks

- Importing `app.main` succeeded. Its OpenAPI schema contains 70 distinct
  paths; the registered routers are auth, clipper, content, health, media,
  projects, timeline, and voice.
- Alembic discovered all registered model metadata. A fresh SQLite
  `upgrade head` and `downgrade base` round-trip passed.
- The running local backend returned HTTP 200 from `/health` and `/docs`.
  `/health` is a liveness check only, not a database-readiness check.
- All ten frontend pages returned their expected title and heading in browser
  checks, with no browser console errors. Project creation produced a clearly
  labeled local-only draft; test data was removed from browser storage.
- The built frontend had no horizontal overflow at 390, 768, or 1280 px after
  fixing the tablet top bar and media-auth form. This was checked on all ten
  routes.
- Cross-module API behavior is exercised by existing integration tests for
  auth/projects/media, timeline save/reload/export, transcript/edit/subtitle,
  content/scene generation and real media attachment, and Smart Clipper
  analysis/export. Not every listed product journey is covered by one
  end-to-end browser test.

## Environment and infrastructure findings

- There was no root `.env`, root `.env.example`, `backend/.env`, or frontend
  environment file. `backend/.env.example` existed. `backend/.env` was created
  from that example and a random development JWT key was generated without
  printing it. Its file mode is `0600`.
- Root `.gitignore` ignores `.env` and `.env.*` and exempts `.env.example`.
  Since this workspace has no Git repository, whether the new file is tracked
  cannot be checked.
- `Settings` uses `backend/.env` when commands run from `backend/`. Required
  for authenticated database-backed operation: a working `DATABASE_URL` and
  a non-placeholder `JWT_SECRET_KEY`. The created local config has a random
  JWT key, but its database authentication currently fails.
- Optional settings include CORS origins, local storage path, upload limit,
  MLX model name, and GPU-worker URL/token/timeout/output cap. The remote
  worker needs `PUBLIC_API_BASE_URL` reachable from that worker.
- Actual setting names are `ENVIRONMENT`, `STORAGE_PATH`,
  `GENERATION_WORKER_API_TOKEN`, and `MAX_UPLOAD_SIZE_BYTES` (not
  `APP_ENV`, `LOCAL_STORAGE_PATH`, `GENERATION_WORKER_TOKEN`, or
  `MAX_UPLOAD_SIZE`). `MODEL_PROVIDER`, `FFMPEG_PATH`, and `FFPROBE_PATH` are
  not settings; provider selection is based on available adapters/configured
  worker, and FFmpeg binaries are resolved through `PATH`. `REDIS_URL` exists
  but is not used by current job workers.
- PostgreSQL reports ready on localhost:5432, but the configured credentials
  were rejected with SQLSTATE `28000`. No PostgreSQL migration or integration
  test was run. `redis-cli` is unavailable and no infrastructure Compose file
  exists.

## Related documentation

- [Milestones 1–8 test report](./MILESTONES_1_TO_8_TEST_REPORT.md)
- [Model and provider license audit](./MODEL_LICENSE_AUDIT.md)
- [GPU worker contract](./gpu-worker-contract.md)
