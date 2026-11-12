# IndicTrans2 sample test results

## Status: blocked before inference — gated access denied

The supplied corpus was saved to
`backend/translation_worker/tests/fixtures/indictrans2_sample_test_corpus.json`
and validated: six distinct source samples × five target languages = **30
cases**. No case was submitted to the model. `uv run hf auth whoami` succeeded
in the isolated worker, and `huggingface_hub.get_token()` returned a token.
The authenticated attempt to fetch the pinned repository's `config.json`
returned HTTP 403: the account is not on the repository's authorized list.
No model output, latency, or memory figure is fabricated. No token was
printed or exposed.

## Model, license, and resource checks

- **Repository:** `ai4bharat/indictrans2-en-indic-dist-200M`
- **Revision:** `2cfd0a20057756d756bf3e53528f492afc52f91a`
- **Model direction:** English→Indic only. The reverse-direction checkpoint
  was neither downloaded nor configured.
- **License:** Hub metadata for the pinned revision has a `license:mit` tag;
  its `LICENSE` file contains the MIT grant and AI4Bharat notice. Preserve
  that notice and inspect all code/data terms before commercial distribution.
- **Gated access:** Repository metadata reports `gated: auto`. Authentication
  works, but the account is not authorized for the gated files (HTTP 403).
- **Weight size:** The expected `model.safetensors` size is 1,098,427,592
  bytes (~1.02 GiB), based on previously verified pinned-repository file
  metadata. No weight file was downloaded.
- **Cache:** The IndicTrans2 cache contains only the 1,128-byte `LICENSE`
  file (about 1.1 KiB total). No config, custom code, tokenizer, dictionaries,
  or weights are cached.
- **Disk:** About 26 GiB was available. Disk capacity was not the blocker.
- **Device:** This is an Apple M2 with 8 GB unified memory. The isolated
  PyTorch environment had previously reported MPS as available. Device use
  and model memory are **not measured** because the model was not loaded.
- **Custom code:** The pinned `config.json` request was denied with HTTP 403.
  The three custom Python files were not retrieved or reviewed. The worker
  requires `trust_remote_code=True`; no custom code was executed.

## All 30 requested combinations

All cases have the same actual preflight outcome: **not run** because
authenticated access to the gated checkpoint was denied. The per-case
“authentication/checkpoint unavailable” labels refer to the unavailable
checkpoint; the verified blocker is repository authorization, not a missing
login. `—` means no model output or inference timing.

| # | Sample ID | Target | Input text | Actual model output | Time | Outcome |
|---:|---|---|---|---|---:|---|
| 1 | basic_greeting | Telugu (`tel_Telu`) | Good morning. How are you today? | — | — | Not run: authentication/checkpoint unavailable |
| 2 | appointment_time | Telugu (`tel_Telu`) | Your appointment is scheduled for Monday at 10:30 AM. | — | — | Not run: authentication/checkpoint unavailable |
| 3 | numeric_measurement | Telugu (`tel_Telu`) | The package contains 3 books and 2 notebooks, and it weighs 1.5 kilograms. | — | — | Not run: authentication/checkpoint unavailable |
| 4 | negation_and_condition | Telugu (`tel_Telu`) | Do not restart the computer until the update is complete. | — | — | Not run: authentication/checkpoint unavailable |
| 5 | proper_noun_and_acronym | Telugu (`tel_Telu`) | Ravi uploaded the PDF report to the AI Creator Studio project. | — | — | Not run: authentication/checkpoint unavailable |
| 6 | short_paragraph | Telugu (`tel_Telu`) | Please review the video before publishing it. Check the subtitles, audio levels, and spelling. If you find an error, save the project and tell the editor what needs to be fixed. | — | — | Not run: authentication/checkpoint unavailable |
| 7 | basic_greeting | Hindi (`hin_Deva`) | Good morning. How are you today? | — | — | Not run: authentication/checkpoint unavailable |
| 8 | appointment_time | Hindi (`hin_Deva`) | Your appointment is scheduled for Monday at 10:30 AM. | — | — | Not run: authentication/checkpoint unavailable |
| 9 | numeric_measurement | Hindi (`hin_Deva`) | The package contains 3 books and 2 notebooks, and it weighs 1.5 kilograms. | — | — | Not run: authentication/checkpoint unavailable |
| 10 | negation_and_condition | Hindi (`hin_Deva`) | Do not restart the computer until the update is complete. | — | — | Not run: authentication/checkpoint unavailable |
| 11 | proper_noun_and_acronym | Hindi (`hin_Deva`) | Ravi uploaded the PDF report to the AI Creator Studio project. | — | — | Not run: authentication/checkpoint unavailable |
| 12 | short_paragraph | Hindi (`hin_Deva`) | Please review the video before publishing it. Check the subtitles, audio levels, and spelling. If you find an error, save the project and tell the editor what needs to be fixed. | — | — | Not run: authentication/checkpoint unavailable |
| 13 | basic_greeting | Tamil (`tam_Taml`) | Good morning. How are you today? | — | — | Not run: authentication/checkpoint unavailable |
| 14 | appointment_time | Tamil (`tam_Taml`) | Your appointment is scheduled for Monday at 10:30 AM. | — | — | Not run: authentication/checkpoint unavailable |
| 15 | numeric_measurement | Tamil (`tam_Taml`) | The package contains 3 books and 2 notebooks, and it weighs 1.5 kilograms. | — | — | Not run: authentication/checkpoint unavailable |
| 16 | negation_and_condition | Tamil (`tam_Taml`) | Do not restart the computer until the update is complete. | — | — | Not run: authentication/checkpoint unavailable |
| 17 | proper_noun_and_acronym | Tamil (`tam_Taml`) | Ravi uploaded the PDF report to the AI Creator Studio project. | — | — | Not run: authentication/checkpoint unavailable |
| 18 | short_paragraph | Tamil (`tam_Taml`) | Please review the video before publishing it. Check the subtitles, audio levels, and spelling. If you find an error, save the project and tell the editor what needs to be fixed. | — | — | Not run: authentication/checkpoint unavailable |
| 19 | basic_greeting | Kannada (`kan_Knda`) | Good morning. How are you today? | — | — | Not run: authentication/checkpoint unavailable |
| 20 | appointment_time | Kannada (`kan_Knda`) | Your appointment is scheduled for Monday at 10:30 AM. | — | — | Not run: authentication/checkpoint unavailable |
| 21 | numeric_measurement | Kannada (`kan_Knda`) | The package contains 3 books and 2 notebooks, and it weighs 1.5 kilograms. | — | — | Not run: authentication/checkpoint unavailable |
| 22 | negation_and_condition | Kannada (`kan_Knda`) | Do not restart the computer until the update is complete. | — | — | Not run: authentication/checkpoint unavailable |
| 23 | proper_noun_and_acronym | Kannada (`kan_Knda`) | Ravi uploaded the PDF report to the AI Creator Studio project. | — | — | Not run: authentication/checkpoint unavailable |
| 24 | short_paragraph | Kannada (`kan_Knda`) | Please review the video before publishing it. Check the subtitles, audio levels, and spelling. If you find an error, save the project and tell the editor what needs to be fixed. | — | — | Not run: authentication/checkpoint unavailable |
| 25 | basic_greeting | Malayalam (`mal_Mlym`) | Good morning. How are you today? | — | — | Not run: authentication/checkpoint unavailable |
| 26 | appointment_time | Malayalam (`mal_Mlym`) | Your appointment is scheduled for Monday at 10:30 AM. | — | — | Not run: authentication/checkpoint unavailable |
| 27 | numeric_measurement | Malayalam (`mal_Mlym`) | The package contains 3 books and 2 notebooks, and it weighs 1.5 kilograms. | — | — | Not run: authentication/checkpoint unavailable |
| 28 | negation_and_condition | Malayalam (`mal_Mlym`) | Do not restart the computer until the update is complete. | — | — | Not run: authentication/checkpoint unavailable |
| 29 | proper_noun_and_acronym | Malayalam (`mal_Mlym`) | Ravi uploaded the PDF report to the AI Creator Studio project. | — | — | Not run: authentication/checkpoint unavailable |
| 30 | short_paragraph | Malayalam (`mal_Mlym`) | Please review the video before publishing it. Check the subtitles, audio levels, and spelling. If you find an error, save the project and tell the editor what needs to be fixed. | — | — | Not run: authentication/checkpoint unavailable |

## API persistence and approval

No genuine translations were submitted to the FastAPI application. Therefore
translation persistence across reloads, real-provider approval state, and
live worker-to-backend ownership checks are **not verified by this run**.
There was no result to approve, and nothing was automatically approved.

The prior backend suite tests this workflow with fake providers; those results
do not establish real model API integration. No worker process or model output
was substituted for the unavailable checkpoint. The main backend and MLX
transcription environments remain unchanged.

## Failure cause and next step

The immediate failure is gated repository authorization, not login:
`uv run hf auth whoami` succeeded and Python could retrieve the cached token,
but the pinned repository returned this actual error:

```text
403 Forbidden: Access to model ai4bharat/indictrans2-en-indic-dist-200M is
restricted and this account is not in the authorized list.
```

Request access to the gated repository for the account used by the worker.
After access is granted, confirm file access from the worker directory before
downloading:

```bash
uv run hf auth whoami
```

Do not send, print, or store the token in chat, source, or a repository `.env`.
Once gated access is granted, retrieve only the English-to-Indic checkpoint
at the pinned revision, review its custom code, then run inference and the
live persistence/reload/approval workflow. All five languages still require
fluent-speaker review before any support claim.
