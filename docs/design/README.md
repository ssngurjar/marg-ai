# Marg.ai — technical design docs

These docs hold the full technical design: **one doc per build step**, plus three foundation
docs every step depends on. Anyone picking up a step, whether Claude or a human, should get
everything they need from the foundation docs plus that step's doc, without having to rebuild
context from chat history.

[plan.md](../../plan.md) says *what* we build and *when*. [CLAUDE.md](../../CLAUDE.md) says *how
code must be written*. These docs say *how each part works*.

## How to use them

1. **Always read the three foundation docs first:**
   - [00-overview.md](00-overview.md): the system on one page: processes, the request lifecycle, layering, glossary.
   - [contracts.md](contracts.md): the shared vocabulary: enums, domain models, ports, errors, settings.
     **The single source of truth for names.** A step doc never invents a type that belongs here.
   - [data-model.md](data-model.md): every table, column, index and retention rule.
2. Then read the step doc for the step you're building (table below).
3. **If the code needs to differ from the doc, stop and ask the owner before changing anything.**
   Docs are full of assumptions (an API's behaviour, a model's quality, a limit), and some will turn
   out wrong. When one does, don't quietly pick a new approach. Present it like this:

   > **Assumption that failed:** what the doc assumed, and the evidence it's wrong (command
   > output, an API response, a measurement).
   > **Options:** A, B (C at most), each with its cost: time, dependencies, what changes elsewhere.
   > **Recommendation:** which one, and why.

   Only after the owner decides: update the doc and the code **in the same commit**, and record
   the decision in the doc's "Decisions log" section (date, what changed, why). A doc that
   disagrees with the code is a bug, and so is a design change nobody approved.
4. The same applies to **any new assumption** a session would need to make that a doc doesn't
   already settle: ask, don't assume.
5. Shared names (a new enum value, a column, a port method) change in `contracts.md` /
   `data-model.md` first, with approval. Step docs only reference them.

## Step → design doc

| Step | Doc | Builds |
|---|---|---|
| S1 | [s01-scaffold.md](s01-scaffold.md) | Repo tooling, config, errors, logging, health, layering test, CI, Docker |
| S2 | [s02-spikes.md](s02-spikes.md) | STT / safety / TTS spikes and their go/fallback criteria |
| S3 | [s03-whatsapp-ingress-auth.md](s03-whatsapp-ingress-auth.md) | Webhook, signature auth, payload parsing, user identity, sending |
| S4 | [s04-queue-worker.md](s04-queue-worker.md) | Inbox, turns, outbox, worker leases, per-user ordering, retries |
| S5 | [s05-llm-orchestrator.md](s05-llm-orchestrator.md) | Model API adapter, structured output, prompt registry, orchestrator, fallbacks |
| S6 | [s06-voice.md](s06-voice.md) | Media fetch, transcoding, STT, TTS sidecar, transliteration, audio replies |
| S7 | [s07-safety.md](s07-safety.md) | Safety gate in and out, domain policy, crisis path, fail-closed |
| S8 | [s08-onboarding.md](s08-onboarding.md) | Conversation state machine, consent, profile, delete-my-data |
| S9 | [s09-translation.md](s09-translation.md) | Translation layer: register, reading level, spoken text |
| S10 | [s10-exposure.md](s10-exposure.md) | Exposure layer (teacher mode) |
| S10b | [s10b-parent-journey.md](s10b-parent-journey.md) | Parent journey for ages 3–8: activity catalogue, daily khoj, serve-and-return, nudges |
| S11 | [s11-rag.md](s11-rag.md) | Corpus format, chunking, embeddings, pgvector, hybrid retrieval |
| S12 | [s12-mentor-roadmap-memory.md](s12-mentor-roadmap-memory.md) | Mentor answers, roadmaps, profile memory |
| S13 | [s13-telemetry.md](s13-telemetry.md) | Turn events, aspiration signals, trajectory metrics, dashboard, teacher links |
| S14 | [s14-web-channel.md](s14-web-channel.md) | Web channel, session auth, SSE progress, `/demo` |
| S15 | [s15-evals.md](s15-evals.md) | Eval harness, LLM judge, scorecards |
| S16 | [s16-hardening.md](s16-hardening.md) | Degradation audit, timeouts, load test, readiness |

S0 (prep), S17 (field test) and S18 (submission) aren't engineering work, so they have no design
docs. They're covered by plan.md and `docs/s0-setup.md`.

## Template every step doc follows

1. **Purpose:** what this step delivers and why, in a few lines.
2. **Read first:** the foundation sections and plan.md sections it relies on.
3. **Scope:** what's in, and what's explicitly out (and which step owns it).
4. **Design:** components, flows (sequence diagrams), algorithms, key decisions with their reasons.
5. **Interfaces:** module paths, class and function signatures, with types from `contracts.md`.
6. **Data:** tables read and written (columns are defined in `data-model.md`), and migrations added.
7. **Configuration:** settings used (names are defined in `contracts.md` §7).
8. **Failure modes:** every way it can fail, what the user sees, and what is recorded.
9. **Tests:** the concrete list: unit, property (with the invariant), negative, integration.
10. **Exit check:** the exact manual demonstration that proves the step is done.
11. **Open questions:** decisions still needed, each with a recommendation.
12. **Decisions log:** approved changes to this doc after v1: date, what changed, why, who approved.

## Status

All docs are **draft v1 (2026-10-25)**, consolidated against the foundation docs the same day. A step's doc is reviewed and approved at the start of
that step, in the "design first" part of the loop in plan.md §11, before any code is written.

## Design decisions (all approved by the owner, 2026-10-25)

| # | Decision | Where |
|---|---|---|
| A1 | Phone numbers are stored **encrypted** (AES-256-GCM) next to their hash, because replying needs the real number. Adds `cryptography`. | data-model.md §3 |
| A2 | The web channel is asynchronous like WhatsApp: `202` + one SSE stream per session, via Postgres `LISTEN/NOTIFY`, with no Redis. | s14, s04 |
| A3 | One turn at a time per user (a lease on the user row), with a 1 s debounce that combines a burst into one turn. | s04 |
| A4 | Teacher dashboard access is a short-lived signed link sent over WhatsApp, scoped to the teacher's district. No passwords. | s13 |
| A5 | Embeddings: `multilingual-e5-small` (384 dimensions), unless S2 shows a reason to change. | s11 |
| B1 | The safety core (`SafeReply`, the Llama Guard adapter, fail-closed) is built in S5, so S5's exit never sends unchecked text. S7 adds the domain policy, lexicon and crisis texts. | s05, s07 |
| B2 | Layers return `TurnWrite`s, applied atomically with the outbox in finalize. Signals and memory are post-turn tasks that never delay the reply. | contracts §2.3–2.4, s04 |
| B3 | A turn that ran to the end is `completed` even with a fallback; `failed` means crashed or abandoned. | contracts §2.3 |
| B4 | Delete-my-data purges the user after the confirmation is delivered, with a 10-minute sweep as the safety net. | s08, s04 |
| B5 | Crisis-turn text is never stored. | s07, data-model.md |
| B6 | Dependencies: add `cryptography`, `pgvector`, `pyyaml`; drop `tenacity`; no `regex`. | s01 |
| B7 | mypy `disallow_any_decorated` stays off (FastAPI); a staging deployment exists for load tests. | s01, s16 |
| B8 | Search grounding off; teachers get memory; `/status` public with cost and crisis counts admin-only; no nightly evals before the deadline; targets ≥ 85% overall, 100% crisis and adversarial. | s10, s12, s13, s15 |
| B9 | Trimmed for time: classroom codes, roadmap progress and check-ins, query rewriting (off unless the retrieval eval shows ≥ +0.05 recall@5). | s11, s12, s13 |
| B10 | MMS-TTS (CC-BY-NC) is used for the hackathon and replaced before any commercial use. | s06 |
| B11 | Layers write canonical replies in English, and a separate translation step localises them. | s09 |
| B12 | The parent journey (ages 3–8): a learner-centred data model, daily opt-in template nudges, nickname + birth year only, a curated activity catalogue with personalisation, designed to move to guarded full generation. | s10b, s08, data-model.md |
