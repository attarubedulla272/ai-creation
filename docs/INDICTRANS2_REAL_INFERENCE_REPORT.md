# IndicTrans2 real inference report

**Status: BLOCKED — authenticated Hugging Face account lacks gated repository access. No model weights downloaded and no real inference run.**

From `backend/translation_worker`, `uv run hf auth whoami` succeeded, and
`huggingface_hub.get_token()` returned a token without displaying it.
Authenticated access to the pinned repository was denied: the request
returned HTTP 403 with the message that the account is not on the authorized
list. Model download, code execution, and inference stopped. No language is
claimed to work.

## Model and license

- **Repository:** [ai4bharat/indictrans2-en-indic-dist-200M](https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M)
- **Pinned revision:** `2cfd0a20057756d756bf3e53528f492afc52f91a`
- **Direction:** English to Indic (Hindi, Telugu, Tamil, Kannada, Malayalam candidates)
- **License:** The exact revision's Hub metadata tags the repository `license:mit`. The `LICENSE` file fetched at that revision contains the MIT grant and AI4Bharat copyright notice. Preserve that notice. Repository license metadata does not substitute for reviewing every bundled file's provenance and terms.
- **Gated access:** Hub metadata reports `gated: auto`. Authentication succeeded, but the account is not on the repository's authorized list (HTTP 403).
- **Expected weights:** `model.safetensors` is 1,098,427,592 bytes (about 1.02 GiB), as previously verified from the repository file metadata. This weight file was not downloaded.
- **Disk check:** The data volume showed about 26 GiB available, sufficient for this checkpoint and supporting files at the time checked.
- **Custom code:** Fetching `config.json` at the pinned revision returned HTTP 403. The three custom Python files were not retrieved, reviewed, or executed. The worker uses `trust_remote_code=True`; do not load this model until those exact files are accessible and reviewed.
- **Download verification:** The authenticated metadata request verified the pinned repository and revision. The only cached IndicTrans2 file is its 1,128-byte `LICENSE` (about 1.1 KiB total); no config, tokenizer, custom code, dictionary, or weights were downloaded.

## Authentication

From `backend/translation_worker`, `uv run hf auth whoami` succeeded. The
account identity is omitted. A Python check confirmed `get_token()` returned
a token; the token was not printed. Authentication does not grant gated model
access. The authenticated file request returned:

```text
403 Forbidden: Access to model ai4bharat/indictrans2-en-indic-dist-200M is
restricted and this account is not in the authorized list.
```

No token was displayed, copied to source, or exposed in an API response. The
isolated worker environment is under `backend/translation_worker/.venv`; the
main backend and MLX transcription environments were not modified.

Request repository access for the account used by the worker. After access is
granted, recheck access from `backend/translation_worker` before downloading:

```bash
uv run hf auth whoami
```

Do not paste tokens into chat, source files, shell command arguments, or
project `.env` files. Do not retry model loading until access to the pinned
files is confirmed.

## Inference results

| Target | Input | Model output | Load / translation time | Peak memory | Result |
|---|---|---|---|---|---|
| Telugu | Not run | Not available | Not measured | Not measured | Blocked: gated access denied (403) |
| Hindi | Not run | Not available | Not measured | Not measured | Blocked: gated access denied (403) |
| Tamil | Not run | Not available | Not measured | Not measured | Blocked: gated access denied (403) |
| Kannada | Not run | Not available | Not measured | Not measured | Blocked: gated access denied (403) |
| Malayalam | Not run | Not available | Not measured | Not measured | Blocked: gated access denied (403) |

No example translations, quality scores, timing values, or memory
measurements are reported because no model inference occurred. No language
has been marked supported.

## API integration and verification

The existing application-level translation workflow has model-free coverage:
the backend fake-provider tests exercise queueing, per-segment persistence and
timestamps, manual editing, approval reset/review, ownership isolation,
failure/retry, and cancellation. The worker contract tests exercise its
authenticated API and no-download behavior. These tests do **not** establish
real model inference or a live main-backend-to-worker translation.

Previously run checks:

- Full backend suite: **70 passed**. Two already-declared Smart Clipper
  dependencies were missing from the base Python environment; they were
  provided temporarily for this test run and removed afterward.
- Backend Ruff check and formatting: passed.
- Frontend lint and production build: passed.
- Isolated worker import and OpenAPI generation: passed.
- The worker environment resolved PyTorch 2.15.0, Transformers 4.57.6,
  NumPy 2.5.4, SentencePiece 0.2.3, and IndicTransToolkit 1.1.1. PyTorch
  reported MPS available on the M2. This does not prove model compatibility
  or translation reliability.

## Next safe steps

1. Obtain gated-repository authorization for the worker's account and confirm
   access to the pinned files.
2. Download only the English→Indic checkpoint at the pinned revision into the
   worker's designated model cache; do not fetch the reverse checkpoint.
3. Inspect the exact pinned custom Python files and dependency behavior before
   enabling `trust_remote_code`.
4. Run serial inference tests for all five target languages, with no MLX or
   GPU video model loaded concurrently. Record real outputs and per-run
   load/inference times; measure peak memory only if the method is reliable.
5. Test the live worker API and authenticated application workflow, including
   persistence, review/approval, ownership, failure/retry, and cancellation.
6. Mark a target language supported only after its real output passes review.

No TTS work has been started.
