# Smart Clipper — Implementation Report

## Implemented

- Reused the existing authenticated `/api/v1/clipper` API, `ClipCandidate`,
  `Transcript`/`TranscriptSegment`, and `ProcessingJob` models, local storage,
  application worker, and `VoiceProviderRegistry`. No table or migration was
  added.
- Analysis probes source videos with FFprobe, detects scene boundaries with the
  already-installed PySceneDetect `ContentDetector`, and detects audio silence
  using FFmpeg `silencedetect` at -35 dB with a 250 ms minimum. When PySceneDetect
  reports no cuts, the source is represented as one scene.
- Analysis reuses the latest completed transcript for the selected asset or
  calls the configured local transcription provider. It does not download a
  model. With no saved transcript/provider (or no audio stream), it can still
  produce explicitly scene/silence-based candidates, with no fabricated
  transcript or captions. A configured provider failure remains a failed job.
- Transcript segments are associated with the scene having the greatest time
  overlap. Existing `speaker_label` values are preserved into candidate
  caption segments; no diarization is claimed or added.
- Candidate windows support requested 15, 30, 45, and 60 second targets plus
  configurable minimum/maximum bounds. Transcript windows end on segment
  boundaries and are grouped through sentence-ending punctuation where
  available. Candidate ranking is a transparent weighted heuristic using scene
  changes, transcript speech coverage, silence proximity, sentence completion,
  opening/ending form, configured lexical signals, standalone-thought length,
  and pacing. It does not estimate virality or understand emotion.
- Candidates can be manually adjusted, approved/rejected, ranked with user
  weights, and batch-exported only after approval. Caption timing remains
  segment-level. Caption exports include styled burned-in segment overlays and
  a selectable `mov_text` subtitle track, with position, boxed/outline/minimal
  theme, font size, foreground/background/outline colors. Exported media stays
  in the project library.
- Exports support vertical 9:16, square 1:1, portrait 4:5, and landscape 16:9
  crops, plus manual horizontal/vertical crop position. FFmpeg is invoked using
  argument arrays; temporary files are cleaned up. Animated word highlighting
  is rejected because verified word-level timestamps are not available.
- The UI shows upload progress, scene and silence ranges, transcript segments
  with speaker labels when present, explainable scores, candidate boundary and
  crop controls, caption styling, job progress/errors/cancellation, and retry
  for failed analysis/export jobs. Face-aware crop remains explicitly
  unavailable.

## API and job workflow

- `GET /api/v1/clipper/capabilities` reports scene/silence/render providers,
  transcript timestamp precision, and unavailable face tracking/word timing.
- `POST /api/v1/clipper/analyses` queues analysis; `GET
  /api/v1/clipper/analyses/{job_id}` reads its owner-scoped status/results.
- `GET /api/v1/clipper/projects/{project_id}/candidates` lists candidates;
  `PATCH /api/v1/clipper/projects/{project_id}/ranking` recalculates scores.
- Candidate endpoints support manual boundaries, approval/rejection, caption
  edits and SRT/VTT downloads, manual framing, and boundary regeneration.
- `POST /api/v1/clipper/exports` queues approved clips for batch rendering.
  `GET /api/v1/clipper/jobs/{job_id}`, `POST .../{job_id}/retry`, and
  `POST .../{job_id}/cancel` inspect or control owner-scoped jobs.
- Project/source/candidate ownership checks remain in place. Caption exports
  are rejected up front when a selected clip has no transcript timing. Worker
  failures remain failed jobs; no mock output is substituted.

## Automated-test verified

- Smart Clipper tests: **9 passed**.
- Complete backend suite: **80 passed**.
- Ruff and format checks pass for the four modified backend Python files.
  Repository-wide `ruff check app tests` has one unrelated, pre-existing
  import-order issue in `backend/app/services/voice_processing.py`; that file
  was not changed.
- Frontend `npx tsc --noEmit`, `npm run lint`, and `npm run build` all pass.
- Automated API tests verify owner/project authorization, candidate edits and
  approval, segment caption timing/speaker preservation, heuristic ranking,
  transcript reuse, job failure/retry/cancellation, and rejection of styled
  captions without transcript timing or animated word highlighting without
  word timestamps.

## Real-media verified

- A generated two-shot video is processed by the installed PySceneDetect
  ContentDetector and the test verifies multiple real scene intervals.
- A locally generated sine-wave recording with a silent interval is analyzed by
  the installed FFmpeg `silencedetect` filter; detected timestamps overlap the
  known silent interval.
- A generated black video is rendered with a styled caption through FFmpeg.
  FFprobe verifies **720 × 1280 (9:16)** and a `mov_text` subtitle stream; a
  decoded output frame contains the rendered caption pixels.
- An API workflow reuses a saved timed transcript, persists an explainable
  candidate and exports a real FFmpeg clip into the owned media library.
- The MLX provider integration path was not exercised with real model inference
  during this milestone. Tests use saved transcript data or explicitly disable
  transcription; no local model was downloaded or invoked.

## Browser verified

- The Next.js route at `/smart-clipper` loaded with the updated workspace and
  analysis controls. The page displayed the local workspace sign-in gate.
- No authenticated project, upload, or editor interaction was performed in
  the browser, so those interactions are not marked as manually verified.

## Remaining limitations

- Transcription depends on an existing completed transcript or the already
  configured local provider. On this verification run, actual MLX inference was
  not run. Provider/model availability, language accuracy, and inference time
  therefore remain environment-dependent and unverified here.
- Available transcription timestamps are segment-level. Word-level captions
  and animated word highlighting remain unavailable; the API explicitly
  rejects requests for animated word highlighting.
- Existing speaker labels are passed through only; there is no speaker
  diarization provider in this workflow.
- Sentence completeness uses recognized punctuation and segment boundaries.
  The system cannot reliably infer sentence boundaries for transcripts missing
  punctuation, and it skips overlong sentence units rather than knowingly
  cutting them to fit a target duration.
- Scene-only candidates are time windows, not semantic highlights. Silence
  detection uses a fixed local FFmpeg threshold and minimum duration; it is not
  adaptive to recording noise.
- Face-aware reframing, face detection, active-speaker tracking, and genuine
  emotion/virality understanding are not implemented.
- `animated_highlighting` is intentionally unsupported until a provider
  supplies verified word-level timing. SRT/VTT and selectable subtitles use
  segment-level timestamps.
- Browser verification was limited by the sign-in gate. Export/render tests use
  synthetic local fixtures, not a creator's real source video.

## Environment and dependency scope

- No dependency manifest, PostgreSQL setting, MLX worker configuration,
  IndicTrans2 authentication/configuration, or model cache was modified.
- PySceneDetect was already declared in the backend dependencies. No packages
  or model weights were installed or downloaded.
- All processing remains local in the existing FastAPI worker architecture;
  no paid API or TTS integration was introduced.
