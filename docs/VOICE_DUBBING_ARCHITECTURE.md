# Voice Studio and dubbing architecture

## Current implementation status

Voice Studio keeps transcription, translation, and speech synthesis as separate optional provider capabilities. The installed MLX Whisper path can transcribe locally on supported Apple Silicon macOS. An optional IndicTrans2 HTTP worker and asynchronous translation workflow are implemented, but no model packages or weights are installed and no real inference has run. The UI presents languages as candidates only; generated translations require creator review. Text-to-speech remains unavailable, so dubbing plans still require user-supplied audio.

No TTS model weights are downloaded by this workflow. Voice profiles store an owned reference asset and an explicit authorization attestation only; they do not create a clone. Consent is a user-provided statement and is not independent identity or permission verification.

## Persistence

- `Transcript` and `TranscriptSegment` store the source media, recognized language, timestamped text, and manually editable speaker labels and translations.
- `TranscriptRevision` stores an immutable full pre-edit snapshot. Editing text, speaker assignment, or translation creates a revision while leaving source timestamps unchanged.
- `VoiceConsent` and `VoiceProfile` associate authorization records and owned reference media with the account.
- `DubbingProject` stores a target language, a JSON glossary, and per-segment source and translated text, translation status/provider/model/revision/license provenance, original and editable timing, optional authorized voice profile, user-supplied audio asset, measured duration, approval state, and timing-conflict state.
- `ProcessingJob` tracks transcription, translation, and asynchronous audio/video export status, progress, retries, cancellation, and errors.

## Workflow and API

All endpoints are under `/api/v1/voice` and require the signed-in user. Transcript, dubbing project, voice profile, audio asset, and optional source-video reads and mutations verify account ownership. The optional source video must also belong to the dubbing project's project.

| Endpoint | Purpose |
| --- | --- |
| `GET /providers` | Report actual provider availability. |
| `GET /transcripts`, `GET /transcripts/{id}` | List and retrieve saved transcripts. |
| `PATCH /transcripts/{id}/segments/{segment_id}` | Edit transcript text, manual speaker label, or manual translation; preserve timestamps and create a pre-edit revision. |
| `GET /transcripts/{id}/revisions` | Retrieve the user's transcript revision snapshots. |
| `GET /transcripts/{id}/subtitles/{srt|vtt}` | Export source transcript subtitles. |
| `GET`, `POST`, `PATCH /dubbing-projects...` | Create, retrieve, and update a target-language plan, its glossary, translations, voice assignments, timing, audio references, and approvals. |
| `POST /dubbing-projects/{id}/translate` | Queue translation for missing segments or regenerate all segments through the configured local worker. |
| `POST /dubbing-projects/{id}/segments/{segment_id}/translate` | Queue or regenerate one translation segment. |
| `POST /dubbing-projects/{id}/segments/{segment_id}/regenerate` | Return an explicit unavailable response until a tested synthesis workflow is configured. |
| `GET /dubbing-projects/{id}/subtitles/{srt|vtt}` | Export translated subtitles. When a user-supplied audio duration is known, subtitle end time follows the full audio duration at the selected speech rate. |
| `POST /dubbing-projects/{id}/export` | Queue FFmpeg assembly from user-supplied audio; optionally mux it with an owned project video. |
| `POST /speech-preview` | Return an explicit unavailable response until synthesis is configured. |
| `GET /jobs/{id}` | Poll the status and result of voice processing jobs. |
| `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retry` | Cancel a queued/processing voice job or retry failed translation segments. |

## Audio and video export behavior

Each export segment must reference an owned audio asset whose media processing has measured its duration. FFmpeg applies the selected playback rate and delays each complete segment to its start time. It does not trim segments to the planned slot or cap the result to the original video duration. A timing conflict is reported when the adjusted audio duration exceeds the segment's editable timing slot; creators can manually revise timing or speech rate before export.

An optional MP4 export copies the original video's video stream (`-c:v copy`) and muxes the assembled dubbed audio. It does not re-encode the video and replaces rather than mixes the video's original audio track. SRT and VTT are separate subtitle downloads; they are not burned into the MP4.

Jobs record failures explicitly and remove temporary output assets after an export failure. The worker uses argument arrays for FFmpeg subprocess invocation.

## Provider and resource boundaries

- Transcription: isolated, optional local MLX Whisper worker on supported Apple Silicon macOS; MLX is not installed in Linux containers.
- Translation: the optional backend adapter sends text to a separately installed local worker using a bearer token. The worker loads one direction-specific model at a time from local, revision-pinned snapshots and has no model-download path. It accepts candidate English↔Hindi/Telugu/Tamil/Kannada/Malayalam pairs; no language is supported or quality-verified until real inference and reference evaluation pass. Indic↔Indic is rejected. Segment translations are independent; neighboring utterances are not currently supplied as model context.
- Speech synthesis: provider interface is separate, but no TTS model is selected, downloaded, or enabled. User-supplied audio is the only supported source of dubbing audio.
- Voice identity: no unauthorized cloning is implemented. Assignments are limited to profiles with active user consent and owned reference assets.
- Heavy models remain optional and are not downloaded or loaded automatically.

## Verification

The backend tests cover manual transcript edits and revision snapshots, timing preservation, ownership checks, fake-provider translation persistence, glossary and approval behavior, translation retries/cancellation, audio duration conflicts, subtitle timing, asynchronous job failure handling, full-length supplied-audio assembly, and optional MP4 stream muxing. They do not measure translation quality. Run them from `backend/` with:

```sh
python -m pytest tests/test_voice.py translation_worker/tests
```

See [the translation quality report](./TRANSLATION_QUALITY_REPORT.md) for
candidate metadata, reference-data limitations, and the approval required
before installing packages or downloading gated model weights.

The frontend uses the existing Next.js application and can be checked from `frontend/` with:

```sh
npm run lint
npx tsc --noEmit
npm run build
```
