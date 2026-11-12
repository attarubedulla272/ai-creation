# Model and provider license audit

This audit distinguishes code/provider adapters from model weights. No model
weights were automatically downloaded during the audit. No paid AI API is a
required dependency.

| Model/provider | Repository or source | License / commercial status | Hardware and installation | External API | Tested / optional |
|---|---|---|---|---|---|
| MLX Whisper adapter (`mlx-whisper`) | `mlx-community/whisper-tiny` configured by default; upstream reference model is `openai/whisper-tiny` | The Python package is documented as MIT; the upstream model card is Apache-2.0. The converted `mlx-community/whisper-tiny` card does not declare a license in the project notes. Converted weights’ provenance, commercial permissions, and attribution requirements remain unverified. | Native Apple Silicon macOS only; install separately with the `voice-mlx` extra. Do not run inside Linux Docker. Small Whisper model; do not load concurrently with other large models. | None; local inference | Adapter is optional. A prior real short-audio inference is documented in the root README; it was not repeated for this audit. |
| Candidate Whisper model (`mlx-community/whisper-tiny-fp16`) | [Hugging Face model repository](https://huggingface.co/mlx-community/whisper-tiny-fp16), converted from `openai/whisper-tiny` using `mlx-audio-plus` | The model repository metadata declares Apache-2.0. Its README identifies the upstream model. Preserve the license and attribution notices when redistributing; review the model and upstream terms before commercial distribution. The `mlx-audio-plus` Python package separately declares MIT; that is not the model license. | Model files total about 75.2 MB (71.7 MiB): 74,386,126-byte `model.safetensors`, 816,730-byte `multilingual.tiktoken`, and small config/card files. Requires an MLX-capable Apple Silicon macOS environment and the `mlx-audio-plus` runtime in a separate worker environment. | None; local inference | English, Hindi, and Telugu synthesized-speech tests ran on M2 / 8 GB. English WER/CER: 7.14% / 1.41% on one 10.4-second sample; Hindi and Telugu returned no segments. These are not human-recording benchmarks and do not establish Hindi/Telugu support. See [MLX_TRANSCRIPTION_TEST.md](./MLX_TRANSCRIPTION_TEST.md) and [TRANSCRIPTION_QUALITY_REPORT.md](./TRANSCRIPTION_QUALITY_REPORT.md). |
| Translation worker adapter | In-repository HTTP adapter and optional isolated worker | Adapter code is separate from model-weight terms. No provider language is marked supported until real inference and quality review pass. | Worker packages are installed only in `backend/translation_worker/.venv`; no weights installed. Main backend has no translation-model dependency. | Optional authenticated local HTTP worker only | Queue, persistence, approval, retry, cancellation, and model-free API paths are tested with a fake provider. Real inference not run. |
| IndicTrans2 En→Indic Distilled 200M | [Hugging Face repository](https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M), pinned revision `2cfd0a20057756d756bf3e53528f492afc52f91a` | Repository metadata and bundled `LICENSE` declare MIT. Review model code, notices, and any separate terms before deployment; repository access is gated and requires accepting Hugging Face conditions. | One safetensors file is 1,098,427,592 bytes (~1.02 GiB). Optional isolated worker only; weights are not downloaded. | None; planned local inference | Candidate for English→Hindi, Telugu, Tamil, Kannada, Malayalam. No real inference; no language verified. |
| IndicTrans2 Indic→En Distilled 200M | [Hugging Face repository](https://huggingface.co/ai4bharat/indictrans2-indic-en-dist-200M), pinned revision `d66a2122ad6d28184f3dc3797b652bd80ae3f65f` | Repository metadata and bundled `LICENSE` declare MIT. Review model code, notices, and any separate terms before deployment; repository access is gated and requires accepting Hugging Face conditions. | One safetensors file is 913,353,672 bytes (~0.85 GiB). Both directional checkpoints total ~1.87 GiB of weights and are loaded one at a time. | None; planned local inference | Candidate for Hindi, Telugu, Tamil, Kannada, Malayalam→English. No real inference; no language verified. |
| Indic-Translate | [Bodhan AI model repository](https://huggingface.co/bodhan-ai/indic-translate) | Model card identifies Indic Open Model License 1.0; do not infer weight rights from code license. Review model and access terms separately. The repository is gated. | Five safetensors shards total 15,882,486,068 bytes (~14.79 GiB), before runtime memory; unsuitable for the 8 GB Mac. | None; local model candidate | Evaluated and rejected for local hardware; not installed or tested. |
| Text-to-speech and voice conversion/cloning | No concrete model/repository configured | No model license can be assigned; interfaces and consent/reference metadata do not implement synthesis or cloning. | No model installed. | None configured | Not implemented / unavailable; no generated voice preview. |
| Self-hosted scene-generation model | Operator-configured; no model repository or weights selected by default | Registry defaults to “not declared” and commercial use disabled. The operator must verify the exact code, model and weight licenses, commercial use, and attribution before enabling. | External GPU worker required; exact hardware depends on the selected model. Weights must be installed manually; the backend never downloads them. | Optional private self-hosted worker, not a paid API | Contract and mock HTTP transport are tested; no real GPU worker/model inference was available or tested. |
| Development mock scene provider | In-repository text-only lifecycle simulator; no weights | No model weights; development adapter only. It emits labeled text metadata and cannot create media. | No GPU or model installation required. | None | Mock lifecycle tests pass; it is not real generation. |
| PySceneDetect content detection | Open-source scene-change detector, not a generative model | Not a model-weight integration. Review the dependency’s license separately for distribution. | Local CPU/video processing; dependency installed with backend requirements. | None | Real synthetic video cut-detection test passes. |

## Product and commercial-use notes

- There is no configured OpenAI, Anthropic, Replicate, Stability, or other paid
  AI provider in the application source. No paid AI API key is required.
- A model registry entry is operator metadata, not license verification.
  `commercial_use_permitted` defaults to false for an operator model.
- Do not market the converted Whisper weights as commercially cleared until
  their actual license and provenance have been verified.
- The candidate `mlx-community/whisper-tiny-fp16` repository declares
  Apache-2.0, unlike the existing `mlx-community/whisper-tiny` conversion.
  The candidate uses `mlx-audio-plus`, not the existing `mlx-whisper` adapter.
  The model card's `from mlx_audio.stt import transcribe` example does not
  match the published `mlx-audio-plus` 0.1.8 wheel. The isolated subprocess
  adapter uses the wheel's bundled Whisper `Model.from_pretrained` API with a
  validated local model directory.
- Compatibility was checked against the Mac's Python 3.13.9 / Apple Silicon
  environment. `mlx-audio-plus` 0.1.8 declares Python >=3.10 and MLX >=0.25.2;
  the installed MLX 0.32.4 satisfies that lower bound. A real inference test
  passed on this Mac with the isolated runtime and model; package installation,
  provider selection and actual inference are distinguished in
  `docs/MLX_TRANSCRIPTION_TEST.md`.
- The isolated worker's latest short synthetic-speech evaluation detected
  English, Hindi, and Telugu, but only returned usable text for English. Hindi
  and Telugu returned no segments; do not claim those languages are supported.
  The single English sample's WER/CER and per-run timing/RSS measurements are
  documented in `docs/TRANSCRIPTION_QUALITY_REPORT.md`; the samples are not a
  representative accuracy benchmark.
- The runtime can produce optional word timestamps when requested directly,
  but the experiment has no independently annotated timing reference and the
  application does not persist word-level timestamps. Treat this as
  experimental, not a verified product capability.
- The package metadata also depends on `mlx-audio[all]`, whose wheel overlaps
  the `mlx_audio` namespace and overwrites the Plus STT module. The isolated
  worker uses uv's `exclude-dependencies` setting for that upstream package.
  Its published dependency set remains broad, so it is kept out of the
  standard backend and Linux installations. The current isolated environment
  contains 66 distributions; it does not alter the backend environment.
- The optional translation worker declares PyTorch >=2.5, Transformers >=4.51,
  NumPy >=2.1, SentencePiece >=0.2, and IndicTransToolkit 1.1.1 in its own
  project. The isolated environment resolved PyTorch 2.15.0, Transformers
  4.57.6, NumPy 2.5.4, and SentencePiece 0.2.3; it did not alter the main
  backend or MLX worker. The two selected
  repositories each declare MIT in their model metadata and include a license
  file; repository code and model-weight terms still require separate review.
  Their `trust_remote_code` Python files are pinned to repository revisions
  and must be audited before model loading. Hugging Face's gated-access
  conditions were not accepted and no weights were downloaded.
- No real translation inference or quality measurements were run. The UI
  exposes candidate languages only; see
  [TRANSLATION_QUALITY_REPORT.md](./TRANSLATION_QUALITY_REPORT.md).
- The model repositories are still not downloaded. At the latest check, the
  worker CLI returned `Not logged in` and could not resolve a Hugging Face
  token; the user had reported a successful login earlier, but the worker's
  actual authentication state did not confirm it. No download was attempted.
- No voice cloning, verified translation language, diarization, generated speech, face tracking,
  or real scene video generation has been established by the available tests.
