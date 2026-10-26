# Spike E: Model API structured output and basics

- Date: 2026-10-27 · Time spent: ~1.5 h (two runs) · Script: scripts/spikes/structured_output_eval.py
- Decision: **GO**: S5 uses Chat Completions with `response_format` `json_schema`, `strict: true`
  and Pydantic models, at `reasoning_effort: "minimal"` for the MVP prompts (a setting the owner
  approves before S5, see below) → ADR [docs/decisions/0007-structured-output-surface.md](../decisions/0007-structured-output-surface.md)

## Question

Does `muse-spark-1.3` on the Meta Model API return our strict JSON shapes reliably, fast enough
for a WhatsApp reply, in the user's script (Devanagari for Hindi, Roman for Hinglish), and does one
S5-style repair turn fix a named problem?

## Setup

- Model `muse-spark-1.3` (the product's `MODEL_TEXT`, never a `-contributor` variant) at
  `https://api.meta.ai/v1`, OpenAI SDK 3.38.0, Chat Completions, `strict: true`, temperature 0,
  no SDK retries, 60 s timeout.
- **Main run:** 4 schemas × 30 calls at the API's default reasoning effort, then 4 × 10 at
  `minimal` and 4 × 10 at `low` on the same inputs; 10 semantic repair tries, 3 invalid-JSON
  repair tries, 1 recursive schema. 225 calls, **4 in flight at a time**.
- **First run (same day, by Muse Code):** 3 schemas × 10 calls at default effort, **one at a
  time**. Used below only as the sequential latency reference; its repair test was invalid (see
  Surprises).
- Schemas: `router` (enum + reason), `exposure_bridge` (3 nested objects with string lists),
  `mentor_answer` (nullable fields), `parent_reflection` (s10b §4.8, with its `max_length` limits).
- Inputs: copied verbatim from `evals/golden/` (router 10, teacher exposure 7, student mentor 10,
  parent journey 5), cycled to 30. Hindi/Hinglish mix; the parent-journey set has one Hindi case.
- "Kept the script": for Hindi input, ≥ 60% of the reply's letters are Devanagari (exam names
  such as NEET are legitimately Roman); for Hinglish input, ≤ 5% are. Keys are excluded.
- **Why this model:** spike E verifies the exact model the product will run on. Marg.ai uses
  Meta's own models end to end (Muse Spark, Muse Voice Transcribe, Muse Image, SAM 3.1, Llama
  Guard 4, Muse Spark Open), which is also deliberate for the hackathon's "Use of Meta AI tooling"
  judging axis.

## Results

**Schema validity and script** (main run):

| Schema | Effort | Valid | Kept script | p50 | p95 | Mean reasoning tokens |
|---|---|---|---|---|---|---|
| router | default | 29/30 ¹ | 29/30 ¹ | 6.08 s | 9.89 s | |
| exposure_bridge | default | 30/30 | 30/30 | 15.00 s | 21.70 s | |
| mentor_answer | default | 30/30 | 30/30 | 10.69 s | 15.15 s | |
| parent_reflection | default | 30/30 | 30/30 | 11.13 s | 15.65 s | |
| router | minimal | 10/10 | 10/10 | 2.25 s | 3.18 s | |
| exposure_bridge | minimal | 10/10 | 10/10 | 5.62 s | 6.98 s | |
| mentor_answer | minimal | 10/10 | 10/10 | 2.93 s | 4.49 s | |
| parent_reflection | minimal | 10/10 | 10/10 | 3.69 s | 4.48 s | |
| router | low | 10/10 | 10/10 | 3.59 s | 4.38 s | |
| exposure_bridge | low | 10/10 | 10/10 | 9.09 s | 11.15 s | |
| mentor_answer | low | 10/10 | 10/10 | 6.94 s | 8.94 s | |
| parent_reflection | low | 10/10 | 10/10 | 6.65 s | 7.54 s | |

¹ The one miss was an `APIConnectionError` (no response), not a model output. **Every response
that arrived (199/199) was schema-valid and kept the user's script.**

Mean reasoning tokens per call, all schemas: default **1,575**, low **679**, minimal **223**
(mean completion tokens 1,803 / 901 / 432). The hidden reasoning is what makes default slow.

**Sequential reference (first run, default effort, one call at a time):** router p50 4.04 s,
exposure p50 7.48 s, mentor p50 5.01 s. The same schemas took about 1.5–2× longer with 4 calls in
flight, so concurrency itself adds latency on the provider side. The rate limits were nowhere
near: `x-ratelimit-limit-requests: 3000`, `x-ratelimit-limit-tokens: 4000000` (per minute), with
2,996 requests remaining during the run.

**Repair turn (s05 §4.1 wording):**

| Test | Result |
|---|---|
| Semantic: an English reply + "Errors: register: expected hinglish, got english. Reply again with only the corrected JSON object." under the real same-register system prompt | **fixed 10/10** (≥ 3 Hinglish markers, Roman script, schema-valid) |
| Invalid JSON (truncated object) + S5's repair message | **fixed 3/3** |

**Recursive schema:** `400`, `type: invalid_request_error`, `param: schema`, message
`"Recursive JSON schemas are not currently supported"`.

**Parent reflection quality (read by hand, `minimal`):** specific praise of what the child did
("Munni ne bahut achha joda ki parchhai ka ghoomna suraj se juda hai"), exactly one extending
question, a short learning tip; the Hindi case was answered fully in Devanagari; no labels, no
careers; the longest field in any reply was 138 characters, inside every `max_length`.

**Go bar (s02 §4.6):**

| Condition | Result |
|---|---|
| ≥ 29 of 30 schema-valid per schema | **met** (29/30 router because of a connection error; 30/30 others) |
| Repair fixes the named problem in ≥ 8 of 10 | **met** (10/10) |
| Exposure bridge p50 ≤ 4 s | **not met**: 5.62 s at `minimal` with 4 in flight (7.48 s at default, sequential). Exposure is the teacher stretch (mvp-scope, Day 8), not on the MVP path |

**Cost:** 47,568 input + 281,275 output tokens across the 200 schema calls and 10 repair calls
≈ **$1.25** at $1.25 / $4.25 per 1M (plan.md §0); the rest of the run adds a few cents.

## Surprises

- **Default reasoning effort is expensive in time and tokens** for these small outputs: ~1,600
  hidden reasoning tokens per call, 2.5–4× slower than `minimal`, with no gain in validity, script
  or (for the router) accuracy. `reasoning_effort` is accepted on Chat Completions with the SDK's
  values (`minimal`, `low` tested).
- **Concurrency adds latency** (≈ 1.5–2×), well below the documented rate limits.
- **A conflicting system prompt beats the repair message.** In the first run the repair kept an
  "English only" system prompt and the model refused the repair ("I understand you want Hinglish,
  but I must reply in English"), fixing 3/10. The repair message must not contradict the system
  prompt; in S5 it never does, since the repair reuses the same request.
- **Routing accuracy is a prompt problem, not a model one:** with a one-line route description it
  was 25/30 at default (teacher-exposure-002, a Hindi teacher question, went to `mentor` 4 times),
  10/10 at `minimal`, 9/10 at `low`. S5's real router prompt and the eval set decide this.
- Muse Spark Open (s10b §4.8, C9) was **not tested**: `OPEN_MODEL_BASE_URL` / `OPEN_MODEL_API_KEY`
  aren't configured yet. Re-run the script with them set; it then runs `parent_reflection` 10× on it.
- The Responses API wasn't tried: Chat Completions met the bar, so there was nothing to compare
  against.

## Consequences for later steps

- **S5:** Chat Completions + `json_schema` + `strict: true` + Pydantic (`extra="forbid"`,
  optional fields required-and-nullable); keep the single repair turn exactly as s05 §4.1 words
  it; map the recursive-schema `400` to `ProviderRejected` (a bug, not retryable); set
  `reasoning_effort` per call from config.
- **S5 timeouts:** at `minimal`, p95 is 3.2 s (router) to 4.5 s (reflection) with 4 in flight.
  `TIMEOUT_ROUTE_S` 4 fits the router at `minimal` (not at default). `TIMEOUT_GENERATE_S` 12 fits.
- **S4:** the worker's concurrency trades throughput for per-call latency; measure again in the
  S16 smoke test before raising it.
- **s10b:** `ParentReflection` with its length limits works as designed on Muse Spark 1.3.
  Muse Spark Open still needs this check once Baseten is set up.
- **Teacher exposure (Day 8 stretch):** the bridge is ~5.6 s at `minimal`; acceptable for a
  teacher planning tomorrow's class, but if the 4 s bar stands, split it into two calls or
  trim the schema then.
- **contracts.md changes needed (owner approval before S5):** add `MODEL_REASONING_EFFORT`
  (`Literal["minimal","low","medium","high"]`, default `minimal`) to §7 "Models and providers".
  CLAUDE.md §10 already puts reasoning effort in `app/core/config.py`; contracts doesn't list it yet.
