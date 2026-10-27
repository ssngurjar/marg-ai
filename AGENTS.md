# AGENTS.md — Marg.ai project rules for Muse Code

Muse Code reads this file as project rules when it runs in this directory.

> Canonical source: [CLAUDE.md](CLAUDE.md) carries these same rules for Claude Code.
> `muse init` reports that AGENTS.md takes precedence over CLAUDE.md, so this file
> mirrors it in full instead of merely referencing it. Keep the two in sync; section
> numbers match. If they ever disagree, follow CLAUDE.md and flag the drift to the owner.

Binding rules for Muse Code writing code in this repository. They override convenience,
speed, and brevity, including under hackathon time pressure. A feature shipped broken
costs more than a feature not shipped: the Indie track is judged on
"whether it works", live.

## Project

- Name: marg-ai — voice-first WhatsApp coach that helps rural parents nurture their
  3-8-year-old's curiosity.
- Build plan, architecture and schedule: [plan.md](plan.md).
- **Hackathon scope:** [docs/design/mvp-scope.md](docs/design/mvp-scope.md) decides what is
  built now and what waits for Phase 2, and lists the hard lines that are never cut.
  Build the full design by default. A lite version is allowed only as an exception listed
  there (reason + upgrade trigger); propose any new exception, with a time estimate, at the
  step's design review and let the owner decide. Don't build Phase 2 items without the
  owner's approval.
- Technical design: [docs/design/](docs/design/README.md). Before writing code for a step,
  read the three foundation docs (`00-overview.md`, `contracts.md`, `data-model.md`) and
  that step's design doc. Names come from `contracts.md` and `data-model.md` only.
- **Never change a design decision or make a new assumption on your own.** If a design doc's
  assumption turns out wrong (an API behaves differently, a model's quality is too low, a limit
  doesn't hold), or the work needs something no doc settles, stop and ask the owner. Show the
  evidence, give 2–3 options with their costs, and recommend one. After the owner decides, update
  the doc (including its "Decisions log") and the code in the same commit. The format is in
  `docs/design/README.md`, "How to use them" §3.
- Interpreter: always use `.venv/bin/python`. Never invoke a bare `python`/`python3`.
  Python **3.13**. Dependencies are managed with `uv`; the lockfile is committed.

## Common Commands

`make check` is the §2 verification loop.

- `make setup` — `uv sync`
- `make fmt` — `.venv/bin/ruff format .`
- `make lint` — `.venv/bin/ruff check .`
- `make type` — `.venv/bin/mypy .`
- `make test` — `.venv/bin/pytest` (unit + contract, hermetic)
- `make check` — fmt + lint + type + test, in order; each stage must exit 0 before the next
- `make test-db-up` / `make test-db-down` — Postgres for integration tests
  (`docker-compose.test.yml`)
- `make test-int` — alembic upgrade/downgrade/upgrade + check, then `pytest -m integration`
- `make migrate` — `alembic upgrade head` against the LOCAL database only (never a deployed
  database unless asked, §8)
- `marg eval` on the affected golden cases when a prompt or a layer changes; report the
  scorecard delta

## Project Layout

- `app/api/` — thin HTTP: verify, parse, enqueue, project. No domain logic.
- `app/pipeline/` — orchestrator + router. Depends on ports, never on concrete providers.
- `app/layers/` — Exposure, Translation, Mentor, Roadmap, Memory.
- `app/domain/` — pure models, state machine, activities, trajectory math, text rules. NO I/O;
  imports only core.errors / core.types.
- `app/providers/` — adapters behind ports in providers/ports.py. The ONLY place an SDK is imported.
- `app/channels/` — the ONLY place that knows a WhatsApp (or web) payload shape.
- `app/store/` — the ONLY place SQL lives.
- `app/core/` — config, clock, errors, types, logging (including the redaction processor).
- `app/prompts/` — `*.md.j2` prompt templates with versioned frontmatter.
- `app/safety/` — safety checks plus the fixed crisis replies (`crisis.py`).
- `services/ml_sidecar/` — heavy ML dependencies (`torch`, `transformers`,
  `sentence-transformers`) belong here only, never in the API image.
- `corpus/` — RAG corpus; every file carries `source_url` and `retrieved_on`.
- `evals/` — golden eval sets (never generated from real user conversations).
- `tests/` — `unit/`, `contract/`, `integration/` suites plus `fakes/` (unit tests never call
  a live model).
- `tests/fixtures/audio/` — only recordings made with explicit consent; do not add new ones
  without asking.
- `alembic/` — migrations; schema changes require one.
- `docs/design/` — technical design docs; `docs/spikes/` — Day-1 spike records.
- `scripts/spikes/` — spike scripts.

---

## 1. Hard negative constraints

Absolute. If a task appears to require one of them, stop and ask instead.

- **NEVER use `Any`.** No `typing.Any`, no bare `dict`/`list`/`tuple` annotations, no implicit
  `Any` from an unannotated parameter or return. If a type is genuinely open, model it with a
  `TypeVar`, `Protocol`, `TypedDict`, `Literal` union, or `object` plus an explicit narrowing
  check. `# type: ignore` is not an escape hatch: every ignore must be error-code-specific
  (`# type: ignore[arg-type]`) and carry a one-line comment justifying it.

  This matters more here than in most repos because **LLM output is untyped by nature**. Every
  model response, webhook payload and provider reply is validated into a Pydantic model at the
  boundary. `InboundMessage`, `Transcript`, `SafetyVerdict`, `ExposureBridge`, `LocalisedReply`,
  `Roadmap`, `AspirationSignals` and `TurnEvent` are models end to end, with no dict in between.

- **NEVER swallow exceptions silently.** No bare `except:`, no `except Exception: pass`, no
  `except Exception: return None`. Every `except` must either re-raise, raise a domain-specific
  error chained with `from exc`, or log at `warning`/`error` with the exception attached *and*
  return a value the caller can distinguish from success. Catch the narrowest exception type that
  can actually be raised.

  In the pipeline, a step that fails returns a typed `StepFailure`, which the orchestrator maps to a
  fixed user-facing fallback **and** records in telemetry. A student who gets no reply because a
  provider timed out and the error vanished is the worst failure this product can have.

- **NEVER leave TODOs, stubs, mocks, or placeholders in delivered code.** No `TODO`, `FIXME`,
  `XXX`, `pass  # implement later`, `raise NotImplementedError`, fabricated sample data, or
  hardcoded return values standing in for real logic. Code is either finished or not submitted.
  Mocks and fakes inside `tests/` are expected and exempt; production code under `app/` is not.
  A demo path that returns canned output instead of calling the real pipeline is a placeholder.

- **NEVER silence a checker to make it pass.** No blanket `# noqa`, no widening
  `per-file-ignores`, no relaxing `[tool.ruff]` / `[tool.mypy]` in `pyproject.toml`, no deleting
  or `skip`-ing a failing test. Fix the underlying defect. Changing strictness settings requires
  explicit human approval.

- **NEVER commit secrets or real user data.** `.env` stays untracked; `.env.example` lists every
  setting with no values. Never commit, log or print: the Model API key, WhatsApp access token, app
  secret, verify token, phone numbers, transcripts or audio from real users. Audio fixtures under
  `tests/fixtures/audio/` are only recordings made with explicit consent for that purpose. Do not
  add new ones without asking.

- **NEVER invent facts in the RAG corpus or in prompts.** Every file under `corpus/` carries a
  `source_url` and `retrieved_on` from an official or reputable public source. Exam dates,
  scholarship amounts, eligibility rules and helpline numbers are copied from the source, never
  recalled from memory. A career fact without a source does not ship.

## 2. Mandatory verification loop

Run this **in order, to completion, from the repo root** before returning any code. Reporting work
as done without a clean run of all four stages is a failed task.

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/mypy .
.venv/bin/pytest
```

- Each stage must exit **0** before the next one runs.
- On failure, fix the cause at source and **restart the loop from the top**. Formatting changes
  what lint and type checking see.
- Scoped runs are fine while iterating (`.venv/bin/ruff check app/pipeline/orchestrator.py`), but
  the final pass is all four stages over the whole repo.
- `pytest` by default runs `unit` and `contract` tests (hermetic). Integration tests need
  `docker compose -f docker-compose.test.yml up -d` and run with `pytest -m integration`; run them
  whenever `app/store/` or `alembic/` changed.
- Report the actual output. Never claim a stage passed if it did not, and never describe a stage
  you skipped as having run.

When a change touches a prompt or a layer, also run `marg eval` on the affected golden cases
and report the scorecard delta. A prompt change that lowers a rubric score needs a reason.

## 3. Mandatory property-based testing

Core logic carries `hypothesis` property tests in addition to example-based tests. In Marg.ai,
core logic means: **the conversation state machine, message splitting, spoken-text sanitising,
TTS text preparation, activity validation and selection, age bands, the chunker, trajectory
math, webhook signature verification, payload parsing, and the inbox/outbox idempotency logic.**

| Component | Property |
|---|---|
| `domain/conversation` | every reachable state has a path to `ACTIVE`; `CONSENT` cannot be bypassed from `NEW` by any event sequence; invalid transitions raise, never no-op |
| `domain/text` splitting | every part ≤ 4096 chars; `"".join(parts)` preserves all non-whitespace content in order; no part is empty; a word is never split mid-grapheme (Devanagari conjuncts, emoji) |
| `domain/text` spoken sanitising | output contains no URLs, markdown or bullet glyphs; idempotent: `s(s(x)) == s(x)` |
| `audio/tts_text` | Devanagari input keeps its letter sequence; output for the Hindi voice contains only Devanagari, digits, whitespace and sentence punctuation; every sentence ≤ the TTS limit; idempotent |
| `domain/activities` | selection never returns an activity outside the learner's age or inside the repeat window (when another exists); deterministic; every catalogue entry passes validation |
| `domain/stages` | age band is total over valid birth years; boundaries (2/3, 8/9, 11, 14, 18) are exact |
| `rag/chunker` | chunks cover the source text in order with bounded overlap; no chunk exceeds the token budget; deterministic |
| `domain/trajectory` | breadth is monotonic non-decreasing over a growing history; metrics are invariant to the order events arrive in when timestamps are equal |
| `channels/whatsapp/signature` | a valid signature verifies; any single-byte change to body or signature fails |
| `channels/whatsapp/payloads` | `parse(serialize(m)) == m` for generated messages; unknown message types are preserved raw, never dropped |
| `store/repositories/inbox` (integration) | inserting the same `wa_message_id` N times yields one row and one reply |

Requirements: encode invariants, not recomputed expected values; build inputs with
`hypothesis.strategies`, derived from the real domain types via `st.builds(Model, ...)`; include
Devanagari, romanised Hinglish, mixed scripts and emoji in text strategies; pin every falsifying
example Hypothesis finds as a permanent `@example(...)`; use `assume()` only to exclude genuinely
invalid input, never to hide a bug; keep them deterministic and hermetic (no network, no
database, no clock, no unseeded RNG). Mark them `@pytest.mark.unit`.

## 4. Mandatory negative and edge-case coverage

**No feature is complete if its tests are not there.** A suite that only proves the happy path is
incomplete and must not be handed back.

Required categories for every endpoint, step, layer and provider adapter you touch:

- **Wrong data type**: a string where a number is expected, an audio message with no `media_id`,
  an LLM returning prose where JSON was requested, a naive `datetime` where an aware one is required.
- **Missing data**: `None`, a webhook with no `messages`, a profile with no grade, a transcript with
  no detected language, a retrieval with zero chunks, a roadmap step with no `source_url`.
- **Empty but present**: `""`, `"   "`, a silent or 0-second voice note, a transcript of only
  filler ("umm"), `[]` search results, an LLM reply that validates but has empty fields.
- **Boundaries**: a text of exactly 4096 and 4097 characters; the 24-hour WhatsApp window at
  exactly-at and one-second-over; max 3 interactive buttons; retry count at the limit.
- **Malformed and hostile input**: invalid signatures, replayed webhooks, prompt injection in the
  user's message ("ignore previous instructions"), jailbreaks in Hinglish, emoji-only messages,
  extremely long voice notes, unsupported media types (video, sticker, location).
- **Out-of-domain values**: grade 0 or 13, an unknown language, a district that does not exist,
  a requested career the corpus has nothing on (must produce the honest "I don't know" path).
- **Provider failure**: timeout, 429 with and without `Retry-After`, 5xx, malformed response, and
  safety service unavailable (must fail closed). Each one is tested against a fake, with no live calls.
- **State and lifecycle**: a duplicate webhook (one reply), a worker crash between claim and
  complete (the turn is retried, not lost or doubled), a user who deletes their data mid-session,
  a consent revoked then re-granted.

What a negative test must assert:

- **The specific exception type and message**: `pytest.raises(SafetyUnavailable, match="llama_guard")`.
  Never `pytest.raises(Exception)`, which passes on a typo.
- **The exact HTTP status and body** for routes: `401` bad signature, `422` validation, `404`,
  `429` rate-limited demo. "Not 200" is not a test.
- **That nothing was sent on the failure path**: no outbox row, no WhatsApp call, no unclassified
  text reaching the user.
- **That the fallback the user receives is the intended one**, and that telemetry recorded the failure.
- **That invalid input is rejected, not silently repaired.** Do not coerce, truncate or default
  unless that is the documented behaviour.

Use `@pytest.mark.parametrize` for families of bad inputs. Name tests after the behaviour
(`test_silent_voice_note_asks_user_to_repeat`, not `test_audio_2`). Every bug fixed ships a
regression test reproducing the original input.

## 5. Escalation rule

**If `ruff check`, `mypy`, or `pytest` fails three times on the same issue, stop.**

No fourth attempt. Do not work around it by suppressing the rule, casting to `Any`, excluding the
file, or deleting the code. Return with:

1. The exact command and its verbatim output.
2. The three fixes attempted and why each failed.
3. Your diagnosis, and the options, including any that need a human decision (changing a public
   interface, adding a dependency, relaxing a rule for a documented reason).

The same applies to a test failing three times for reasons you do not understand, and to a
provider (Model API, WhatsApp, sidecar) behaving differently from its documentation three times.
Escalating is the correct outcome, not a failure.

## 6. Typing standards

- Every function, method and coroutine in `app/`, `services/` and `tests/` is fully annotated,
  including `-> None`.
- No implicit `Optional`. `x: str | None = None`, never `x: str = None`.
- `Sequence` / `Mapping` for read-only parameters; concrete `list` / `dict` for returns.
- `Literal` for closed string sets, `StrEnum` where the value is persisted or crosses the API
  (`Role`, `Mode`, `Language`, `ConversationState`, `SafetyCategory`, `StepName`).
- `Decimal` for money (cost accounting, `cost_inr` on roadmap steps). Never `float` for an amount.
- Timestamps are timezone-aware UTC. Get the current time from `app/core/clock.py`, never call
  `datetime.now()` directly in `domain/`, `layers/` or `pipeline/`.
- Public boundaries (API request/response, webhook payloads, LLM structured outputs, DB rows,
  telemetry events) are Pydantic models, `TypedDict` or dataclasses.
- Narrow at the edges: a provider adapter or channel validates untyped external input **once**,
  at the boundary, into a typed model the rest of the code can trust.
- `mypy` runs `strict = true` with `disallow_any_unimported = true`. An untyped third-party object
  (the OpenAI SDK response, an httpx JSON body) is wrapped in a typed adapter at the boundary, not
  passed inward.

## 7. Readability: write for the reviewer, not the compiler

Code here is read far more often than it is written, by reviewers who know **education and the
product**, not graph theory. A function that is correct but reads like a competitive-programming
answer has failed: it can't be reviewed, so its bugs can't be found.

The test: **a reviewer who knows the domain and not this file should be able to say what a
function does from its names alone**, without holding the algorithm in their head.

Concretely, do not:

- **Name things after the technique instead of the domain.** `res`, `tmp`, `acc`, `data`, `out`,
  `n`, `i`, `k`, `v`. The reader needs `localised_reply`, `retrieved_sources`, `pending_turns`,
  `fields_explored`.
- **Use an untyped nested container as a working structure.** Declare a frozen dataclass, even a
  private one used in a single function.
- **Write a comprehension that does more than one thing.** Split it, or use a loop.
- **Thread a mutable accumulator through recursion.** Return values and let the caller combine them.
- **Guard with `isinstance` and then `continue`.** Either the branch is impossible and should
  raise, or it is possible and needs handling.
- **Abbreviate.** `ctx`, `id`, `db`, `llm`, `stt`, `tts`, `rag` are established and fine.
  Inventing new ones is not.

Prefer, in order: a well-named local variable over a comment; a small named helper over a clever
expression; an explicit loop over a dense comprehension; a named type over a tuple or a nested
dict. Length is not the enemy, density is.

### Code organisation (adopted 2026-10-27)

A reader should know what a file does from its name, without following the router.

- **One main class per module, and the module is named after it:** `turn_processor.py` holds
  `TurnProcessor`. A module may also hold the small dataclasses that class takes or returns.
- **The class name says its role:** `*Repository` (SQL for one table or aggregate, in
  `store/repositories/`), `*Service` (application logic), `*Builder`, `*Parser`, `*Verifier`,
  `*Classifier`, `*Planner`, `*Dispatcher`, `*Processor`, `*Sender`, `*Layer`, `*Gate`.
- **Behaviour lives in classes.** A stateless rule is a class with `@staticmethod`s
  (`MessageSplitter.split`, `TurnBatcher.choose_batch`). Module-level functions are kept only for
  FastAPI route handlers and dependencies, CLI entry points, and bootstrap (config loading,
  logging setup, creating the database engine).
- **Data and rules are separate:** domain data models live in `app/domain/models/<topic>.py`,
  pure domain rules in `app/domain/rules/<rule>.py`, enums only in `app/domain/enums.py`.
- **Constants and reviewed copy** live in `app/constants/<topic>.py` (fixed replies, external
  API limits and codes). A rule class keeps its own tunables as `ClassVar`s.
- **`docs/code-map.md`** lists every module and class; regenerate it with
  `.venv/bin/python -m scripts.code_map` (a unit test fails while it's stale).

## 8. Dependencies and migrations

- New dependencies need explicit human approval. Note the pinned version and whether it belongs in
  `[project.dependencies]`, the `dev` group, or the sidecar's own requirements. Heavy ML
  dependencies (`torch`, `transformers`, `sentence-transformers`) belong in `services/ml_sidecar/`
  only, never in the API image.
- Schema changes require an alembic migration. Never edit a table without one.
- **Never run `alembic upgrade` / `downgrade` against the deployed database** unless asked.
  Migrations are tested against `docker-compose.test.yml`.
- Keep changes scoped to what was asked. No opportunistic refactors or config rewrites.

---

## 9. Layering, one direction only

```
app/api/        thin HTTP: verify, parse, enqueue, project. No domain logic.
app/pipeline/   orchestrator + router. Depends on ports, never on concrete providers.
app/layers/     Exposure, Translation, Mentor, Roadmap, Memory.
app/domain/     pure models, state machine, activities, trajectory math, text rules. NO I/O; imports only core.errors / core.types.
app/providers/  adapters behind ports in providers/ports.py. The ONLY place an SDK is imported.
app/channels/   the ONLY place that knows a WhatsApp (or web) payload shape.
app/store/      the ONLY place SQL lives.
app/constants/  reviewed copy (fixed and onboarding replies, crisis words) and external-API limits.
                Imports domain and core only; layers, pipeline and safety may read it.
```

- `domain/` importing anything from `app/` other than `core.errors` and `core.types` is a bug.
- `pipeline/` or `layers/` importing a concrete provider (`meta_model_api`, `llama_guard`) instead
  of a Protocol from `ports.py` is a bug. This is what keeps every unit test offline.
- Nothing outside `channels/` reads `entry[0].changes[0].value` or any other WhatsApp structure.
- Enforced by `tests/unit/test_layering.py` (import-graph check). Keep it passing; never add exceptions to it.

## 10. LLM and prompt rules

- **Model ids, reasoning effort, temperature, timeouts and cost caps live in `app/core/config.py`.**
  Never hardcode `"muse-spark-1.3"` in a layer.
- **Prompts live in `app/prompts/*.md.j2`**, never as inline strings in Python. Each carries a
  `version` in its frontmatter. Bump it on every change. The version is recorded on every turn.
- **Every generative call uses structured output** into a Pydantic model. Validation failure: one
  retry with the validation error appended, then a `StepFailure`. Never regex prose out of a reply.
- **User text is data, never instructions.** It goes into a delimited slot in the prompt, never
  concatenated into the system prompt. Prompt-injection cases live in the golden eval set.
- **No Contributor-mode models on user content.** Contributor variants let Meta train on the
  content, and our users are minors. They are allowed only for evals over synthetic cases.
- **Grounding:** the mentor and roadmap layers may only state facts present in retrieved chunks,
  and must cite them. If nothing was retrieved, the reply says it doesn't know. Search grounding
  is behind a flag with a per-turn cost cap.
- **Unit tests never call a live model.** Use `tests/fakes/`. Live calls belong in `marg eval` and
  in Day-1 spikes recorded under `docs/spikes/`.

## 11. Safety rules (non-negotiable)

- No generated output is used, stored or delivered before `safety-in` returns ALLOW (generation
  may run concurrently and is discarded otherwise), and nothing is sent without `safety-out`.
  **No code path reaches the outbox without a passing `safety-out` verdict.** Tests assert this
  for every route through the pipeline.
- **Fail closed.** If Llama Guard errors or times out, the Muse Spark backup check classifies
  instead (owner, 2026-10-27); if the backup fails too, send the fixed holding reply.
  Never send unclassified generated text.
- **Crisis replies are fixed text** in `app/safety/crisis.py`, reviewed by a human, with helpline
  numbers copied from their official source. An LLM never writes them.
- Users are mostly minors or speak for them: collect only role, grade, district and language;
  for a parent's child, only an optional nickname (≤ 20 chars) and a birth year. Never full
  names, school names or exact birth dates. Photos of what a child made are checked for people
  first (a person → reject and drop) and are never stored; only object counts are kept. Activities for young children come from the
  reviewed catalogue; personalisation may not add steps or materials, the `d7` hazard rule runs
  on every journey reply, and the supervision line is appended by code (s10b). **Direct child talk**
  (s10b §4.16) requires the parent's recorded consent; it never asks a child for personal details,
  never uses secrecy or attachment language (`d8`), always encourages telling a parent, ends at
  the session limits, uses child-worded crisis replies, and the parent summary never quotes a disclosure. Phone numbers are
  stored as salted hashes. Raw audio is deleted after transcription. Logs never contain phone
  numbers, transcripts or generated replies, only ids and hashes (enforced by the redaction
  processor in `app/core/logging.py`, which has its own tests).
- Consent (DPDP Act 2023) is a state in the conversation machine, not a flag that can be skipped.
  `delete my data` must purge every table that holds the user's hash.

## 12. Reliability rules

- **Every external call** has an explicit timeout, bounded retries with exponential backoff plus
  jitter, `Retry-After` honoured on 429, and raises a typed `ProviderError` subclass on exhaustion.
  Retry policy comes from `app/providers/http.py`, not from ad-hoc loops.
- **The webhook acknowledges in under one second.** It verifies, parses and inserts into the
  inbox, nothing else. All model calls happen in the worker.
- **Idempotency:** inbox is unique on `wa_message_id`; outbox is unique on `(turn_id, part_no)`.
  A redelivered webhook or a retried worker must never produce a second reply.
- **Degradation over failure:** each step has a documented fallback in `pipeline/fallbacks.py`
  (TTS down → text only; RAG empty → honest "don't know"). Adding a step means adding its fallback
  and its test.
- Long-running provider work never blocks the event loop. Use async clients, and run ffmpeg via
  `asyncio.create_subprocess_exec` with a timeout. Never `shell=True`.

## 13. Git and commits

- **Work directly on `main` for now.** There is one developer, so no feature branches until the
  owner says otherwise. Because `main` is the only line, it must stay green: never commit with the
  verification loop failing, and finish each build step (plan.md §11) in a working state before
  committing it.
- Small commits whose message says *why*, starting with the step id (`S3: verify webhook
  signatures before parsing`).
- Never force-push or rewrite `main`'s history. Never commit `.env`, audio from real users, or anything under `evals/`
  generated from real user conversations.

## 14. When you finish

State what you changed, the verification-loop result stage by stage (plus the eval delta if a
prompt or layer changed), and anything you deliberately left out. If the work moves a day's exit
criterion in [plan.md](plan.md) §7, say so.
