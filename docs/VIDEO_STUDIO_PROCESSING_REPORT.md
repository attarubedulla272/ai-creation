# Video Studio Processing Pipeline

## Phase 1 audit: existing functionality and gaps

### Existing functionality

- The Video Studio is a client-side timeline editor in
  `frontend/src/components/video-editor.tsx`. It supports project selection,
  media import, native preview, editable timeline clips, timeline persistence,
  and MP4 export.
- `POST /api/v1/media` streams uploads to local storage, validates extension,
  MIME type, file signature, configured size, and optional project ownership.
  Storage keys are server-generated; display names are sanitized.
- `MediaAsset` stores owner/project IDs, storage key, file metadata, duration,
  and probe/derivative metadata. `ProcessingJob` already stores status,
  progress, output, retry limits, and cancellation intent.
- `GET /api/v1/media` and media detail, download, derivative, deletion, and
  media-job status endpoints enforce owner scope. Project associations are
  checked against the authenticated user.
- The in-process media worker uses safe subprocess argument arrays for
  FFprobe/FFmpeg. It records duration, dimensions, frame rate, codecs and audio
  streams; videos receive a thumbnail, proxy, extracted audio and waveform.
  Original uploads remain unchanged.
- Timeline data is stored as JSON on the existing `Timeline` model.
  Timeline export runs asynchronously, tracks progress, renders MP4, stores
  its storage key in job output, and has owner-scoped status/download routes.
- Existing media tests generate small media fixtures with FFmpeg and exercise
  upload validation, derivatives, ownership, downloads, deletion, and failed
  processing. Timeline tests exercise actual export and download.
- No new database migration is currently indicated. The existing job schema
  has retry and cancellation fields; no media-specific retry/cancel routes
  were present. There is no standalone Celery dependency for media tasks:
  the FastAPI lifespan starts the existing polling worker.

### Gaps to address

- Media processing jobs had no API retry or cancellation controls, and the
  worker did not observe the persisted cancellation flag.
- Timeline export was fixed to saved timeline dimensions. There were no
  validated 720p/1080p/4K preset requests, nor retry/cancel endpoints for
  export jobs.
- The editor discarded upload progress, did not surface derivative job
  progress/errors, and showed no thumbnail or technical metadata in its media
  cards.
- Disk-full errors were not surfaced distinctly to upload or processing users.

### Environment observed during audit

- FFmpeg and FFprobe are installed locally (FFmpeg 9.0.2).
- The workspace has approximately 26 GiB available at audit time.
- The project directory has no `.git` metadata, so a Git diff/status check is
  unavailable in this workspace snapshot.

## Implementation and verification

### Implemented

- Uploads require an allowed extension, matching MIME type, and matching file
  signature; they are checked against the configured limit both before and
  during streaming. The default limit is 2 GiB (configurable up to 20 GiB).
  Generated owner-scoped storage keys are used instead of client filenames or
  filesystem paths.
- The existing media worker probes uploads with FFprobe and persists duration,
  dimensions, frame rate, codecs, audio streams, and derivative locations.
  Video assets receive a JPEG thumbnail (maximum 640 px wide), an H.264/AAC
  proxy (maximum 1280 px wide), extracted AAC audio, and a waveform when audio
  is present. Images receive thumbnails; audio receives a waveform.
- Media jobs expose progress, failed/cancelled status, retry counts, and
  cancellation intent. The worker polls cancellation while probing and
  processing, removes partial derivatives after failures/cancellation, and
  reports safe user-facing errors for invalid media, unsupported codecs,
  timeouts, and disk-full conditions.
- Timeline export accepts `720p`, `1080p`, and `4k` presets, retains the
  timeline aspect ratio, and rejects a preset when any selected source video
  has fewer pixels on its long edge. It uses FFmpeg argument arrays (never a
  shell), limits H.264 encoder threads to two, reports job progress, and stores
  the output storage key and render metadata on the existing processing job.
  Export jobs support owner-scoped status, retry, cancellation, and download.
- The Video Studio and media-library screens now expose upload progress,
  thumbnails, metadata, derivative processing status/errors, preview and
  download controls, plus retry/cancel controls. The editor exposes export
  preset selection and export progress/retry/cancel/download.
- No database migration or dependency-manifest change was needed. Existing
  `MediaAsset`, `Timeline`, and `ProcessingJob` models and FastAPI lifespan
  workers are reused.

### API endpoints

- `POST /api/v1/media` — validate, store, and enqueue an upload.
- `GET /api/v1/media` and `GET /api/v1/media/{asset_id}` — list and retrieve
  only the authenticated user's assets.
- `GET /api/v1/media/{asset_id}/download` and
  `GET /api/v1/media/{asset_id}/derivatives/{kind}` — download the source or a
  generated thumbnail, proxy, extracted audio, or waveform.
- `GET /api/v1/media/jobs/{job_id}`,
  `POST /api/v1/media/jobs/{job_id}/retry`, and
  `POST /api/v1/media/jobs/{job_id}/cancel` — inspect/control an owned media
  processing job.
- `DELETE /api/v1/media/{asset_id}` — delete the owned asset and its
  derivatives.
- `GET`/`PUT /api/v1/projects/{project_id}/timeline` — load/save the validated
  timeline document.
- `POST /api/v1/projects/{project_id}/timeline/export` — queue a timeline MP4
  render.
- `GET /api/v1/timeline/exports/{job_id}`,
  `POST /api/v1/timeline/exports/{job_id}/retry`,
  `POST /api/v1/timeline/exports/{job_id}/cancel`, and
  `GET /api/v1/timeline/exports/{job_id}/download` — inspect/control/download
  an owned export.

### FFmpeg processing and presets

- FFprobe runs with `-show_format -show_streams -of json`.
- Thumbnails seek into the source and scale to at most 640 px wide.
- Proxies scale to at most 1280 px wide and use `libx264 -preset ultrafast
  -crf 30 -threads 2`, with AAC audio at 96 kbit/s when present.
- Timeline rendering has since been extended beyond this pipeline milestone:
  it now composites ordered video/overlay/subtitle tracks, gaps, transitions,
  keyframes, color effects, and mixed audio. See
  [VIDEO_STUDIO_TIMELINE_RENDERING_REPORT.md](./VIDEO_STUDIO_TIMELINE_RENDERING_REPORT.md)
  for current implementation details and verification.
- Presets set the long edge to 1280, 1920, or 3840 pixels respectively. They
  require source video at least that large on its long edge. The 4K path was
  actually rendered and probed at 3840x2160 on this Mac with the available
  FFmpeg encoder.

### Tests and verification

- At this pipeline milestone, the backend suite had **75 passed**; after the
  timeline renderer work, the current full suite has **76 passed**. See the
  timeline rendering report for current tests and results.
- Focused FFmpeg/FFprobe media and timeline API tests include secure upload,
  metadata and derivatives, ownership, failure handling, retry/cancel,
  successful 720p export, source-resolution rejection for 1080p/4K, and a
  generated 4K upload → processing → export → download → FFprobe workflow.
  The downloaded 4K result was verified as **3840x2160**.
- Ruff check and format check passed for all eight backend files changed for
  this work.
- Repository-wide Ruff check is not clean: it reports an import-order issue
  in the unrelated existing `backend/app/services/voice_processing.py`. That
  file was not changed. No unrelated formatting or import cleanup was applied.
- Frontend ESLint, `tsc --noEmit`, and the Next.js production build all passed.
- The end-to-end checks above are automated API tests using locally generated
  media and real FFmpeg/FFprobe. The Video Studio route was later loaded
  manually, but authentication blocked access to the editor; no signed-in
  editing interaction was manually verified.

### Cleanup, limitations, and remaining work

- Temporary processing directories are automatically removed. Partial
  derivatives and failed/cancelled export files are deleted. Deleting a media
  asset removes its original and derivatives.
- Successfully completed exports are retained in storage for later download;
  there is no automatic expiration or export-delete endpoint. Originals and
  generated media assets remain until the user deletes them. Disk-full
  failures are surfaced when a write fails; there is no predictive disk-space
  reservation.
- Timeline export limitations and supported rendering behavior have evolved;
  consult the [timeline rendering report](./VIDEO_STUDIO_TIMELINE_RENDERING_REPORT.md)
  rather than the original pipeline limitations below.
- 4K export depends on the local FFmpeg build and available hardware/resources;
  the API checks source dimensions but cannot guarantee that every host can
  finish a large render. Unsupported encoders, corrupt media, timeouts, and
  insufficient disk space produce failed jobs rather than successful-looking
  output.
- No paid APIs, AI models, or additional dependencies were introduced. The
  IndicTrans2 reports, MLX worker, and their environments were not changed.
