# 0007. Structured output through Chat Completions with strict JSON schemas, at minimal reasoning effort

- Status: accepted (the `MODEL_REASONING_EFFORT` setting awaits owner approval of the contracts.md change)
- Date: 2026-10-27
- Evidence: [docs/spikes/structured-output.md](../spikes/structured-output.md)

## Context

Every generative call in Marg.ai must return a Pydantic model (CLAUDE.md §10), with one repair
retry on a schema or semantic failure (s05 §4.1). The Meta Model API documents two surfaces for
structured output (Chat Completions `response_format`, Responses `text.format`) and a
reasoning-effort setting, but not their behaviour on Hindi and Hinglish input or their latency.
A WhatsApp reply has a few seconds to arrive, and the router has a 4 s timeout.

## Decision

S5 calls `muse-spark-1.3` through **Chat Completions** with
`response_format = {"type": "json_schema", "json_schema": {"name", "schema", "strict": true}}`,
schemas generated from Pydantic models (`extra="forbid"`, optional fields required and nullable),
validated with `model_validate_json`, and the single s05 repair turn on failure. MVP prompts run
at **`reasoning_effort: "minimal"`**, read from settings. In spike E this gave 199/199 valid,
script-preserving responses, 10/10 semantic repairs, and p95 of 3.2–4.5 s for the router, mentor
and parent-reflection schemas with 4 calls in flight.

## Alternatives considered

- **Default reasoning effort:** equally valid, but ~1,600 hidden reasoning tokens per call and
  6–15 s p50; the router would miss its 4 s timeout about half the time. Lost on latency and cost.
- **`low` effort:** valid, 3.6–9 s p50; no measured quality gain over `minimal` for these schemas.
- **Responses API (`text.format`):** not needed; Chat Completions met the bar, and it is the
  surface the OpenAI SDK's typed helpers and our fakes already model.
- **Unconstrained JSON + parsing:** rejected by CLAUDE.md §10 (never regex prose out of a reply).

## Consequences

- Easier: one adapter shape for every prompt; the repair path is cheap and reliable; Muse Spark
  Open (same Chat Completions surface, s10b §4.8) can reuse the adapter, once its own check passes.
- Harder: recursive schemas are rejected with `400` ("Recursive JSON schemas are not currently
  supported"), so no schema may reference itself.
- Revisit if: a prompt's eval scores improve materially at `low` or higher (raise effort for that
  prompt only); the teacher exposure bridge (5.6 s at `minimal`) is built and must meet 4 s;
  Meta changes the effort values or the strict-schema rules; or concurrency latency in the S16
  smoke test exceeds the step timeouts.
