# Translation worker and quality report

## Status

The local translation integration is implemented as an optional HTTP worker,
separate from the FastAPI environment and the MLX transcription worker. The
worker code, backend queue/persistence path, and UI controls have model-free
tests. After approval, the isolated worker environment was installed; no
model weights were downloaded. **No real translation inference has run; no
language is verified as supported and no translation-quality score is
available.**

The main backend advertises the six requested languages as candidates only.
Its `supported_languages` list remains empty until real inference and a
reviewed reference evaluation pass.

## Candidate model evaluation

| Candidate | Verified repository facts | Assessment |
|---|---|---|
| [AI4Bharat IndicTrans2 English→Indic Distilled 200M](https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M) | Repository metadata declares MIT and contains a `LICENSE`. Safetensors: 1,098,427,592 bytes (about 1.02 GiB). Snapshot revision: `2cfd0a20057756d756bf3e53528f492afc52f91a`. The repository is gated; Hugging Face requires accepting its access conditions, including sharing account information. | Selected English-to-Hindi/Telugu/Tamil/Kannada/Malayalam candidate. |
| [AI4Bharat IndicTrans2 Indic→English Distilled 200M](https://huggingface.co/ai4bharat/indictrans2-indic-en-dist-200M) | Repository metadata declares MIT and contains a `LICENSE`. Safetensors: 913,353,672 bytes (about 0.85 GiB). Snapshot revision: `d66a2122ad6d28184f3dc3797b652bd80ae3f65f`. The repository is gated under the same access conditions. | Selected Hindi/Telugu/Tamil/Kannada/Malayalam-to-English candidate. Both direction-specific checkpoints are needed for bidirectional English↔Indic use; only one is loaded at a time. |
| [Bodhan AI Indic-Translate](https://huggingface.co/bodhan-ai/indic-translate) | Model card describes a 7.94B-parameter model and an Indic Open Model License 1.0, distinct from the repository's code terms. Five safetensors shards total 15,882,486,068 bytes (about 14.79 GiB); repository is gated. | Rejected for the 8 GB Mac: weights alone exceed available unified memory. License and use conditions need separate legal review. |

IndicTrans2's two weight files total 2,011,781,264 bytes (about 1.87 GiB),
before tokenizer, dictionary, Python runtime, and inference memory. Its
model card's Transformers example uses `trust_remote_code=True`; this worker
therefore loads only local files, pins each repository revision, and must not
be exposed to untrusted model directories. Audit the pinned custom Python
files and license notices before installing or running the checkpoints.
The model-card recommendation favors GPU/FlashAttention for speed; the
worker uses one model at a time, MPS when available, float32, beam size 4,
and a 256-token generation cap. These are conservative unverified defaults,
not measured M2 performance claims.

The separate worker project declares FastAPI/Uvicorn, PyTorch >=2.5,
Transformers >=4.51, NumPy >=2.1, SentencePiece >=0.2, and
`IndicTransToolkit==1.1.1`. Its isolated `uv.lock` resolved PyTorch 2.15.0,
Transformers 4.57.6, NumPy 2.5.4, SentencePiece 0.2.3, FastAPI 0.162.5, and
Uvicorn 0.54.0 under Python 3.13.9; MPS is available. These packages were
installed only in `backend/translation_worker/.venv`. The main backend and
MLX worker dependencies were not modified.

## Languages and directions

| Direction | Architecture candidate | Real inference | Quality status |
|---|---|---|---|
| English → Hindi | IndicTrans2 En→Indic | Not run | Unverified |
| English → Telugu | IndicTrans2 En→Indic | Not run | Unverified |
| English → Tamil | IndicTrans2 En→Indic | Not run | Unverified |
| English → Kannada | IndicTrans2 En→Indic | Not run | Unverified |
| English → Malayalam | IndicTrans2 En→Indic | Not run | Unverified |
| Hindi → English | IndicTrans2 Indic→En | Not run | Unverified |
| Telugu → English | IndicTrans2 Indic→En | Not run | Unverified |
| Tamil → English | IndicTrans2 Indic→En | Not run | Unverified |
| Kannada → English | IndicTrans2 Indic→En | Not run | Unverified |
| Malayalam → English | IndicTrans2 Indic→En | Not run | Unverified |
| Indic → Indic | Not covered by these two distilled checkpoints | Not run | Rejected by the worker |

API tests exercise English↔Hindi and English↔Telugu using a fake provider.
These establish only queueing, persistence, ownership, approval, retry, and
cancellation behavior; they are not translation tests. Tamil, Kannada, and
Malayalam have not been inferred or quality-reviewed.

## Provisional reference dataset

`backend/translation_worker/tests/fixtures/reference_translations.json`
contains one short parallel example in each required smoke-test direction
(English→Hindi, English→Telugu, Hindi→English, Telugu→English). The examples
are project-authored provisional references; they have not been independently
reviewed by fluent speakers. A structural test checks their presence and
direction only. They are **not** accepted gold references and are not used to
calculate quality scores.

Before reporting translation quality, replace or validate this tiny set with
human-reviewed references, include names/terms and longer contextual
utterances, then run real inference on the pinned model snapshots. Report
sentence-level disagreements, omissions, mistranslated names/glossary terms,
and a suitable metric (for example chrF or BLEU) only after that comparison.

## Implemented behavior and limits

- Translation runs in a separate authenticated HTTP worker. The standard
  backend has no PyTorch, Transformers, or IndicTransToolkit dependency.
- The worker never downloads models. It accepts local snapshot paths only,
  checks the pinned repository revision and required local files, and reports
  configured directions from its health endpoint.
- Translation jobs preserve source segment text and timestamps, store
  provider/model/revision/license provenance, and persist each segment result
  independently. Failed segments can be retried without replacing successful
  translations. Cancellation updates pending segment status.
- Glossary terms are sent to the worker and protected before generation; the
  UI labels results as candidates that require creator review.
- Translation is segment-by-segment. The selected model is not instruction
  tuned for conversational context; adjacent-segment context is not currently
  passed to the model. Review pronouns, ellipsis, names, and cross-segment
  references manually.
- No trained-language support, translation accuracy, inference time, or
  memory use is claimed until real local inference is approved and measured.
- No voice synthesis or TTS integration is part of this work.

## Remaining gate before real inference

Approval was given to provision the isolated worker and download both pinned
checkpoints; the dependency installation is complete. At the latest check,
the worker execution environment could not resolve a Hugging Face token, so
no model download was attempted. The two snapshots total about 1.87 GiB of
safetensors weights, plus tokenizer/dictionary/code files. After authenticated
access is visible, download the pinned snapshots, inspect the custom model
Python files and license notices, and only then run inference and record
measured outputs.
