# YouTube Integration Report

## Status

The official YouTube integration is implemented behind optional backend
configuration. Automated tests use mocked Google responses. No Google OAuth
credentials are configured in this workspace, so an authenticated channel,
live upload, thumbnail upload, native scheduled publication, and live analytics
have **not** been verified. This integration is **not production-ready** until
the configured OAuth app and a real private or unlisted upload have been
manually verified.

## Architecture and scopes

The FastAPI backend uses Google's OAuth 2.0 web-server flow and official
YouTube Data API v3 and YouTube Analytics API endpoints. The frontend receives
only an authorization URL and public channel/job/analytics data.

OAuth protections include:

- A cryptographically random state value, stored as a SHA-256 hash, bound to
  the initiating user, expiring after 10 minutes, and consumed once.
- PKCE with S256; the verifier is encrypted at rest.
- The callback URI comes from backend configuration and is sent unchanged in
  the authorization and token-exchange requests. Configure the identical URI
  in Google Cloud.
- Refresh tokens and PKCE verifiers use Fernet encryption. Access tokens are
  transient and are never stored or returned to the frontend.
- Connection, publication, asset, and upload-job queries are owner-scoped.
  Disconnect removes the local connection and attempts Google token revocation.
- Refresh-token rejection marks the connection `reauthorization_required`.

| Purpose | OAuth scopes |
|---|---|
| Channel identification and video upload | `youtube.readonly`, `youtube.upload` |
| Analytics (incremental consent) | `yt-analytics.readonly`, retaining the base scopes |

Analytics permission is requested separately. OAuth state is cleaned up when a
new authorization flow starts. A YouTube account exposing multiple channels is
rejected rather than silently selecting one; explicit channel selection is not
implemented.

## Google Cloud setup

1. Create separate Google Cloud projects for development/staging and
   production. Enable **YouTube Data API v3** and **YouTube Analytics API**.
2. Configure the OAuth consent screen, audience, app branding, support contact,
   authorized domains, homepage, privacy policy, and the scopes above.
3. Create an OAuth client of type **Web application**. Register the exact
   backend callback URI shown in `YOUTUBE_OAUTH_REDIRECT_URI`; do not use a
   client-side OAuth secret.
4. Put the credentials in the backend's secret environment, never in the
   frontend or source control. Generate a stable Fernet key for
   `YOUTUBE_TOKEN_ENCRYPTION_KEY`; retain it securely and back it up because
   changing or losing it makes stored refresh tokens unusable.
5. Set the variables below, restart the backend, sign in, and connect a channel.
   The integration is disabled when the required OAuth configuration is absent.

Backend environment variables:

| Variable | Purpose |
|---|---|
| `YOUTUBE_OAUTH_CLIENT_ID` | Google OAuth web-client ID |
| `YOUTUBE_OAUTH_CLIENT_SECRET` | Google OAuth web-client secret |
| `YOUTUBE_OAUTH_REDIRECT_URI` | Exact registered callback, normally `/api/v1/publishing/youtube/oauth/callback` |
| `YOUTUBE_OAUTH_FRONTEND_RETURN_URL` | Frontend return location (defaults to localhost in development; set to HTTPS in production) |
| `YOUTUBE_TOKEN_ENCRYPTION_KEY` | Fernet key for encrypted refresh tokens and PKCE verifiers |

The `.env.example` contains blank credential placeholders. Production callback
and frontend return URIs must use HTTPS. The development callback may use a
loopback host.

Google can require OAuth app verification for scopes classified as sensitive
or restricted; check each requested scope in the Cloud Console's Data Access
page and complete applicable branding, domain, privacy-policy, and verification
requirements before broad public availability. Google states sensitive-scope
verification can take up to 10 days. Audience and testing-mode restrictions
depend on the configured OAuth app; they have not been exercised here.

## API endpoints

All endpoints except the Google callback require the application's user
authentication. The callback is protected by the single-use state and PKCE
flow.

| Endpoint | Function |
|---|---|
| `GET /api/v1/publishing/youtube/connections` | List the signed-in user's connected channels and consent status |
| `POST /api/v1/publishing/youtube/connect` | Start channel OAuth |
| `GET /api/v1/publishing/youtube/oauth/callback` | Exchange the Google authorization code and persist the channel |
| `POST /api/v1/publishing/youtube/connections/{connection_id}/disconnect` | Disconnect locally and attempt provider revocation |
| `POST /api/v1/publishing/youtube/connections/{connection_id}/analytics/authorize` | Request separate Analytics consent |
| `GET /api/v1/publishing/youtube/analytics` | Return provider-backed daily metrics and traffic-source rows |
| `POST /api/v1/publishing/youtube/publications/{publication_id}/uploads` | Queue an explicit YouTube upload |
| `POST /api/v1/publishing/youtube/publications/{publication_id}/thumbnail` | Upload/retry the selected thumbnail after video confirmation |
| `GET /api/v1/publishing/youtube/uploads` | List the user's upload jobs |
| `GET /api/v1/publishing/youtube/uploads/{job_id}` | Read upload status/progress |
| `POST /api/v1/publishing/youtube/uploads/{job_id}/retry` | Retry a failed or cancelled job within its retry limit |
| `POST /api/v1/publishing/youtube/uploads/{job_id}/cancel` | Cancel a queued or active upload |

## Persistence and upload workflow

Migration `7b3c91a6d204` adds:

- `youtube_connections`: owner/channel identity, encrypted refresh token,
  granted scopes, connection status, and last error.
- `youtube_oauth_states`: hashed, expiring OAuth state, encrypted PKCE verifier,
  purpose, and one-time consumption state.
- `publications.youtube_status`, `youtube_privacy_status`, and `youtube_url`.

Uploads use the existing `ProcessingJob` table and background-worker pattern.
The worker revalidates ownership of the publication, exported video, optional
thumbnail, and channel. It sends metadata through a resumable upload session in
8 MiB chunks, follows YouTube's acknowledged byte ranges, and persists progress.
The publication's YouTube video ID and URL are written only after Google
confirms a video ID. Metadata maps title, description, tags, category, language,
hashtags, and chapter timestamps. Titles, descriptions, tags, and chapter text
are validated before queueing and again in the worker.

Visibility can be private, unlisted, or public. Native `publishAt` scheduling is
available only with private visibility and a future timezone-aware timestamp;
it is distinct from the existing local calendar schedule. The frontend labels
local plans separately from YouTube upload/scheduling status. A successful
upload is not represented as public until YouTube's publication behavior is
confirmed. Actual scheduled-publication behavior has not been tested.

Thumbnail upload is a separate step after the video is confirmed. It accepts
JPEG/PNG assets up to 2 MB. A thumbnail error does not invalidate the confirmed
video upload and can be retried separately.

The UI adds a YouTube area in SEO & Publish Studio for channel connection and
disconnect, analytics authorization, privacy/schedule selection, upload
progress/history, retry/cancel, thumbnail retry, and provider analytics.
Analytics shown are only the values returned by YouTube. The implementation
does not synthesize missing metrics or claim SEO performance.

## Quotas and provider limitations

According to the current [YouTube Data API quota documentation][quota]:

- `videos.insert` has a default bucket of 100 calls per day; each call costs one
  unit in that bucket.
- Other Data API endpoints share a default 10,000-unit daily quota; daily quota
  resets at midnight Pacific Time.
- `thumbnails.set` costs 50 units.
- YouTube documents a maximum upload size of 256 GB and `video/*` or
  `application/octet-stream` media types. This application uses its own stricter
  local upload/storage limits.

Quota allocations and Google OAuth policies can change; confirm current values
in the Cloud Console and official documentation before launch. The OAuth
verification status, project quota, channel permissions, and any API approval
requirements for the production project remain unknown until configured.

The worker retries eligible transient provider errors and persists failed,
cancelled, and completed states. Quota exhaustion is surfaced, not silently
treated as success. The resumable session URL is not persisted across worker
restarts. An interrupted or uncertain upload is failed with a warning to check
the channel before retrying, because a provider-side completion could occur
without a locally recorded confirmation. Multi-channel account selection,
automatic quota increase requests, and browser-based publishing automation are
not implemented.

Analytics uses the official Analytics API and currently requests daily views,
estimated minutes watched, average view duration, likes, comments, subscribers
gained, and traffic-source views. Metrics may be delayed or absent for the
requested period; the response includes the latest date returned by the
provider. Revenue analytics and content-owner reports are not implemented.

## Verification

### Automated / mocked

- YouTube and publishing tests: **12 passed** in the targeted run.
- Full backend suite after the final worker/error-handling refinements:
  **92 passed**.
- Mocked OAuth callback, single-use/replayed state, encrypted-token behavior,
  separate Analytics consent, owner access controls, resumable partial-range
  acknowledgement, worker persistence/reload, local-file error redaction, and
  revoked-refresh-token handling are covered.
- Changed YouTube/publishing backend files passed Ruff after the final edits.
- Fresh temporary SQLite migration upgrade reached `7b3c91a6d204`; `alembic
  heads` reports that single head.
- Frontend ESLint, TypeScript (`tsc --noEmit`), and optimized Next.js production
  build passed.
- Repository-wide Ruff reports one unrelated pre-existing import-order issue
  in `backend/app/services/voice_processing.py`. That file is outside this
  milestone and was not changed.

Automated tests do **not** exercise every provider branch. In particular,
thumbnail retry, YouTube quota exhaustion, and native `publishAt` have not been
independently verified by a live provider request.

### Real integrations and manual verification

| Workflow | Result |
|---|---|
| Google OAuth channel connection | Not run; Google credentials are not configured |
| Real video upload | Not run; no live channel or explicit live-test authorization |
| Real thumbnail upload | Not run |
| Native YouTube scheduling | Not run |
| Live YouTube Analytics | Not run |
| Browser-manual UI workflow | Not run |

No credentials were used in automated fixtures. The API's mocked confirmed
upload and persistence test is not evidence of a real YouTube upload.

## Known limitations and release gate

- Complete a real OAuth connection and explicitly authorized private or
  unlisted test upload using the configured Google Cloud project.
- Verify live upload progress/retry behavior, thumbnail upload/retry, and
  native scheduling, then verify the resulting video through YouTube itself.
- Confirm production OAuth verification, quotas, consent-screen configuration,
  and Data API / Analytics API access.
- Perform browser-manual review of connection, upload, error, and analytics
  states.
- Resolve or document the existing repository-wide Ruff issue separately.

Do not call this integration production-ready until these release gates pass.

## Official references

- [YouTube Data API quota costs][quota]
- [YouTube `videos.insert`][insert]
- [YouTube `thumbnails.set`][thumbnail]
- [YouTube Analytics `reports.query`][analytics]
- [Google OAuth web-server flow][oauth]
- [Google OAuth verification requirements][verification]
- [Google OAuth policies][oauth-policies]

[quota]: https://developers.google.com/youtube/data/determine_quota_cost
[insert]: https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
[thumbnail]: https://developers.google.com/youtube/data/reference/rest/v3/thumbnails/set
[analytics]: https://developers.google.com/youtube/analytics/reference/reports/query
[oauth]: https://developers.google.com/identity/protocols/oauth2/web-server
[verification]: https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
[oauth-policies]: https://developers.google.com/identity/protocols/oauth2/policies
