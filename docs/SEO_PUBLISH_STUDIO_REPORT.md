# SEO & Publish Studio Report

## Existing functionality and gaps

- The application already had authenticated users, owner-scoped projects and
  media, exported video assets, Smart Clipper candidates, and a minimal
  `Publication` database model.
- The SEO & Publish page was a session-only demonstration. There were no
  publication APIs, metadata history, thumbnail rendering, calendar workflow,
  OAuth connection, publishing client, or provider-backed analytics.
- `Settings` has no Google OAuth client, redirect URI, or encrypted token-store
  configuration. No platform credentials were used or exposed during this work.

## Implemented

- Added authenticated, owner-scoped publication create/list/update APIs and a
  calendar list API. Drafts can associate with a project video, Smart Clipper
  candidate, and project thumbnail. Association checks reject assets or
  projects owned by someone else.
- Persisted title, description, tags, hashtags, primary/secondary keywords,
  chapters, language, category, platform, workflow status, planned date, and
  asset associations. Updates append immutable snapshots and increment a
  publication version; no-op updates do not create duplicate versions.
- Enforced a 100-character title, 5,000-character description, and YouTube's
  500-character combined tags limit. Chapters must have unique, ascending
  timestamps. Scheduled entries require a future timezone-aware date.
- Added deterministic local title ideas using user-provided text templates.
  They are identified as rule-based, not AI-generated, and include no keyword
  volume, ranking, or performance claims.
- Added local Pillow thumbnail rendering from an owned image asset, with
  selectable 16:9 (1280×720), 1:1 (1080×1080), or 9:16 (1080×1920) output,
  adjustable crop center, text, size, color, and vertical position. Output is a
  generated project image asset; filesystem paths are not returned.
- Replaced the SEO demo page with authenticated metadata editing, revision
  version display, video/clip/thumbnail associations, image upload and render
  controls, locally planned calendar entries, and explicit unavailable states
  for disconnected integrations.
- Added an Alembic migration extending the existing publication table and
  creating `publication_revisions`.

## API endpoints

All except title suggestions require the normal bearer-token authentication.

- `GET /api/v1/publishing/capabilities` — report YouTube and analytics as
  unavailable until configured.
- `POST /api/v1/publishing/title-suggestions` — deterministic local template
  suggestions from supplied topic and keywords.
- `POST /api/v1/publishing/projects/{project_id}/publications` —
  create a release package.
- `GET /api/v1/publishing/projects/{project_id}/publications` — list packages
  for an owned project.
- `GET /api/v1/publishing/calendar` — list the caller's packages, optionally
  filtered by `start` and `end`.
- `PATCH /api/v1/publishing/publications/{publication_id}` — update metadata
  and status.
- `GET /api/v1/publishing/publications/{publication_id}/revisions` — retrieve
  owner-scoped version snapshots.
- `POST /api/v1/publishing/projects/{project_id}/thumbnails` — render and
  persist a local thumbnail.
- `GET /api/v1/publishing/assets/{asset_id}/thumbnail` — read owned thumbnail
  metadata.

## Database changes

- Added `metadata`, video/clip/thumbnail asset references, and a version counter
  to `publications`.
- Added `publication_revisions` with a unique publication/version pair and
  immutable JSON snapshots.
- Migration: `2d9a7c4e6b10_add_seo_publish_studio.py`, following the existing
  merged Alembic head.

## Platform integrations and requirements

- **YouTube publishing: not implemented or connected.** Official upload uses
  OAuth 2.0 user authorization and `videos.insert` with resumable upload. The
  Google Cloud project must enable the YouTube Data API and have an OAuth
  client/redirect URI configured. Those configuration fields and secure
  encrypted token storage are absent, so no OAuth initiation/callback, channel
  connection, upload, privacy setting, thumbnail upload, or publish-success
  path is exposed.
- Google notes that apps requesting sensitive or restricted scopes may need
  OAuth verification before public use; the exact scope classification and
  review depend on the endpoints the eventual integration requests. Request
  only the minimum scopes needed.
- The current YouTube quota documentation describes a default bucket of 100
  `videos.insert` calls per day and 10,000 units per day for other Data API
  methods (with separate quotas for some methods and requests consuming quota).
  Quota allocations and usage must be checked in the operator's Google Cloud
  project. No quota is consumed by this implementation.
- YouTube Analytics API metrics require an authorized channel/owner context.
  There is no analytics connection or returned metric; the UI shows metrics as
  unavailable rather than fabricating values.
- Instagram, TikTok, and Other can be selected as local metadata labels only.
  Their publishing integrations and platform-specific validation have not been
  implemented; YouTube's documented title/description/tag limits are the only
  enforced platform limits.
- No browser scraping or unauthorized publishing automation is used.

Official references:

- [YouTube OAuth authentication](https://developers.google.com/youtube/data/guides/authentication)
- [YouTube video upload guide](https://developers.google.com/youtube/data/guides/uploading_a_video)
- [YouTube API quota costs](https://developers.google.com/youtube/data/determine_quota_cost)
- [YouTube Analytics metrics](https://developers.google.com/youtube/analytics/metrics)
- [Google OAuth sensitive-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

## Verification

### Automated-test verified

- `backend/.venv/bin/pytest -q`: **86 passed**.
- Publishing API tests cover persistence/reload, version history, metadata
  validation, chapter ordering, timezone/future scheduling, calendar output,
  owner checks, local title ideas, explicit disconnected integrations, and
  actual Pillow rendering followed by downloading and decoding the generated
  PNG at 1280×720.
- All Alembic migrations upgraded successfully against an isolated temporary
  SQLite database, including the new migration.
- `backend/.venv/bin/ruff check` on the changed Python files: passed.
- Repository-wide Ruff still reports the previously existing import-order
  issue in `backend/app/services/voice_processing.py`; that unrelated file was
  not changed.
- `frontend/npm run lint`: passed.
- `frontend/npx tsc --noEmit`: passed.
- `frontend/npm run build`: passed; `/seo-publish` is included in the output.

### Real integrations

- No external platform integration was run. No YouTube channel, OAuth consent,
  upload, thumbnail submission, or analytics query was available or claimed.
- Thumbnail output was produced by real local Pillow processing in API tests;
  no image-generation service is required.
- OAuth state validation and mocked upload/analytics client tests are not
  present because the OAuth and provider client workflows have not been
  implemented.

### Browser manually verified

- Opened `/seo-publish` in the browser and confirmed the refreshed module
  header and authenticated connection form render.
- The authenticated browser workflow was not exercised; no browser test
  account/backend was provisioned for this check.

## Not implemented and known limitations

- OAuth state creation/validation, channel connection, encrypted token
  persistence/refresh/revocation, YouTube upload jobs, upload progress/retry/
  cancellation, platform thumbnail upload, and YouTube Analytics requests.
- Subtitle-file association and a complete export/subtitle/thumbnail publishing
  package.
- Platform-specific metadata presets and constraints for Instagram/TikTok.
- A drag-and-drop calendar, thumbnail template gallery, font selection, and
  advanced interactive crop editor. Thumbnail composition currently uses one
  title overlay with a black outline and adjustable crop center.
- AI title/description/keyword generation. Title ideas are local templates;
  no paid or local AI provider is used.
- Actual publication status is never advanced to `published` by local
  scheduling. The API only accepts draft, ready, and scheduled updates.
