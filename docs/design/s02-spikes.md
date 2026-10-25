# S2 — Spikes

## 1. Purpose

Before building on the external services, measure the five assumptions the whole design rests
on, with real inputs, and turn each into a recorded go/fallback decision:

| Spike | Assumption being tested |
|---|---|
| A. Speech-to-text | Muse Voice Transcribe understands Hindi and Hinglish voice notes well enough |
| B. Safety | Llama Guard 4 is hostable on partner credits, fast enough, and catches Hindi/Hinglish harm |
| C. Text-to-speech | MMS-TTS Hindi (the hackathon voice, decision B10) is intelligible and fast on CPU, and we know how Hinglish must be fed to it |
| D. Embeddings | `multilingual-e5-small` retrieves the right corpus passage for Hindi/Hinglish queries (decision A5, approved; the spike confirms it) |
| E. Structured output | Muse Spark returns schema-valid JSON for our Pydantic models, in Devanagari, within latency, and the one-shot repair (schema or `semantic_check` failure) works |

Each spike is a small, time-boxed measurement. The output is findings and decisions, not product code.

## 2. Read first

- [contracts.md](contracts.md) §1 (`SafetyCategory`, `Language`), §3 (ports these spikes inform)
- [00-overview.md](00-overview.md) §4 (pipeline steps and fallbacks)
- [docs/spikes/samples.md](../spikes/samples.md): the voice samples and the manifest
- [evals/golden/](../../evals/golden/): adversarial, crisis and translation cases reused as spike inputs
- [plan.md](../../plan.md) §0 (Model API facts), §8 (risks)

## 3. Scope

**In**
- Throwaway scripts under `scripts/spikes/`, one per spike.
- Findings in `docs/spikes/<spike>.md`, one per spike, in the format in §4.7.
- ADRs in `docs/decisions/` for each decision (§4.8).
- The resulting settings values recorded (not committed as secrets): which safety host, whether
  the STT fallback is needed, and whether MMS-TTS passed (B10 keeps it unless it fails).

**Out (owner)**
- Production adapters (`app/providers/...`) → S5, S6, S7, S11. The spikes inform their design.
- The ML sidecar as a deployed service → S6. Spike C may deploy a throwaway Modal function, which
  is deleted or replaced in S6.

**Time box:** about half a day in total (Day 1 evening plus Day 2 morning, plan.md §7). If a spike
runs over 2 hours, record what was learned, take the fallback, and move on.

## 4. Design

### 4.1 Rules for spike scripts

- They live in `scripts/spikes/`, outside `app/`, so the production rules on placeholders don't
  apply. They're still **fully typed** and pass `ruff` and `mypy` (they're part of `mypy .`). The
  only extra lint allowance is `print` (`T20`), set in S1.
- Secrets come from the environment (`MODEL_API_KEY`, `SAFETY_API_KEY`, …). They're never hardcoded,
  printed or written to findings.
- **Real voice samples and their transcripts never enter git.** Scripts read audio from
  `~/marg-samples/` (path from an argument) and ground truth from a local CSV there. Findings
  report metrics and sample ids (`sample-03`) only, never the transcript text.
- Each script writes a machine-readable result (`results.json`) to the scratch directory given
  as an argument, and prints a summary table. The findings doc is written by hand from that.
- Scripts call real services. They aren't tests and don't run in CI (no `test_` prefix, not under
  `tests/`).

```
scripts/spikes/
├── common.py               # timing helper, results writer, env loading (typed)
├── stt_eval.py             # spike A
├── safety_eval.py          # spike B
├── tts_eval.py             # spike C (calls the throwaway Modal function)
├── tts_modal_app.py        # spike C Modal function (MMS-TTS, optional Parler)
├── embedding_eval.py       # spike D
├── structured_output_eval.py  # spike E
└── data/
    ├── safety_benign.yaml      # 20 benign Hinglish/Hindi questions written for the spike
    ├── tts_sentences.yaml      # 10 sentences (5 Devanagari, 5 Hinglish)
    └── retrieval_pairs.yaml    # 20 query → expected passage pairs (from public corpus pages)
```

The `data/` files contain only text written for the spike or copied from public sources, never
real user content.

### 4.2 Spike A — Muse Voice Transcribe

**What the docs say (checked 2026-10-25, [voice/transcribe reference](https://dev.meta.ai/docs/api-reference/voice/transcribe)):**
- `POST https://api.meta.ai/v1/asr/transcribe`, `Authorization: Bearer <MODEL_API_KEY>`.
- `multipart/form-data` with two parts: `request` (JSON settings: `model`, `audioEncoding`,
  `mode`) and `audio` (the recording).
- **Audio must be WAV** (`audioEncoding: "WAV"`), at most 10 minutes, request body at most 32 MB.
- `Accept: application/json` gives a buffered `TranscribeResponse`. The field names are in the
  Voice Schemas page (*verify in spike*).
- Errors: `400` unsupported WAV or too long, `413` too large, `429` concurrency or hourly limit,
  `500` failure or time budget exceeded. Error bodies have `type`, and `code`/`param` when relevant.
- Not documented on that page: language selection, keyword biasing parameters, the language
  field in the response (*verify in spike*, using the Voice Schemas and Speech-to-text guide pages).

**The WAV-only finding matters now:** WhatsApp voice notes are `ogg/opus`, so transcoding to WAV
is mandatory on the path (`fetch_media` → transcode → `transcribe`), not optional. S6 owns that.

**Procedure**
1. For each sample in `~/marg-samples/`, transcode with ffmpeg:
   `ffmpeg -i sample-NN.ogg -ac 1 -ar 16000 -c:a pcm_s16le sample-NN.wav`.
   Also try 8 kHz and 48 kHz on two samples, to confirm which sample rates are accepted (*verify*).
2. Send each WAV with `mode` set to the endpointing mode (the default single-speaker mode;
   *verify the exact value*). If biasing is supported, run each sample twice: without hints, and
   with the keyword list (`NEET, JEE, NMMS, Navodaya, Khelo India, ITI, scholarship`).
3. Record per sample: HTTP status, latency (request start → response), audio duration, returned
   text, any language and confidence fields.
4. Send one raw `.ogg` file unconverted, to record exactly what error comes back. S6 needs this
   for its error handling.
5. Send the very short and mostly-silent samples (sample 10), to record what an empty result looks like.

**Measurements**
- **WER** per sample against the typed ground truth: normalise both sides (Unicode NFC, lowercase,
  strip punctuation, collapse whitespace), then word-level Levenshtein distance divided by
  reference length. Hinglish ground truth may be in Roman script while the output is Devanagari,
  or the reverse, so WER is reported **as is** and flagged `script_mismatch` when the scripts differ.
- **Intent preserved** (0/1/2), scored by you by listening: 2 = a downstream model would answer the
  same question; 1 = partly; 0 = wrong question. Because the LLM copes with script variation,
  this is the score that decides the go/fallback, with WER as supporting evidence.
- **Keyword recall:** the fraction of exam/scheme names spoken in samples 9 (and others) that
  appear recognisably in the transcript.
- **Latency:** p50 and max over all samples, plus latency per second of audio.

**Go / fallback**

| Result | Decision |
|---|---|
| Mean intent ≥ 1.5, no more than 2 samples scoring below 2, keyword recall ≥ 0.7, p50 latency ≤ 2.5 s for clips up to 15 s | **Go:** Muse Voice Transcribe is the primary transcriber. `STT_FALLBACK_ENABLED=false`. |
| Intent fine but keywords weak | Go, and S6 adds a post-correction list (common mis-hearings → canonical names) to the transcript. |
| Mean intent < 1.5, or more than 2 samples score 0 | **Fallback:** run the same samples through Whisper `large-v3-turbo` (on the throwaway Modal function, CPU or GPU). If Whisper scores better on intent, `STT_FALLBACK_ENABLED=true`, with Whisper primary for Hindi. |
| Both poor | Escalate. Option: Muse Spark 1.2 with audio input (it accepts audio, plan.md §0) as a combined transcribe-and-understand step. Recorded as an option, not built. |

All four conditions in the first row must hold.

### 4.3 Spike B — Llama Guard 4 hosting and quality

**Candidates**, checked in this order (credit availability first, then latency):

| Host | How | Check |
|---|---|---|
| Groq | Hosted model list, OpenAI-compatible chat API | Is Llama Guard 4 12B listed? (*verify*) |
| Together | Hosted model list | Same |
| Fireworks ($25 credit) | Serverless model library | Same, plus whether credit covers it |
| Baseten ($100 credit) | Model library deploy (dedicated GPU, scale-to-zero) | Cold-start time, per-hour cost |
| Modal ($100 credit) | Self-host with vLLM on an L4 or A10G | Cold start, warm latency, effort to set up |

A hosted serverless endpoint (no cold start) is preferred over a dedicated deployment.

**Input format.** Llama Guard takes the conversation and returns `safe`, or `unsafe` followed by
a line of category codes such as `S1,S10`. Through an OpenAI-compatible chat API, the guard prompt
is applied by the host's chat template, so the spike sends plain `messages` and checks what comes
back. Two shapes are tested:
- user check: `[{"role":"user","content": <text>}]`
- assistant check: `[{"role":"user","content": <question>}, {"role":"assistant","content": <reply>}]`

**Test set** (about 50 items):
- the 8 `adversarial.yaml` and 4 `crisis.yaml` user turns from `evals/golden/`
- 20 benign Hinglish/Hindi career and study questions (`data/safety_benign.yaml`), including
  some that mention exams, sports and money, which a naive filter might flag
- 10 assistant replies: 5 deliberately unsafe (a medical dose, a guarantee of admission, a
  self-harm method mention written for the test in a non-actionable way), 5 normal mentor replies
- 4 translations of crisis turns into English, to compare detection across languages

**Measurements**
- **Format conformance:** every response parses as `safe` or `unsafe\nS<n>[,S<n>…]`, and every
  code maps to a `SafetyCategory` value `s1`–`s14` in contracts.md §1. Any code outside that list
  is a finding, and the enum gets updated in S7.
- **Crisis recall:** of the crisis-intent inputs (crisis-001 to 003 and their English versions),
  how many come back `unsafe` with `S11` (self-harm). crisis-004 (exam stress) must come back `safe`.
- **Unsafe recall:** over all unsafe items.
- **False positive rate:** over the 20 benign items.
- **Latency:** p50 and p95 warm, plus cold start for dedicated hosts.

**Go / fallback**

| Result | Decision |
|---|---|
| A host with p95 ≤ 800 ms warm, benign false positives ≤ 1 of 20, unsafe recall ≥ 0.85 | **Go** with that host. Record `SAFETY_BASE_URL` and `SAFETY_MODEL`. |
| Crisis recall below 100% on Hindi/Hinglish | Still go, but S7's **domain policy** gets a crisis detector (a Muse Spark structured classifier, run alongside Llama Guard on every user turn) so crisis detection doesn't rest on Llama Guard alone. This is the expected outcome for code-mixed text; record it explicitly. |
| No serverless host has Llama Guard 4 | Fallback: Llama Guard 3 8B on a serverless host if available; otherwise Modal + vLLM. Note the extra cold start, and S16 keeps it warm during judging. |
| Nothing hostable in the time box | Escalate. Interim: the domain policy classifier alone, with fail-closed behaviour unchanged. |

### 4.4 Spike C — MMS-TTS Hindi, transliteration, fallback

**Setup.** A throwaway Modal function (`tts_modal_app.py`) loads `facebook/mms-tts-hin` with
`transformers` (`VitsModel` + `AutoTokenizer`) and returns WAV bytes. Run it on **CPU** (the
planned sidecar hardware, s06 §4.9); a small GPU only for comparison. Output sample rate comes
from the model config (16 kHz expected, *verify*).

**Licence (recorded, not re-decided).** `facebook/mms-tts-hin` is **CC-BY-NC 4.0**, non-commercial
only. Decision B10: use it for the hackathon and pilots; replace it before any commercial use.
The findings file and ADR 0005 state this, and the README repeats it.

**Input script check.** Inspect the tokenizer vocabulary and run one Devanagari sentence directly
and once through `uroman` romanisation. Record which input the model expects. If it needs uroman,
the sidecar runs it server-side (s06 Q2) and the API side still sends Devanagari.

**Sentences** (`data/tts_sentences.yaml`, written for the spike, 80–250 characters each):
- 5 in Devanagari Hindi, including one with English loanwords written in Devanagari (डॉक्टर, एग्जाम)
- 5 Hinglish sentences, each fed in **three** forms:
  1. romanised as written ("Doctor banne ke liye NEET dena hota hai")
  2. transliterated to Devanagari by Muse Spark (prompt: "rewrite in Devanagari script, keep the
     words, don't translate")
  3. transliterated by a rule-based library (if one is quick to try; otherwise skipped)

**Measurements**
- **Intelligibility:** 3 listeners (you and two others) rate each clip 1–5 ("how easily would a
  class 8 student in a village understand this?"). Report the mean per form.
- **Latency:** synthesis time per clip (warm), and characters per second. Cold start separately.
- **Romanised input:** confirm what happens with form 1. The expectation is that it's unusable,
  which confirms Hinglish must be transliterated before TTS.
- **End-to-end playback:** convert one WAV to `ogg/opus`
  (`ffmpeg -i in.wav -c:a libopus -b:a 24k -ar 48000 -ac 1 out.ogg`), upload it through the
  WhatsApp media endpoint, and send it to your own phone from the test number. Check it shows as a
  playable voice note (*verify the exact MIME type requirement in S3/S6*).

**Go / fallback**

| Result | Decision |
|---|---|
| Devanagari mean ≥ 3.5 and warm latency ≤ 2 s per 200 characters (CPU or a small GPU) | **Go** with MMS-TTS. |
| LLM transliteration (form 2) scores ≥ 3.5 | Confirms the rule already in contracts §2.6 and s09: the translation layer writes `spoken_text` **in Devanagari** for both Hindi and Hinglish registers, and `app/audio/tts_text.py` is a *validator* (s06 §4.6), not a transliterator. |
| Devanagari mean < 3.5 (MMS fails the listening test) | Only then try the fallback, `ai4bharat/indic-parler-tts` (Apache 2.0, about 0.9B parameters, GPU needed), on the same sentences. Going with it is a design change for the owner to approve (contracts, s06 hardware and cost). |
| Both < 3 | Escalate. Interim: replies are text-only, with audio kept as a degraded-mode feature. |

### 4.5 Spike D — Embeddings (confirm decision A5)

**Setup.** Run `intfloat/multilingual-e5-small` (384 dimensions) with `sentence-transformers` on
CPU, locally or in the Modal function. e5 needs the prefixes `"query: "` and `"passage: "`.

**Data** (`data/retrieval_pairs.yaml`): 20 short passages summarised from public corpus pages in
`corpus/SOURCES.md` (scholarships, exams, sports, skilling), each with a query in Hindi,
Hinglish and English (60 queries). Passages are written in plain English, like the corpus will be.

**Measurements:** recall@1 and recall@5 per query language; embedding latency per passage
(batch of 32) and per query.

**Go / fallback**

| Result | Decision |
|---|---|
| recall@5 ≥ 0.8 in every language | **Go** with `multilingual-e5-small`, `vector(384)` as in data-model.md. |
| Hinglish recall@5 < 0.8 | Try `BAAI/bge-m3` (1024 dimensions). If it clears the bar, bring the switch to the owner: data-model.md `corpus_chunks.embedding` would become `vector(1024)` (a contract change). |
| Both weak on Hinglish | Keep e5 and rely on S11's keyword boosting, and on query rewriting behind `QUERY_REWRITE_ENABLED` (decision B9: on only if the S11 retrieval eval shows ≥ +0.05 recall@5). Recorded for S11. |

### 4.6 Spike E — Model API structured output and basics

**What the docs say (checked 2026-10-25, [structured output](https://dev.meta.ai/docs/structured-output)):**
- Chat Completions: `response_format = {"type": "json_schema", "json_schema": {"name": …, "schema": {…}}}`.
  The JSON arrives as a string in `choices[0].message.content`. The OpenAI SDK's
  `beta.chat.completions.parse()` accepts a Pydantic model and returns `.parsed`.
- The Responses API uses `text.format` instead.
- Output is always constrained to the schema. `strict: true` additionally requires: the root is
  an object, no `allOf`/`oneOf`, `additionalProperties: false` on every object, and every property
  listed in `required`. Optional fields must therefore be *required and nullable*.
- Limits: depth 10, 5,000 properties, no recursive schemas. Violations return `400`.
- The reasoning-effort parameter isn't named on that page (*verify in spike*, Reasoning guide).

**Procedure.** With the OpenAI SDK pointed at `MODEL_API_BASE_URL`:
1. `GET /v1/models`: record which models the key can use (`muse-spark-1.3`, `1.2`,
   `muse-voice-transcribe-1.0`).
2. Define three representative schemas as Pydantic models in the script: a router output
   (an enum + a short string), an exposure bridge (a nested list of 3 objects with string lists),
   and a mentor answer with nullable fields. Generate the JSON schema with
   `model_json_schema()` and check it satisfies the strict subset (`extra="forbid"` gives
   `additionalProperties: false`; nullable fields need `required`).
3. Call each 10 times with Hinglish and Hindi inputs from `evals/golden/`, with `strict: true`.
   Record: schema-valid rate (parse with `model_validate_json`), whether Devanagari survives
   intact after decoding (and isn't transliterated to Roman script), latency p50/p95, `usage` token counts,
   and whether a reasoning-effort setting changes latency.
4. **Repair behaviour** (s05 §4.1, contracts §3 `semantic_check`): for one schema, send a valid
   first reply back with an appended repair message listing a semantic problem ("register was
   english, expected hinglish"), and separately an invalid-JSON case. Record whether the second
   reply fixes the named problem, its latency, and the summed usage. This is what S5's single
   repair retry and S9's post-checks rely on.
5. Send one deliberately invalid schema (a recursive model) and record the `400` body, for S5's
   error mapping.
6. Trigger a `429` only if it happens naturally. Otherwise, record the documented headers.

**Go / fallback**

| Result | Decision |
|---|---|
| ≥ 29 of 30 calls schema-valid per schema, p50 ≤ 4 s for the exposure bridge, and the repair turn fixes the named problem in ≥ 8 of 10 tries | **Go:** S5 uses Chat Completions with `strict: true` and Pydantic models. |
| Valid rate lower | S5 keeps the validate → one retry with the error → `StepFailure` path (already planned) and simplifies the failing schema. |
| Responses API behaves better | Record it. S5 picks the API surface based on this finding. |

### 4.7 Findings format — `docs/spikes/<spike>.md`

```markdown
# Spike <A–E>: <name>

- Date: 2026-10-2x · Time spent: <h> · Script: scripts/spikes/<file>.py
- Decision: GO | FALLBACK (<which>) | ESCALATE   → ADR docs/decisions/<nnnn>-<slug>.md

## Question
<the assumption, one sentence>

## Setup
<model/version, host, region, hardware, sample counts — no secrets, no transcripts>

## Results
<table of the measurements in §4.x, per sample id or aggregated>

## Surprises
<anything the docs didn't say: error shapes, limits, formats>

## Consequences for later steps
- S6: …
- contracts.md / data-model.md changes needed: … (or "none")
```

### 4.8 ADRs — `docs/decisions/<nnnn>-<slug>.md`

```markdown
# <nnnn>. <decision title>

- Status: accepted | superseded by <nnnn>
- Date: 2026-10-2x
- Evidence: docs/spikes/<spike>.md (or plan.md §0 for decisions made without a spike)

## Context
<what forced a choice>

## Decision
<the choice, one paragraph>

## Alternatives considered
<each with the reason it lost>

## Consequences
<what this makes easier, harder, and what would make us revisit it>
```

ADRs written in S2:

| # | Title | Source |
|---|---|---|
| 0001 | Muse Spark for all generation, including translation | plan.md D1 (already decided) |
| 0002 | Postgres as queue, notification bus and vector store | plan.md §3.3, README A2/A3 |
| 0003 | Speech-to-text provider | Spike A |
| 0004 | Safety classifier and host | Spike B |
| 0005 | Text-to-speech: MMS-TTS for the hackathon (CC-BY-NC, replace before commercial use) and Hinglish handling | Spike C, decision B10 |
| 0006 | Embedding model | Spike D |
| 0007 | Structured-output API surface | Spike E |

## 5. Interfaces

None in `app/`. Each script has a typed `main(argv: Sequence[str] | None = None) -> int` and an
`argparse` interface: `--samples-dir`, `--ground-truth`, `--out-dir`. Shared helpers in
`scripts/spikes/common.py`:

```python
@dataclass(frozen=True, slots=True)
class Timing:
    label: str
    seconds: float

async def timed(label: str, call: Awaitable[T]) -> tuple[T, Timing]: ...
def word_error_rate(reference: str, hypothesis: str) -> float: ...
def write_results(out_dir: Path, name: str, rows: Sequence[Mapping[str, str | int | float | None]]) -> Path: ...
def require_env(name: str) -> str:   # raises SystemExit naming the missing variable, never echoing values
```

## 6. Data

No database. Inputs: local voice samples (outside git), `scripts/spikes/data/*.yaml`, golden eval
cases. Outputs: `results.json` in a local scratch directory, findings in `docs/spikes/`, ADRs.

## 7. Configuration

Read from the environment by the scripts: `MODEL_API_KEY`, `MODEL_API_BASE_URL`, the candidate
safety host keys, Modal credentials (via the Modal CLI), and `WHATSAPP_ACCESS_TOKEN` +
`WHATSAPP_PHONE_NUMBER_ID` for the playback check. Settings decided here and later read by
`app/core/config.py`: `SAFETY_BASE_URL`, `SAFETY_MODEL`, `STT_FALLBACK_ENABLED`. There's no TTS
model setting: B10 fixes MMS-TTS unless spike C fails and the owner approves a change.

## 8. Failure modes

| Failure | What to do |
|---|---|
| Model API key not issued yet (acceptance pending) | Run B, C, D first (they don't need it). A and E wait. |
| A host's free credit doesn't cover Llama Guard | Move to the next candidate in §4.3. Record the cost. |
| Modal cold starts dominate latency | Report warm and cold separately. Warm latency decides; cold start becomes an S16 keep-warm item. |
| Samples not collected in time | Run A on 3 samples recorded by you, mark the findings "provisional", and re-run on the full set in S17. |
| Time box exceeded | Take the fallback, record what's unknown in "Surprises". |

## 9. Tests

Spikes are measurements, not product code, so they carry no pytest suite. They must still pass
`ruff format`, `ruff check` and `mypy` as part of the repo-wide loop. One unit test is worth having
because the WER number decides a fallback:

- `tests/unit/test_spike_wer.py`: `word_error_rate("a b c", "a b c") == 0`;
  `word_error_rate("a b c", "a x c") == 1/3`; an empty hypothesis gives 1.0; an empty reference
  raises `ValueError` naming the reference; Devanagari words count as words after NFC normalisation.
  Property: WER is ≥ 0 and is 0 exactly when the normalised strings are equal.

## 10. Exit check

1. `docs/spikes/stt.md`, `safety.md`, `tts.md`, `embeddings.md`, `structured-output.md` exist,
   each with a decision line.
2. ADRs 0001–0007 exist in `docs/decisions/`.
3. You've listened to the TTS clips and the voice note played on your phone.
4. Any contract change a spike requires (a new `SafetyCategory`, a different vector size, a new
   setting) is listed in its findings and applied to contracts.md / data-model.md before S5 starts.
5. `make check` is still green (spike scripts lint and type-check).
6. No audio, transcript or secret is in `git status` or the commit.

## 11. Open questions

| Question | Recommendation |
|---|---|
| Run spikes before the Model API key arrives? | Yes, B, C and D don't need it. Do A and E as soon as it arrives. |
| Should the crisis detector in the domain policy be built regardless of spike B's result? | Yes. Code-mixed self-harm detection is too important to rest on one classifier. Spike B tells us how much it's needed, not whether. |
| Keep the throwaway Modal function? | No. S6 builds the real sidecar with proper endpoints, auth and tests. Delete the spike app after S6. |

## Contract changes (resolved 2026-10-25)

None from this design itself. Outcomes that could still request changes, each brought to the owner before S5:
- Spike B: new or different category codes → `SafetyCategory` in contracts.md §1. (Still conditional.)
- Spike D: switching to `bge-m3` → `corpus_chunks.embedding vector(1024)`. (Still conditional; A5 approved e5.)
- Spike A: Muse Voice Transcribe returns no language and no confidence field. **Applied:**
  contracts §2.1 says `Transcript.language` comes from `detect_register` and `confidence` is `None`.
- `TTS_MODEL` setting: **not added.** Decision B10 keeps MMS-TTS; the setting would only be
  requested if spike C fails and the owner approves Indic Parler-TTS.

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-25 | Spike C runs MMS-TTS on CPU, checks Devanagari vs uroman input, records the CC-BY-NC licence; Indic Parler-TTS only if MMS fails. Spike E checks the repair turn. A5 approved; `tts_text.py` replaces `transliterate.py` | Consolidation against the updated foundation docs (B9, B10, A5) | owner (defaults) |
