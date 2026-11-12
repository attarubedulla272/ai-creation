# Video Editor Completion Report

## Milestone 4.2 — Text fit and pre-export validation

### Fully verified

- **Pre-export validation:** Added owner-scoped validation that uses the actual Pillow text renderer, the selected export resolution, its installed fonts, line wrapping, and line limit. The export endpoint performs the same blocking check before creating a job; blocking requests return a structured clip-specific error and do not queue an export. The editor validates its current draft after edits and validates again immediately before export.
- **Actionable editor results:** Blocking errors and non-blocking warnings identify the clip and track, explain the issue, recommend a correction, and link directly to the clip. Selected-clip warnings appear beside the text controls. Warnings cover worker font fallback, subtitle lines over two rows, and subtitle durations under 0.5 seconds. Missing glyphs, empty text, unrenderable layouts, and unsupported text clip filters block export.
- **Shared wrapping and fitting:** Automatic word wrapping was already present in both preview and renderer. The worker's exact Pillow layout is authoritative for preflight and fit proposals. Box-width proposals expand to the full available width; shrink proposals search for a valid font size down to the user's chosen minimum; proposals are checked before being returned.
- **Text and subtitle splitting:** The editor previews changes before applying them. The backend recursively splits at word boundaries until each proposed clip passes the renderer, preserves all original text including whitespace and punctuation, sequences clips without adding time or overlap, and distributes durations in proportion to text length. Subtitle proposals warn when any resulting cue lasts under 0.5 seconds. Proposals are undoable and pass through the existing save/reload path.
- **Preview/export and real rendering:** Playwright verifies oversized-text blocking, width and shrink proposals, exact text preservation, undo/redo, save/reload, and a real 1280×720 FFmpeg export with visible rendered text. It also checks the missing-glyph blocker and subtitle splitting workflow. Backend tests verify validation categories, ownership, proportional subtitle timing, persistence, and a successful FFmpeg export after fitting.
- **Font handling:** The worker reports available font-family alternatives for fallback and missing-glyph results. Missing characters cannot be repaired by fitting and are reported as blocking errors. No font packages, dependencies, or migrations were added.

### Partially verified and known limitations

- Browser font metrics and Unicode shaping can differ from Pillow. Fit validity is guaranteed against the active export worker and requested resolution, not pixel-identical browser typography.
- The box-fit action widens to the maximum supported width; there is no independent height setting because rendered box height follows the wrapped text. If widening alone is insufficient, the editor offers shrink or split proposals.
- Splitting requires word boundaries. A single unbroken token that cannot render at the current settings must be widened or reduced in size. The worker caps a timeline at 500 clips. Subtitle durations are distributed proportionally by character count, not speech cadence; review short-duration warnings manually.
- Available-family alternatives indicate font files present on the export worker; they are not a promise that every font can render every script. Glyph compatibility is checked for the actual text.
- Enabled clip effects and non-default brightness, contrast, or saturation on text clips are unsupported by the text export branch and block export. Text fades are alpha-composited in FFmpeg.

### UI-only or browser-only behavior

- The browser canvas is an immediate visual approximation. Its native font selection, shaping, and pixel measurements can differ from the export worker; its layout is not used to decide whether an export is valid.
- No fit action is UI-only: all proposals are checked against the shared export renderer before they can be applied.

### Not implemented

- Independent text-box height controls, automatic font installation/bundling, and cross-platform font parity.
- Splitting an unbroken word at arbitrary character positions or automatic subtitle timing based on speech cadence.

### Automated verification

- Focused timeline tests: **13 passed**.
- Full backend test suite (`backend/.venv`): **102 passed**.
- Ruff on changed backend implementation/tests: **passed**.
- Frontend ESLint: **passed**.
- TypeScript (`npx tsc --noEmit`): **passed**.
- Full Playwright suite in installed Chrome: **6 passed**.
- Production build (`npm run build`): **passed**.

### Recommended next milestone

Improve platform font coverage and give users more control over box dimensions and subtitle timing. Keep renderer-based preflight as the source of truth; do not claim typography parity across systems without cross-platform render verification.

## Milestone 4.1 — Text and subtitle hardening

### Fully verified

- **SRT and WebVTT:** Parser and serializer tests cover SRT↔VTT conversion, multiple and overlapping cues, UTF-8 Unicode, BOM, CRLF/LF, cue identifiers and VTT settings, millisecond precision, timestamps near the 24-hour timeline limit, multiline/edge whitespace, empty files, missing text, malformed timestamps, and 10,000-character cues. Same-time cues retain input order. Import/export endpoints enforce project ownership and return helpful errors for invalid format, non-UTF-8 data, empty cues, and files over 2 MB.
- **Browser subtitle workflow:** Playwright imports an SRT and a BOM/CRLF WebVTT file with overlapping Unicode cues, edits/splits/combines subtitle clips, saves and reloads their times, and exports both formats. The cross-format downloads confirm the imported content survives conversion.
- **All seven title presets:** Playwright creates basic, centered, opening, ending, lower-third, section-heading, and callout titles; checks each preset’s initial position/font settings; edits content, font family/weight/style/size, text and background colors, opacity, outline, shadow, alignment, position, and duration; then duplicates/deletes, saves/reloads, and confirms the stored values. Browser canvas checks and exported-frame pixel checks verify all seven styled overlays in the same real FFmpeg export.
- **Undo/redo:** The browser text workflow verifies title-style undo and redo. Subtitle split/combine and title duplication/deletion are also exercised.
- **Unicode rendering on this Mac:** Pillow generated non-empty overlay images for English, Telugu, Hindi, Tamil, Kannada, and Malayalam. The real FFmpeg timeline test rendered a mixed-script subtitle and extracted visible glyph pixels. Emoji rendering was probed: the installed font candidates on this machine do not cover the tested emoji, and the renderer returns a clear missing-Unicode-font error rather than emitting replacement glyphs.
- **Real FFmpeg/FFprobe:** The backend export test checks output at 160×90 and extracted subtitle/title pixels. The browser test exports the saved seven-preset timeline at 1280×720, uses FFprobe to verify dimensions, and checks representative pixels for every preset. This verifies representative behavior, not pixel-perfect parity.
- **Security and validation:** Subtitle upload is limited to 2 MB, requires `.srt`/`.vtt` and UTF-8, and is project-owner scoped. Text and style values are schema bounded; font family is an enum and renderer font paths come only from fixed system candidates. Text is rasterized to PNG before FFmpeg composition; FFmpeg runs through argument-vector subprocess execution, not a shell command built from text. Unsupported font glyphs and text overlays exceeding the renderer’s line limit fail with actionable messages visible in the export job status.

### Partially verified and known limitations

- **Typography parity:** Canvas backing dimensions match timeline/export dimensions. Position, box width, and font size use normalized frame coordinates and output-frame pixels; text wrapping, line spacing, overlay scaling, and rectangular backgrounds were aligned. Browser font matching, glyph shaping, metrics, antialiasing, and shadow blur still vary from Pillow/system fonts and FFmpeg. Pixel-perfect preview/export parity is not claimed.
- **Font portability:** Known macOS, Windows, and Linux font paths are candidates only; no font package is bundled. The requested Indic scripts rendered on this Mac, but other hosts may lack a font with the necessary glyph coverage. Such exports fail explicitly. Emoji support is not available on the tested Mac.
- **Long text:** Import and persistence preserve cues up to 10,000 characters. When a text overlay wraps to more than the renderer’s resolution- and font-size-dependent maximum (capped at 12 lines), export now fails with a message to reduce font size or split the text; the previous behavior silently truncated it. The job status surfaces this error. The hard limit remains a usability limitation.
- VTT import/export was exercised in Playwright. The browser workflow checks representative cue timing/content and overlapping preview; exact glyph-shape parity for every supported language is not asserted in browser canvas.
- No effects, transitions, or keyframe-animation work was added by this milestone.

### Automated verification

- Focused timeline tests: **11 passed**.
- Full backend test suite (`backend/.venv`): **100 passed**.
- Ruff on changed backend implementation/tests: **passed**.
- Frontend ESLint: **passed**.
- TypeScript (`npx tsc --noEmit`): **passed**.
- Production build (`npm run build`): **passed**.
- Full Playwright suite in installed Chrome: **5 passed**.
- No dependencies or database migrations were added. Playwright now uses a stable, isolated frontend port (`VIDEO_EDITOR_E2E_FRONTEND_PORT`, default `3100`) and passes that origin to the local test API to avoid reusing the unrelated/stale server on port 3000.

### Milestone 4.1 follow-up

The long-text warning and user-controlled fit/split workflow recommended for Milestone 4.1 are implemented in Milestone 4.2 above.

## Milestone 4 — Text, titles and subtitle editor

### Text timeline functionality

- **Persistent text clips: completed.** Overlay and subtitle clips use the existing timeline document and a shared validated text-style model. Text, timing, position, alignment, font settings, color/background, outline, shadow, opacity, fades, and z-order are saved with the timeline. Defaults preserve timelines created before text clips existed; no database migration was needed.
- **Clip editing: implemented.** Text clips use the editor's timeline selection, move, trim, split, duplicate, delete, undo/redo, save, and reload flows.
- **Title presets: partially verified.** Seven presets are available: basic, centered, opening, ending, lower third, section heading, and callout. Browser and FFmpeg workflows exercise opening titles and lower thirds; the remaining presets are not individually covered by browser/export assertions.
- **Lower thirds: verified in representative cases.** Browser preview and real FFmpeg tests exercise a styled lower-third overlay.

### Subtitle editing

- **Subtitle editing: browser-verified for the main workflow.** The Playwright workflow imports SRT, edits Unicode text and styling, splits and combines cues, exports SRT, saves and reloads the project, and includes the resulting cues in an MP4 export.
- **SRT/VTT utilities: backend-verified.** Tests cover SRT and VTT parsing/serialization, timestamp errors, and owner-scoped import/export endpoints. The browser workflow currently exercises SRT rather than VTT.
- This milestone provides subtitle editing only; it does not claim speech recognition, automatic subtitle generation, or translation.

### Browser preview

- **Text preview: partially verified.** The composite canvas renders active text clips over the timeline at the playhead, including multiple overlapping overlay/subtitle clips and supported style controls. Playwright verifies active overlays and representative background colors for an opening title, lower third, and subtitles.
- Browser text uses browser typography and is not pixel-identical to the FFmpeg output. Unicode glyph appearance and every font/style combination have not been independently asserted in the browser.

### FFmpeg rendering

- **Text export: verified for representative cases with real FFmpeg.** Pillow-generated overlays are composited by the timeline renderer with clip timing and track/z-order. The backend test renders an opening title, lower third, overlapping Unicode subtitles, and checks representative output pixels; the Unicode glyph assertion is isolated after the title expires. FFprobe confirms the deterministic test output is `160x90`.
- The Playwright workflow exports the saved timeline through the backend, downloads the MP4, verifies `1280x720` with FFprobe, and checks rendered title pixels from an extracted frame. This is not a claim of pixel-perfect typography parity.
- Font selection is constrained to known system fonts. The renderer checks glyph coverage and reports a clear failure if no available candidate can render the requested text; font appearance can vary by host.

### UI-only or not yet verified

- The remaining five title presets have editor controls but are not individually exercised through browser preview and exported-frame assertions.
- VTT import/export is covered by backend tests, not by the browser workflow.
- All text style values, font availability across operating systems, and text clip operations in every overlapping-track scenario do not yet have dedicated end-to-end assertions.

### Automated verification

- Focused timeline tests: **9 passed**.
- Full backend test suite: **98 passed**.
- Real FFmpeg/FFprobe text and Unicode rendering test: **passed**.
- Ruff on changed backend files: **passed**.
- Frontend ESLint: **passed**.
- TypeScript (`npx tsc --noEmit`): **passed**.
- Production build (`npm run build`): **passed**.
- Playwright in installed Chrome: **4 passed**, covering composite preview/audio, effects and transitions, text/subtitle editing and export, and backend setup guidance.
- No dependencies or database migrations were added.

### Known limitations and next recommended milestone

- Browser and FFmpeg typography/rendering can differ; exact typography parity is not claimed.
- Browser testing does not yet cover every title preset, VTT round-trip, every text style field, or every font/Unicode combination.
- **Next milestone: text/subtitle hardening.** Add browser coverage for VTT import/export and text clip operations across overlap cases, verify font/glyph behavior on supported environments, and expand exported-frame assertions across presets and style controls before pursuing typography parity or advanced animation.

## Milestone 3 — Effects and transitions

### Effects completed

- Added an ordered, per-clip `effects` list for brightness, contrast, saturation, grayscale, and blur. Effects have unique IDs, enabled state, type-specific value limits, and stable ordering. Missing effect lists default to empty, so earlier timeline documents continue to load.
- Added Effects controls to add, remove, enable/disable, reset, and edit effect parameters, with undo/redo and normal timeline save/reload.
- The browser composite applies the supported filter chain to clips. The FFmpeg renderer builds the corresponding filters in the same order. Unsupported preview behavior is disclosed instead of shown as if applied.
- Existing clip-level brightness, contrast, saturation, opacity, transform, and fade fields remain available for compatibility; they were not migrated into the new effects list.

### Transitions completed

- Added controls for fade-in-from-black, fade-out-to-black, and incoming cross-dissolve.
- New cross-dissolves require versioned transition data and a preceding video clip on the same track with enough timeline overlap. Legacy unversioned cross-dissolves remain accepted only when their existing identity and timing are unchanged.
- Existing timelines remain JSON-compatible; no database migration or dependency was added.
- The FFmpeg renderer processes fades and cross-dissolves. The canvas preview applies black fades and cross-dissolve blending. Wipe transitions are not offered by the new controls and are not represented in the browser preview.

### Preview and export verification

- **Browser preview: partial.** Playwright verifies grayscale parameter changes in the canvas, undo/redo, and cross-dissolve blending. Other effect filters and black fades are implemented but are not individually asserted in the browser test. The browser canvas and FFmpeg use different filtering/color pipelines; pixel-perfect parity is not claimed.
- **Real FFmpeg effects render: passed.** A deterministic test video is exported with brightness, contrast, saturation, grayscale, blur, fade-in, and fade-out clips. Extracted frames are checked for brightness, channel differences, blur smoothness, and fade progression. FFprobe verifies the rendered dimensions and duration.
- **Real FFmpeg transition render: passed.** The Playwright workflow saves and reloads a timeline with a cross-dissolve, exports through the backend renderer, downloads the MP4, verifies `1280x720` with FFprobe, and checks a representative exported transition pixel.

### Automated verification

- Focused timeline tests: **6 passed**, including schema bounds/order, overlap validation, rejection of newly added unversioned cross-dissolves, and real FFmpeg output checks.
- Full backend suite: **96 passed** using the project's backend virtual environment.
- Ruff on changed backend files: **passed**.
- Frontend ESLint: **passed**.
- TypeScript (`npx tsc --noEmit`): **passed**.
- Production build (`npm run build`): **passed**.
- Playwright: **2 passed**, including effects/transition editing, undo/redo, save/reload, browser preview assertions, backend export, download, FFprobe, and exported-frame checks.

### Known limitations and remaining work

- Browser and FFmpeg outputs are functionally aligned for the tested cases, not pixel-identical.
- Browser verification does not yet cover each effect type, fade boundary, invalid overlap case, or legacy-transition round trip independently.
- Existing clip properties coexist with the ordered effects list for backward compatibility. A future schema evolution could consolidate overlapping properties after a compatibility plan.
- Cross-dissolve validation uses timeline overlap; source-handle availability is not separately modelled. Wipe preview is unsupported.
- Continue with focused browser and real-render regression tests for all effect values, transition edge cases, and legacy timeline round-trips before claiming full preview/export parity.

## Milestone 2 — Composite preview baseline (historical verification)

## 1. Features completed in this milestone

- Replaced the single-source preview with a browser canvas composite for active video and image clips on visible video/overlay tracks. It follows timeline positions, black gaps, timeline track order, clip position/scale/opacity, and text clips; later tracks draw over earlier tracks.
- Video elements seek to the active clip's source-in plus its elapsed timeline time. Empty visual sections clear to black rather than retaining a stale frame.
- Added a browser Web Audio mix for media with audio streams. It schedules clips at their timeline positions and source trims, supports overlapping clips, track mute/solo, clip and track volume, volume keyframes, and fades. Seeking rebuilds scheduled sources.
- Kept a single requestAnimationFrame timeline clock for playhead, video preview, and audio scheduling. Play, pause, frame-step seeking, scrubbing, timeline-end stop, project-change cleanup, and tab-hidden pause are wired into the editor.
- Added clear preview notices for effects and transitions not reflected in the browser composite, simplified subtitle rendering, and preview load/play errors.
- Added Playwright configuration, an isolated SQLite-backed FastAPI test server, and deterministic local FFmpeg media fixtures. Tests exercise editor preview and export workflows against the real frontend and backend rather than API mocks.

## 2. Features partially completed

- **Composite video preview: partial.** Overlapping tracks, ordering, gaps, seeking, and track mute/visibility behavior are browser-tested. The implementation uses native browser decoders and canvas, not the backend's rendered frames. Non-zero source trims, images, subtitle timing/style, and every track ordering combination are not independently covered by browser assertions.
- **Multi-track audio preview: partial.** Two simultaneous tracks are decoded and scheduled, and seeking while playing reschedules them. The browser test checks scheduling state rather than recording/analysing audible output, so sample-accurate audio/video synchronization is not proven. Browser decoding and timing can vary by format and device.
- **Synchronization: partially verified.** The shared timeline clock drives seeking and scheduling; tests verify playhead movement, seek behavior, audio schedule counts, and cleanup. They do not measure rendered audio loopback against video frames or guarantee frame-perfect playback.

## 3. Features still UI-only or not verified

- Existing timeline controls for effects, transitions, transforms, keyframes, and subtitle styling were not all exercised through browser edit-save-render comparisons in this milestone.
- Browser text/subtitle rendering is a simplified canvas treatment; it does not reproduce all renderer typography or styling options.
- Audio waveform display remains a media-library derivative, not a live waveform generated from the preview mix.

## 4. Features not implemented

- Exact browser-preview parity with the FFmpeg renderer.
- Visual rendering of color effects, blur, transitions, and fades in the browser composite. The preview explicitly reports unsupported effects/transitions rather than presenting them as applied.
- Automated browser verification of non-zero source trims, image overlays, subtitle appearance, and audio sample synchronization.
- Browser preview of every supported media format; unsupported decoding surfaces an error or the empty-preview fallback.

## 5. Real FFmpeg verification

- The Playwright export workflow saves a timeline edit (moves a clip to `0.5s`), reloads the project, exports the saved timeline through the backend, downloads the actual MP4, and verifies `1280x720` with FFprobe. Local `1280x720` video fixtures are used because the backend correctly rejects a 720p preset when source media is below the required long-edge resolution.
- The full backend suite includes the three timeline tests, which use real FFmpeg rendering and FFprobe checks for persistence, timeline composition, gaps, and export output. The browser export also exercises the actual timeline export worker; it is not mocked.

## 6. Automated test results

- Full backend suite: **93 passed**.
- Focused timeline tests: **3 passed** as part of the full backend run.
- Ruff: **passed** for `backend/tests/e2e_server.py`.
- Frontend ESLint: **passed**.
- TypeScript (`npx tsc --noEmit`): **passed**.
- Production build (`npm run build`): **passed**, including `/video-studio`.
- Playwright: **2 passed**.

## 7. Browser test results

Playwright ran against the existing Next.js development server, an isolated SQLite-backed FastAPI server, and locally generated media:

- Opened the Video Editor with an authenticated test user and a project containing multiple video and audio tracks.
- Verified the topmost overlapping video appears in the canvas, seeking changes the displayed frame, and muting the upper video track reveals the lower track.
- Verified gaps show no stale visual and both audio clips are decoded and scheduled during playback; seeking while playing reschedules audio, pause/project switch stops scheduled sources, and the playhead resets on project change.
- Changed a clip's timeline position, waited for save, reloaded the page, and verified the saved position.
- Exported that saved timeline through the backend, downloaded the result, and verified its `1280x720` dimensions using FFprobe.
- Result: **2 Playwright tests passed**. Browser behavior not listed above is not claimed as verified.

## 8. Known limitations

- Browser preview is an approximation produced by browser codecs and canvas; final output is rendered by FFmpeg and can differ.
- Preview applies supported position, scale, opacity, and simplified text treatment, but not all renderer effects, transitions, fades, rotations, or subtitle styling.
- Web Audio scheduling and browser video decoding have runtime/device timing limits. Automated tests validate source scheduling and timeline controls, not audible output or sample-level synchronization.
- The Playwright suite uses local fixtures and one browser engine (installed Chrome); it does not establish compatibility across browsers or devices.

## 9. Exact next recommended milestone

Add focused browser assertions for non-zero source trims, image overlays, subtitle timing, and track ordering; capture browser audio output to measure synchronization against video during seeking and playback. Use those results to close the remaining preview gaps before expanding browser effect or transition support.
