# Milestones 1–8 audit and test report

Audit date: 2026-11-12.

## 1. Overall result

**Partially ready for local development.** Frontend build, backend API tests,
local media processing, SQLite migrations, and local worker/provider tests
pass. Database-backed local operation is blocked by PostgreSQL credential
rejection (`SQLSTATE 28000`). A configured external GPU worker is not present.

## 2. Milestone status

| Milestone | Feature | Implementation | Tests | Result | Remaining issues |
|---|---|---|---|---|---|
| 1 | Frontend foundation | Partial | Ten routes, project draft interaction, responsive browser smoke test | PARTIAL | Demo account/storage and local project drafts are not synchronized to backend; many module surfaces are planned/demo. |
| 2 | Backend/database foundation | Partial | Auth, ownership, projects, API errors; SQLite suite and migration round-trip | PARTIAL | PostgreSQL login rejected; no PostgreSQL migration/integration evidence. |
| 3 | Media and FFmpeg | Local feature set implemented | Upload validation, metadata, derivatives, failure cleanup, traversal and ownership tests | COMPLETE | Local filesystem only; no S3 implementation. |
| 4 | Video editor | Partial | Timeline save/reload, ownership, actual FFmpeg export | PARTIAL | Renderer omits timeline overlays, subtitles, effects, transitions, gaps, overlaps, and source-video audio. |
| 5 | Voice Studio | Partial | Queued transcript/edit/subtitles, consent, and user-audio assembly tests | PARTIAL | No translation, diarization, TTS, voice conversion, or cloning provider. Prior MLX inference is documented but not rerun here. |
| 6 | Content Studio / Script-to-Film | Partial | Persistence, ownership, scene jobs, mock preview and output attachment tests | PARTIAL | Research/script generation, image storyboard generation, guaranteed continuity, and final rendering are absent. |
| 7 | GPU worker | Partial | Mock lifecycle, HTTP adapter contract, signed references and valid output attachment | PARTIAL | No real worker configured; invalid-response, timeout, oversized-output, and expired-URL cases are not comprehensively tested. |
| 8 | Smart Clipper | Partial | Scene detection, transcript reuse, ranking, boundaries, captions, approval, failure/retry/cancel and FFmpeg export | PARTIAL | No face tracking or translation; heuristic scores are not virality predictions; captions are selectable subtitles, not styled burn-in. |

## 3. Environment configuration

- Before the audit, `.env` was absent at the workspace root, in `backend/`,
  and in `frontend/`; `backend/.env.example` was present.
- Created `backend/.env` from the example and generated a 48-byte-equivalent
  random development JWT secret. The value is not included in this report.
  Permissions are `0600`. The configured PostgreSQL authentication fails.
- `.gitignore` contains `.env` and `.env.*` ignore patterns and exempts
  `.env.example`. The workspace is not a Git repository, so tracked status
  cannot be checked.
- Required for authenticated database operations: valid `DATABASE_URL` and
  non-placeholder `JWT_SECRET_KEY`. CORS, `STORAGE_PATH`,
  `MAX_UPLOAD_SIZE_BYTES`, `MLX_WHISPER_MODEL`, and generation metadata have
  defaults. A GPU worker is optional; when configured, the worker URL/token
  and reachable `PUBLIC_API_BASE_URL` are operator settings.
- Actual application names are `ENVIRONMENT`, `STORAGE_PATH`,
  `GENERATION_WORKER_API_TOKEN`, `GENERATION_WORKER_TIMEOUT_SECONDS`, and
  `MAX_UPLOAD_SIZE_BYTES`. `APP_ENV`, `LOCAL_STORAGE_PATH`,
  `GENERATION_WORKER_TOKEN`, `MODEL_PROVIDER`, `FFMPEG_PATH`, and
  `FFPROBE_PATH` are not consumed settings. FFmpeg tools are located on
  `PATH`. `REDIS_URL` is defined but unused by active workers.
- `.env.example` has placeholders/local defaults only and now lists every
  Pydantic setting. No paid-provider credential was added.

## 4. Import and application startup

- `from app.main import app` succeeded.
- OpenAPI generation found 70 unique paths and no duplicate paths. Registered
  feature routers: auth, clipper, content, health, media, projects, timeline,
  and voice. SEO/publish has no backend router.
- Alembic imports `app.models`; 19 SQLAlchemy tables were registered.
- Running backend endpoints `/health` and `/docs` both returned HTTP 200.
  Health is liveness-only; it does not check database readiness.
- The production frontend returned HTTP 200 and all ten routes rendered with
  the expected title/heading. Browser console errors: none. Responsive
  overflow: none across all ten routes at widths 390, 768, and 1280 px.
- No unresolved imports or TypeScript errors were reported by build/lint.
  No Git metadata was available to distinguish pre-existing edits.

## 5. Test results

| Check | Result |
|---|---|
| `uv run pytest -q` | 32 passed, 0 failed, 0 skipped |
| `uv run ruff check app migrations tests` | Passed |
| `uv run ruff format --check app migrations tests` | Passed; 65 files already formatted |
| `uv lock --check` | Passed |
| `DATABASE_URL=sqlite+aiosqlite:////tmp/ai_creator_audit_20261112_0338.db uv run alembic upgrade head` then `downgrade base` | Passed on a temporary SQLite database |
| `npm run lint` | Passed |
| `npx tsc --noEmit` | Passed |
| `npm run build` | Passed; 12 App Router pages generated |
| Browser route/responsive smoke test | Passed; 10 routes × 3 widths; no console errors or horizontal overflow |
| Browser local project creation | Passed; local-only draft creation verified and test storage restored |
| `uv run python -m pip check` | Not available: the active uv environment has no `pip` module; `uv lock --check` passed instead |
| PostgreSQL integration/migration | Blocked: server accepts TCP, configured authentication rejected with SQLSTATE `28000` |
| Real GPU worker | Not tested: no worker configured |

Small local FFmpeg-generated media fixtures are used for backend tests. Test
coverage includes media upload and derivatives, timeline persistence/export,
voice transcript and consent flows, content persistence and worker contracts,
and Smart Clipper analysis/export. Not every requested end-to-end journey has
a single browser-driven test.

## 6. Security findings

- **Medium — database configuration:** current local PostgreSQL authentication
  is rejected. Configure an existing local database account and URL before
  database-backed testing or normal API use.
- **Medium — external worker hardening:** the worker API token is optional and
  the URL schema permits HTTP. Use a private network or HTTPS and a strong
  token in any non-local deployment; never expose the worker publicly without
  authentication.
- **Medium — voice authorization assurance:** consent is a stored user
  attestation plus asset ownership, not independent identity/permission
  verification. This is currently reference metadata only; no cloning or
  synthesis runs.
- **Low — browser token exposure:** frontend API tokens are kept in
  `sessionStorage`, not an HttpOnly cookie. An XSS in the frontend origin could
  access the token; maintain a strict XSS posture and consider a server-managed
  session before production.
- **Low — authentication abuse controls:** no login/register rate limiter was
  found. Add deployment-level or application-level throttling before exposing
  auth endpoints publicly.
- No critical exploitable issue was established in this audit. Upload
  validation, generated storage paths, ownership checks, Argon2 password
  hashes, short-lived JWTs, and scoped five-minute worker reference URLs have
  implementation/tests. Dependency vulnerability scanning was not run.

## 7. AI functionality reality check

| Capability | UI | API | Provider adapter | Installed/tested inference |
|---|---|---|---|---|
| Transcription | Implemented | Queued transcript API | Optional native MLX Whisper | Prior real short-audio MLX test documented; not rerun in this audit |
| Translation | UI/manual text entry | Transcript fields/workflow support | Interface only | No provider/model installed |
| TTS / cloning / conversion | UI labels and consent/reference management | Metadata and user-audio assembly | Interface only | No provider/model/inference |
| Script/video generation | Scene planning and controls | Persisted scene jobs | Mock text preview and self-hosted HTTP contract | Mock tests pass; no real model/worker |
| Smart Clipper | Implemented | Queued analysis/export | PySceneDetect + local heuristic scoring + FFmpeg | Real local scene detection/export tests pass; no generative model |
| SEO/publishing | Demonstration UI | No API router/integration | None | Not implemented |

## 8. Files changed

Created:

- `backend/.env` — ignored local development configuration with generated
  signing key; never include in version control.
- `docs/PROJECT_AUDIT.md` — architecture and Milestone 1–8 status.
- `docs/MODEL_LICENSE_AUDIT.md` — model/provider and commercial-use review.
- `docs/MILESTONES_1_TO_8_TEST_REPORT.md` — this evidence-based test report.

Modified:

- `README.md` — links to audit and licensing reports.
- `backend/.env.example` — added the optional MLX model setting.
- `backend/app/api/v1/auth.py`, `backend/app/api/v1/timeline.py`,
  `backend/app/db/session.py`, `backend/app/models/publication.py`,
  `backend/app/models/timeline.py`, `backend/app/models/user.py`,
  `backend/app/services/media_processing.py`,
  `backend/app/services/timeline_export.py`,
  `backend/migrations/env.py`,
  `backend/migrations/versions/fa0b41bc4e10_create_initial_studio_schema.py`,
  `backend/tests/conftest.py`, `backend/tests/test_api.py`,
  `backend/tests/test_media.py`, and `backend/tests/test_timeline.py` —
  Ruff import/annotation fixes or formatting; the missing-database test now
  explicitly overrides `DATABASE_URL` so it remains isolated when `.env`
  exists.
- `backend/app/core/security.py` and `backend/app/services/storage.py` —
  Ruff-compatible UTC/context-manager annotations.
- `frontend/src/app/globals.css` — tablet layout fixes for the top bar and
  media authentication form.

No database, uploaded media, or model weights were deleted.

## 9. Remaining tasks, priority order

1. Configure valid local PostgreSQL credentials/database; run Alembic against
   PostgreSQL and exercise core API workflows there.
2. Before public deployment, require HTTPS/private network and worker
   authentication; add rate limiting and decide whether to move browser
   credentials to an HttpOnly session.
3. Add a configured, license-verified self-hosted GPU worker and test invalid
   responses, timeouts, cancellation races, and output-size limits.
4. Implement and test missing production capabilities: SEO/publishing APIs,
   translation/TTS, face-aware framing, rendered caption styling, timeline
   overlays/effects/transitions, and full browser end-to-end journeys.
5. Re-verify the commercial license and provenance of converted MLX Whisper
   weights before commercial distribution.

## 10. Next milestone readiness

**Do not begin Milestone 9 implementation yet.** The audited code and local
test suites are stable, but PostgreSQL database-backed operation is blocked by
the current local credentials, and major provider-dependent product behavior
remains intentionally incomplete. Resolve the database configuration and
confirm the required Milestone 9 scope first.
