# MLX Transcription Quality Report

## Summary

Real inference was run locally on the M2 Mac with the already-cached
`mlx-community/whisper-tiny-fp16` model through the isolated `mlx-audio-plus`
worker. No weights were downloaded and no audio was sent to an external
service.

The English sample produced usable segment-timestamped text with a measured
WER of 7.14%. Hindi and Telugu samples were language-detected, but returned no
segments; both therefore scored 100% WER/CER for these test utterances. These
results do not establish Hindi or Telugu transcription support.

## Test setup

- Hardware: Apple Silicon M2, 8 GB unified memory.
- Model: `mlx-community/whisper-tiny-fp16`, snapshot
  `c8c5417d20aca5049e6a6b07bede74a316618542`.
- Model license: Apache-2.0 as declared by its model repository. The isolated
  `mlx-audio-plus` 0.1.8 runtime is separately MIT-licensed.
- Runtime: the existing isolated worker environment, MLX 0.32.4, Python 3.13.9.
- Audio: short recordings synthesized on the Mac with the installed Samantha
  (English), Lekha (Hindi), and Geeta (Telugu) macOS voices. References are the
  exact text submitted to `say`; they are not human recordings or a
  representative benchmark.
- Language mode: automatic detection (no language argument passed).
- Metrics: WER uses Unicode letter/number runs as tokens; CER uses Unicode
  letters/numbers and excludes spaces and punctuation. Rates are normalized by
  reference length.
- Process RSS is the Python worker's maximum resident set size, not total
  unified-memory or Metal allocation.

## Real inference results

| Reference language | Duration | Detected | Inference | Worker total | Peak process RSS | WER | CER |
|---|---:|---|---:|---:|---:|---:|---:|
| English | 10.389 s | `en` | 0.586 s | 2.991 s | 274,448,384 B (261.8 MiB) | 7.14% | 1.41% |
| Hindi | 10.189 s | `hi` | 2.512 s | 3.478 s | 351,092,736 B (334.8 MiB) | 100% | 100% |
| Telugu | 12.583 s | `te` | 3.300 s | 4.389 s | 334,823,424 B (319.4 MiB) | 100% | 100% |

### English

Reference:

> This is a local English transcription quality test for AI Creator Studio.
> The quick brown fox jumps over the lazy dog. Please return an accurate
> transcript with timestamps.

Recognized segments:

| Start | End | Recognized text |
|---:|---:|---|
| 0.00 s | 5.28 s | This is a local English transcription quality test for AI Creator Studio, the QuickBround |
| 5.28 s | 10.28 s | Fox jumps over the lazy dog, please return an accurate transcript with timestamps. |

The output joined “the quick brown” into “the QuickBround”; punctuation and
capitalization differences are ignored by the reported metrics.

### Hindi

Reference:

> यह एआई क्रिएटर स्टूडियो के लिए स्थानीय हिंदी प्रतिलेखन परीक्षण है। यह वाक्य
> केवल परीक्षण के लिए बोला गया है। कृपया इसे सही समय-चिह्नों के साथ लिखें।

Detected language was `hi`, but the worker returned no segments and no
transcript text. A detected language code alone is not evidence that the
language is supported.

### Telugu

Reference:

> ఇది ఏఐ క్రియేటర్ స్టూడియో కోసం స్థానిక తెలుగు లిప్యంతరీకరణ నాణ్యత పరీక్ష.
> ఈ వాక్యం పరీక్ష కోసం మాత్రమే చెప్పబడింది. దయచేసి సమయ సూచికలతో ఖచ్చితమైన
> పాఠ్యాన్ని ఇవ్వండి.

Detected language was `te`, but the worker returned no segments and no
transcript text.

## Timestamp evaluation

The worker and backend return segment-level start/end timestamps. The English
run above returned two segments; no word-level alignment is included in the
persisted backend transcript.

An additional local English inference exercised the installed Whisper
implementation's optional `word_timestamps=True` mode. It returned word
entries with start/end times for 18 words across two segments. The transcript
contained recognition errors (“or level time stamps” instead of “word-level
timestamps”). The timings were structurally present, but were not compared
against independently annotated word boundaries. Treat this as an experimental
alignment capability only; word-level timing is not integrated into the API
and its accuracy is unverified.

## Audio handling and job behavior

- Worker normalization uses FFprobe and FFmpeg to produce mono, 16 kHz PCM
  chunks, with argument-array subprocess calls.
- WAV, MP3, M4A, and audio extracted from a video container passed the
  normalization tests using small synthetic media fixtures. These codec tests
  validate conversion, not transcription accuracy for each format.
- Long-audio logic uses 60-second core windows with 3-second overlap, assigns
  each segment to a core by its midpoint, shifts timestamps to source time,
  and removes duplicate text at chunk seams. Windowing and merging are covered
  by deterministic tests; long-duration real inference was not run.
- A model is loaded once per worker invocation and reused for that invocation's
  chunks. Separate jobs start separate worker processes and reload it.
- The worker streams per-chunk progress to the backend job. Cancellation,
  timeout, worker failure, and subprocess cleanup have automated coverage.
- A previous local 15-second video excerpt completed through the FastAPI
  transcription flow and persisted two timestamped segments. It had no known
  reference transcript and is not included in the accuracy scores above.

## Recommendations and limitations

- Keep `mlx-community/whisper-tiny-fp16` as an opt-in, local evaluation model;
  for this Mac, use sequential jobs, the current 60-second chunk / 3-second
  overlap settings, and avoid concurrently loading other large models.
- English performance on this one synthesized utterance is not evidence of
  general English accuracy. Evaluate representative human recordings before
  product claims.
- Hindi and Telugu currently fail to produce text in these tests. Do not list
  either as a supported transcription language based on language detection.
- The synthesized references are clean and artificial; background noise,
  accents, speakers, and real recording conditions are not represented.
- Peak RSS excludes or may not reflect all MLX/Metal unified-memory usage.
- Word-level alignment is experimental and not persisted by the API.
- Model licensing and runtime packaging details are tracked separately in
  [the model/license audit](./MODEL_LICENSE_AUDIT.md). No commercial-readiness
  or multilingual-accuracy claim is made.
