# Video Studio Timeline Rendering Engine

## Implemented

- The existing project `Timeline.timeline_data` JSON and `ProcessingJob` queue
  now carry the renderable timeline. No database migration or backend/frontend
  dependency change was needed.
- Timeline validation supports up to 32 ordered tracks and 500 clips, source
  trims, timeline placement and gaps, visibility via track mute, clip opacity,
  position, scale, volume, fades, transition settings, color controls, and
  clip-relative keyframes. Keyframes support linear and held interpolation.
- The export API checks project ownership and that every referenced media asset
  belongs to the requesting user. It stores opaque storage keys in the job,
  not filesystem paths. FFmpeg is launched with argument arrays, and media is
  staged/copied in bounded chunks into temporary directories.
- The worker renders ordered video and overlay tracks over a black canvas,
  leaving gaps black. It mixes available audio from all active audio/video
  clips, honoring clip and track volume, clip keyframes, trim, timeline offset,
  and fades. It reports FFmpeg progress and cleans temporary/partial output
  after failure or cancellation.
- Video effects include fades, cross-dissolves and left/right wipes. Image
  overlays can be positioned, scaled, faded and keyframed; color adjustments
  include brightness, contrast and saturation. Subtitle-track text is rendered
  to temporary RGBA images with Pillow and burned into the result. This avoids
  dependence on FFmpeg `drawtext`/libass, which are absent from the FFmpeg
  build checked on this Mac.
- The editor retains existing project/media selection, proxy preview, drag
  positioning, clip trimming, zoom, and export polling. It now exposes track
  creation/order/mute/lock/volume controls, audio waveforms, clip properties,
  transitions, color controls, keyframes, and full-timeline MP4 export.

## API endpoints

- `GET` / `PUT /api/v1/projects/{project_id}/timeline` — load and save the
  validated timeline JSON.
- `POST /api/v1/projects/{project_id}/timeline/export` — enqueue a full
  timeline render, or a requested selection of video clips.
- `GET /api/v1/timeline/exports/{job_id}` — read owner-scoped job status and
  progress.
- `POST /api/v1/timeline/exports/{job_id}/retry` — retry a failed or cancelled
  job if retries remain and source objects still exist.
- `POST /api/v1/timeline/exports/{job_id}/cancel` — cancel queued work or ask
  an active worker to stop.
- `GET /api/v1/timeline/exports/{job_id}/download` — stream a completed MP4
  only to its owner.

## FFmpeg and export presets

- The worker creates a `filter_complex` graph with a black canvas, timestamped
  clip overlays, per-clip alpha/position/scale/effects, and delayed/mixed audio.
  Subtitle cards are generated as temporary PNG inputs. FFmpeg is run as a
  subprocess with separate arguments; it is not invoked through a shell.
- Output video uses `libx264`, `ultrafast`, two threads, `yuv420p`, the
  timeline frame rate, and `+faststart`. Mixed audio uses AAC at 192 kbit/s.
- `720p`, `1080p`, and `4k` select long edges of 1280, 1920, and 3840 pixels.
  Aspect ratio is preserved and dimensions are even. A preset is rejected if
  any rendered video source is below that preset's long-edge resolution.
  Without a preset, the saved timeline dimensions are used.
- Wipes use an FFmpeg `geq` alpha mask; fades/dissolves use alpha composition.
  A dissolve needs visible footage beneath the transitioning clip to blend
  between footage; otherwise it fades against the underlying track/canvas.

## Automated-test verified

- Full backend suite: **76 passed**.
- `test_timeline_save_reload_owner_checks_and_ffmpeg_export` verifies timeline
  save/reload, project/media ownership rejection, completed 720p export and
  download/FFprobe dimensions, source-resolution preset rejection, cancellation,
  retry, and cross-user export access denial.
- `test_4k_preset_renders_when_source_resolution_and_encoder_allow_it` renders
  and checks a real 3840x2160 export.
- `test_full_timeline_composites_tracks_gaps_transitions_overlays_subtitles_and_audio`
  uses generated local fixtures and the application API to render a 3-second
  160x90 output. FFprobe verifies duration, dimensions, and audio/video streams.
  Decoded-frame assertions check image overlay positioning/keyframes, color
  adjustment, dissolve, both wipe directions, subtitle pixels, and black gaps.
  Audio RMS checks verify the mixed audio's timeline placement and fade behavior.
- Ruff and format checks pass for the four modified backend Python files.
  Repository-wide `ruff check app tests` still reports an import-order issue in
  the unrelated, unchanged `backend/app/services/voice_processing.py`.
- Frontend ESLint, `npx tsc --noEmit`, and `npm run build` all pass.

## Real FFmpeg verified

- The automated API tests above invoke the installed FFmpeg and FFprobe against
  generated local files. The 4K preset test confirms a decoded/exported
  3840x2160 result; the composite test inspects decoded output pixels and audio,
  rather than only checking the filter graph or job status.
- Test videos/audio are locally generated fixtures. No external service, paid
  API, additional model, or model download is involved.

## Browser manually verified

- The Video Studio route loaded and showed the updated studio description.
  Authentication was required before the editor became available. No signed-in
  timeline editing, render, or download interaction was manually verified.

## Not implemented

- Real-time composite playback of the entire timeline in the browser; preview
  remains an individual selected asset using its proxy when available.
- Cross-track drag-and-drop, draggable trim handles, advanced title typography,
  transition easing controls, keyframe curves, and full NLE-grade color tools.
- Dedicated standalone title and watermark workflows beyond text clips on the
  subtitle track and image/video clips on overlay tracks.
- A persistent distributed job broker: exports continue to use the existing
  in-process polling worker architecture.
- An explicit automated test that forces an FFmpeg render failure and verifies
  the failed-job retry path; cancellation/retry and successful render paths are
  covered.

## Known limitations

- Wipes and dynamic opacity/position/scale use per-pixel FFmpeg expressions and
  can be slow, especially at 4K. The encoder is limited to two threads, but
  memory/space availability and render time still depend on the host.
- Subtitle appearance is currently a fixed white-on-dark rounded card with
  automatic wrapping and platform font fallbacks; per-word styling and font
  selection are not exposed.
- Track order is visual stacking order; later tracks composite over earlier
  ones. Mute is the visibility control. A transition without underlying
  footage blends against the base canvas.
- Completed exports remain in storage until separately cleaned up. There is no
  automatic export retention policy.
- Local-browser authentication prevented manual verification of the editing
  interactions. The automated tests verify API and rendered media behavior,
  not browser usability.
