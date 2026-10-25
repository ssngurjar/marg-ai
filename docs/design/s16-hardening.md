# S16 — Hardening

> **Hackathon build level: Exception E4. Smoke test instead of the staging load test until the trigger fires (mvp-scope.md §4.7).** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

## 1. Purpose

By S16 every feature exists. This step makes sure the system behaves well when things go wrong,
with judges watching. It covers six things:

1. Audit every pipeline step's fallback.
2. Enforce per-step timeouts and the turn budget.
3. Complete the readiness probes.
4. Finish the retention and maintenance loop.
5. Enforce the cost cap.
6. Prove with a load test and chaos tests that no turn is lost or duplicated.

It ends with **feature freeze** (plan.md §7, Day 8) and a pre-demo checklist.

S16 adds no user-facing features. Every change here is a timeout, a probe, a limit, a test or a fix
for something those turn up.

## 2. Read first

- [00-overview.md](00-overview.md) §3–4 (life of a message, step table with fallbacks)
- [contracts.md](contracts.md) §4 (errors), §5 (retry policy), §6 (fixed replies), §7 (settings)
- [data-model.md](data-model.md) §4 (retention), `turn_steps`, `rate_limit_counters`
- [s04-queue-worker.md](s04-queue-worker.md) (leases, claiming, outbox retries)
- [s05-llm-orchestrator.md](s05-llm-orchestrator.md) (orchestrator, `StepFailure` mapping, step timeouts)
- [s07-safety.md](s07-safety.md) (fail closed), [s14-web-channel.md](s14-web-channel.md) (demo limits)
- [plan.md](../../plan.md) §5.1 (reliability), §8 (risks), §10 (definition of done)

## 3. Scope

**In**
- The degradation-ladder audit and a test per row (§4.1).
- Timeout values per step and turn-budget enforcement in the orchestrator (§4.2).
- Provider readiness probes and a queue-health probe (§4.3).
- The maintenance loop: completes S4's jobs (lease takeover, stuck sends, purge sweep, retention, pruning) (§4.4).
- The nudge loop's failure behaviour (s10b §4.11) in the audit and chaos tests.
- Daily cost-cap enforcement (§4.5).
- Load test tooling and the run report (§4.6).
- Chaos tests: hermetic ones in CI, and manual ones against staging (§4.7).
- The pre-demo checklist (§4.8).

**Out (owner)**
- How the orchestrator runs steps and builds `StepFailure` → S5. S16 only tightens timeouts and
  adds budget checks to it.
- Lease and outbox retry mechanics → S4. S16 verifies them under load and fault injection.
- `/status` page content → S13. S16 makes sure the latency and failure numbers it shows come from
  `turn_steps`.
- New features or prompt changes → frozen after S16. Bugs found in S17 are fixed, nothing else.

## 4. Design

### 4.1 Degradation-ladder audit

For every `StepName`, the audit confirms three things in code:
1. The failure path produces the fallback in 00-overview.md §4.
2. A `turn_steps` row records the failure with the right `outcome` and `failure_kind`.
3. A test proves it.

Any row that fails the audit is fixed in S16.

| `StepName` | Trigger tested | User receives | `turn_steps` outcome | Turn status |
|---|---|---|---|---|
| `fetch_media` | WhatsApp media `404`, timeout, oversized (> 2 MB after download) | `REPEAT_PLEASE` fixed reply | `failed` / `unavailable` or `timeout` or `unsupported_input` | `completed` (a reply was sent) |
| `transcribe` | timeout, `429` past retries, empty transcript, silence | `REPEAT_PLEASE` | `failed` / matching kind; empty → `empty_input` | `completed` |
| `safety_in` | classifier timeout or unavailable | `HOLDING` (fail closed) | `failed` / `unavailable` | `completed` |
| `safety_in` | verdict `CRISIS` | `CRISIS` fixed reply; the route result is discarded, `generate` and `translate` are skipped | `ok`; skipped steps get `skipped` rows | `completed` |
| `route` | invalid structured output twice | onboarding prompt if state ≠ `ACTIVE`, else `TRY_AGAIN_LATER` | `failed` / `invalid_response` | `completed` |
| `generate` | timeout, invalid output, `BudgetExceeded` | `TRY_AGAIN_LATER` | `failed` / matching kind | `completed` |
| `translate` | timeout or invalid output | canonical reply if already in the user's register, else `TRY_AGAIN_LATER` | `degraded` or `failed` | `completed` |
| `safety_out` | classifier unavailable | `HOLDING` | `failed` / `unavailable` | `completed` |
| `safety_out` | verdict `BLOCK` on generated text | `REFUSE`/`GENERIC` fixed reply (s07 §4.7); generated text and speculative audio never sent | `ok` (the check worked), `decision = block` | `completed` |
| `safety_out` | `d7` child hazard on a journey reply | the unmodified catalogue activity instead (s10b §4.10) | `ok`, `decision = block`, then the fallback | `completed` |
| `synthesize` | sidecar timeout or down | text-only reply | `degraded` / `unavailable` or `timeout` | `completed` |
| `enqueue_reply` / finalize | database error | nothing yet; inbox rows go back to `pending` with backoff | `failed` / `internal` | `failed` (decision B3) |
| `extract_signals` (post-turn) | timeout or invalid output | nothing (reply already committed) | `failed`, user unaffected | `completed` |
| `update_memory` (post-turn) | timeout, invalid output, privacy guard | nothing; memory unchanged | `failed` or `skipped` | `completed` |
| `NudgeLoop` (no inbound turn) | template rejected (`132xxx`), Graph API down | no nudge today; the parent can still ask | outbox part `failed` with `last_error`, log `error` `nudge_template_rejected` | the `NUDGE` turn stays `completed` |
| Purge after delivery | the post-delivery purge errors | the user already got `DATA_DELETED` | log `error`; the maintenance purge sweep deletes the user within `PURGE_SWEEP_AFTER_S` | — |

Two rules come out of this table and are enforced by tests:
- **Every turn that reaches `completed` has at least one outbox row.** No silent turns.
- **Generated text is never in the outbox unless a `safety_out` row with outcome `ok` and
  `turn_steps.decision = 'allow'` exists for that turn.** (CLAUDE.md §11. S7 implements it with the
  sealed `SafeReply`/`ReplyDelivery`; S16 adds the cross-check test that runs every fault scenario
  above and asserts it.)

### 4.2 Timeouts and the turn budget

Each step has a timeout setting `TIMEOUT_<STEP>_S`, with defaults in **one place**, contracts.md
§7. S16 measures the real latencies (from `turn_steps`, during the load test) and, with the
owner's approval, updates the defaults there. The starting values S16 audits against are the
contract defaults:

| Step | `TIMEOUT_<STEP>_S` | Basis |
|---|---|---|
| `FETCH_MEDIA` | 5 | WhatsApp media download for a voice note under 1 MB |
| `TRANSCRIBE` | 8 | includes ogg → wav transcode; spike A latency × 3 |
| `SAFETY_IN` | 3 | spike B p95 × 3 |
| `ROUTE` | 4 | small structured call |
| `GENERATE` | 12 | largest call (exposure bridge / mentor with retrieval) |
| `TRANSLATE` | 8 | |
| `SAFETY_OUT` | 3 | |
| `SYNTHESIZE` | 8 | spike C latency for about 600 characters |
| `EXTRACT_SIGNALS` | 6 | post-turn; not on the user's critical path |
| `UPDATE_MEMORY` | 6 | post-turn; not on the user's critical path |

`enqueue_reply` has no timeout setting: it hands the delivery to S4's finalize transaction.

**Turn budget (`TURN_BUDGET_S`, default 25 s).** The orchestrator tracks the turn's start time
(from the injected `Clock`) and, before each step, computes:

```
remaining      = TURN_BUDGET_S − elapsed
reserve        = DELIVERY_RESERVE_S (1.0, s05 §4.5)       # always keep room to send a fixed reply
step_deadline  = min(TIMEOUT_<STEP>_S, remaining − reserve)
```

- If `step_deadline` for `generate` or `translate` is under 2 s, the step isn't started. It
  becomes `StepFailure(kind=TIMEOUT, detail="turn budget exhausted before <step>")`, and the user
  gets `TRY_AGAIN_LATER`.
- If the deadline for `synthesize` is under 2 s, it's skipped (`skipped`) and the reply goes out
  as text only.
- `extract_signals` and `update_memory` aren't bound by the turn budget, since they're post-turn
  tasks run after finalize. They're still bound by their own timeouts.
- The retry policy (contracts.md §5) receives `step_deadline`. A retry or `Retry-After` wait that
  can't finish before the deadline isn't attempted.
- `LEASE_DURATION_S` (60) must be at least `2 × TURN_BUDGET_S` (contracts §7, s04 startup check).
  Post-turn tasks run after the lease is released, so they don't count. A lease expiring mid-turn
  would let a second worker start the same turn.

### 4.3 Readiness

S1 built `/readyz` with a probe list and one probe, `database`. S16 adds the rest. Every probe
has a 2 s timeout and reports `ProbeResult(name, ok, detail, critical)`. Results from external
providers are cached so `/readyz` doesn't hammer them.

| Probe | Check | Critical | Cache |
|---|---|---|---|
| `database` | `SELECT 1`, plus Alembic `version_num` equals the head revision bundled in the image | yes | none |
| `queue` | age of the oldest `pending` inbox row with `available_at <= now()` < 60 s | yes | none |
| `model_api` | `GET {MODEL_API_BASE_URL}/models` returns 200 | yes | 60 s |
| `safety` | one classify call on a fixed benign string returns `ALLOW` | yes (fail closed would make every reply a holding reply) | 60 s |
| `sidecar` | `GET {SIDECAR_BASE_URL}/health` returns 200 | no (TTS down means text-only, still useful) | 60 s |
| `whatsapp` | `GET {WHATSAPP_GRAPH_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}` returns 200 (token valid) | yes in `prod`, no elsewhere | 300 s |

The `queue` probe is the worker's liveness signal, so no heartbeat table is needed: if workers are
down, pending rows age, and the probe fails. The `/status` page (S13) shows the same probes.

Probe calls never log response bodies, and `detail` never includes URLs (which could carry
tokens) or keys.

### 4.4 Maintenance loop

Runs inside the worker (S4 created the loop and its lease, stuck-send and purge jobs; S16
completes the set) every `MAINTENANCE_INTERVAL_S` (30 s). Each job deletes or updates in batches of
1,000 rows, repeating until nothing is left, so no job holds long locks. Each run logs one line per
job with the row count (no content).

| Job | Owner | Action |
|---|---|---|
| Lease takeover | S4 §4.8 | expired leases → dead turns `failed`, inbox rows back to `pending` |
| Stuck sends | S4 §4.10 | `sending` rows older than `OUTBOX_SENDING_STUCK_S` (by `sending_since`) → `pending` |
| Purge sweep | S8, S4 | users with `purge_after_turn_id` set and that turn completed more than `PURGE_SWEEP_AFTER_S` ago → deleted (cascade) |
| Retention | S16 | the SQL below |

```sql
-- 1. Expired media (inbound audio once transcribed is deleted by S6 directly; this catches leftovers)
DELETE FROM media_blobs
WHERE id IN (SELECT id FROM media_blobs WHERE expires_at < now() LIMIT 1000);

-- 2. Raw webhook payloads past retention
UPDATE inbox_messages SET raw_payload = NULL
WHERE id IN (SELECT id FROM inbox_messages
             WHERE raw_payload IS NOT NULL
               AND received_at < now() - make_interval(days => :raw_payload_days)
             LIMIT 1000);

-- 3. Turn text past retention
UPDATE turns SET user_text = NULL, reply_text = NULL
WHERE id IN (SELECT id FROM turns
             WHERE (user_text IS NOT NULL OR reply_text IS NOT NULL)
               AND started_at < now() - make_interval(days => :turn_text_days)
             LIMIT 1000);

-- 4. Old rate-limit windows
DELETE FROM rate_limit_counters WHERE window_start < now() - interval '2 days';
```

Expired leases and inbox rows stuck in `processing` (a worker died after claiming) are recovered
by S4's lease-takeover job, never directly by the claim query (s04 §4.8). S16's chaos tests (§4.7)
prove that.

### 4.5 Cost cap

`DAILY_COST_CAP_USD` (default 5) limits spend that strangers can drive: **web demo turns** and
**search grounding** (contracts.md §7). WhatsApp turns from real users aren't capped by it, so a
judge on WhatsApp never hits a cap set for the public demo.

```python
class SpendGuard:
    """Reads today's spend from turn_steps and refuses work past the cap."""
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], clock: Clock,
                 cap_usd: Decimal) -> None: ...
    async def check(self, purpose: Literal["demo_turn", "search_grounding"]) -> None:
        """Raises BudgetExceeded(purpose, spent, cap) when today's spend >= cap."""
```

- "Today" is the **IST** calendar day (decision B8). Spend comes from s13's cost-today query
  filtered to `channel = 'web'` (the same function s14 uses), so the day boundary is defined once.
  Search grounding is off for the MVP (B8), so the `search_grounding` purpose is wired but unused.
  The sum is cached for 30 s, so the guard doesn't query on every call. It may overshoot by up to
  30 s of spend, which is acceptable at this scale.
- The guard is checked before `generate` on web turns and before any grounded call.
- `BudgetExceeded` maps to `FailureKind.BUDGET_EXCEEDED` → `TRY_AGAIN_LATER`. On the web demo,
  the SSE stream also says the demo has reached today's limit.
- At 80% of the cap, one `warning` log line per day (`cost_cap_80_percent`) so you notice before
  the demo stops.

### 4.6 Load test

**Goal:** show that under realistic concurrency, no turn is lost or duplicated, and record real
p50/p95 latency per step.

**Tooling:** `scripts/load/` (typed, linted, not under `tests/`):

```
scripts/load/
├── run.py              # entrypoint: --target, --users, --turns-per-user, --duplicate-rate, --out
├── web_driver.py       # simulated web users: cookie session → POST /demo/messages → SSE until reply
├── whatsapp_driver.py  # signed fake webhooks → POST /webhooks/whatsapp
├── payloads.py         # builds Cloud API-shaped payloads (text and audio) for synthetic numbers
└── report.py           # queries turn_steps / inbox / outbox after the run and writes the report
```

**Where it runs:** a **staging** deployment of the same image, with its own Neon branch, never the
production database or the real WhatsApp number. Staging differs in two ways:
- `WHATSAPP_APP_SECRET` is a staging-only secret the driver signs with.
- Outbound WhatsApp sending goes to a **sink sender**: a `ChannelSender` that records the part and
  returns a synthetic `provider_message_id` instead of calling the Graph API, because the
  synthetic numbers don't exist. Selected by `CHANNEL_SINK_ENABLED` (contracts §7). It's refused
  at startup when `ENVIRONMENT=prod`. Staging is approved (decision B7).

Model, safety, STT and TTS calls are **real**, because measuring their latency under load is the point.

**Scenario** (defaults):
- 20 concurrent users: 10 web, 10 WhatsApp. 5 turns each, 100 turns in total.
- Mix: 60% text, 40% audio. Audio clips are synthetic, generated by the TTS sidecar from the
  `evals/golden/` inputs, never real recordings.
- Think time between a user's turns: 3–10 s, random with a fixed seed.
- `--duplicate-rate 0.1`: 10% of WhatsApp webhooks are sent twice, 0–2 s apart, the way Meta
  redelivers.
- Burst case: 3 users send 3 messages within 1 s, to exercise per-user combining (S4).
- Search grounding off. The demo cost cap is raised for the run (and the cost recorded in the report).

**Pass criteria** (computed by `report.py` from the database, not from client timings alone):

| Metric | Target |
|---|---|
| Inbound messages with no turn (`inbox_messages` never reaching `done`) | **0** |
| Turns with more than one reply set (duplicate `part_no` sequences, or more than one turn per message) | **0** |
| Duplicate webhooks producing an extra turn | **0** |
| Turns `completed` without any outbox row | **0** |
| Turn latency (first inbox `received_at` → first outbox `sent_at`), text | p50 ≤ 6 s, p95 ≤ 12 s |
| Same, audio | p50 ≤ 8 s, p95 ≤ 15 s (plan.md §4.2) |
| Fallback replies, excluding injected faults | ≤ 2% of turns |
| Per-step p50/p95 | reported, not gated; used to set §4.2 timeouts |

The report (`docs/load/2026-11-02-load-test.md`) records the scenario, the commit hash, the results
table, the per-step latencies, the run's cost, and any defects found and fixed.

### 4.7 Chaos tests

**Hermetic (in the test suite, run in CI).** These use fakes and the integration Postgres, with
no real providers.

| Test | Setup | Assertion |
|---|---|---|
| `test_worker_killed_mid_generate_turn_retried_once` | A fake LLM that blocks; a worker task is cancelled mid-`generate` without releasing its lease; the clock advances past `LEASE_DURATION_S`; the maintenance takeover job runs | A second worker completes the turn; exactly one set of outbox rows; inbox rows `done`; the first worker's late finalize (if it resumes) raises `LeaseLost` and writes nothing |
| `test_provider_429_then_success_within_budget` | respx: Model API returns 429 with `Retry-After: 1`, then 200 | Step `ok`, one retry recorded, reply generated |
| `test_provider_429_retry_after_beyond_budget` | `Retry-After: 30` | No wait attempted; `StepFailure(RATE_LIMITED)`; `TRY_AGAIN_LATER` |
| `test_provider_5xx_exhausts_retries` | 3 × 503 | `StepFailure(UNAVAILABLE)`, exactly 3 attempts |
| `test_safety_down_holds_every_reply` | safety fake raises `SafetyUnavailable` | Every turn's outbox contains only `HOLDING` text; no generated text anywhere in `outbox_messages` |
| `test_sidecar_down_sends_text_only` | synthesizer fake raises `ProviderUnavailable` | Outbox has a text part, no audio part; `synthesize` outcome `degraded` |
| `test_database_unavailable_webhook_returns_503` | session factory raises on insert | Webhook returns `503` (s03 §8; not `200`), so Meta redelivers; nothing logged with payload content |
| `test_outbox_send_failure_retried_then_failed` | channel sender fake fails 3 times | Outbox row `failed` with `last_error`; turn stays `completed`; no regeneration |
| `test_duplicate_webhook_during_processing` | same `external_id` posted while its turn is running | One inbox row, one turn, one reply |
| `test_budget_exhausted_mid_turn` | clock fake jumps past the budget after `route` | `generate` not started; `TRY_AGAIN_LATER`; `turn_steps` shows the reason |
| `test_nudge_template_rejected_logs_and_reschedules` | sender fake raises `ProviderRejected` (template not approved) for a `TEMPLATE` part | outbox part `failed` with `last_error`; `nudge_subscriptions.next_due_at` is tomorrow; no retry flood |
| `test_nudge_loop_two_workers_one_template` | two `NudgeLoop`s against one due subscription | exactly one `NUDGE` turn and one `TEMPLATE` part |
| `test_purge_sweep_deletes_after_failed_post_delivery_purge` | the post-delivery purge raises; clock advances past `PURGE_SWEEP_AFTER_S` | the sweep deletes the user and every dependent row |

**Manual, against staging (recorded in the load-test report):**
1. Kill the worker container (`docker kill` / platform restart) during the load test. Pass when
   the load-test criteria still hold.
2. Revoke the sidecar token for 2 minutes. Replies go text-only, and `/readyz` stays `200` with
   `sidecar` failing as non-critical.
3. Point `SAFETY_BASE_URL` at an unreachable host. `/readyz` returns `503`; WhatsApp replies are
   holding replies only.
4. Restart Postgres (Neon branch suspend/resume). The api returns `503` on `/readyz`, webhooks
   during the outage get `503` (Meta retries), and nothing is lost after recovery.

### 4.8 Pre-demo checklist — `docs/submission/pre-demo-checklist.md`

Run the day before submission and again before the closing-ceremony finals. Every item is a yes/no.

**Accounts and access**
- [ ] Permanent system-user WhatsApp token in production settings; temporary token removed.
- [ ] Display name approved for the real number (or the fallback plan in plan.md §4.1 is ready).
- [ ] Webhook subscribed to `messages`; a test message from your phone gets a reply.
- [ ] Model API spend limit and the partner credits checked: enough for the judging window.

**Service health**
- [ ] `/readyz` is `200` with every probe passing.
- [ ] `/status` shows the last 24 h: success rate ≥ 98%, p95 within §4.6 targets.
- [ ] Sidecar and safety host kept warm through judging (Nov 4–9): Modal `min_containers=1` on the
      sidecar's CPU class (s06 §4.9) or equivalent, cost noted.
- [ ] Nudge template (`NUDGE_TEMPLATE_NAME`) approved in WhatsApp Manager in all three languages;
      a test parent received one and its button opened today's khoj.
- [ ] Activity catalogue loaded at startup with **30 enabled** activities (startup log line), each reviewed.
- [ ] Load-test report committed, and no open defects from it.

**Safety and data**
- [ ] Every `adversarial.yaml` and `crisis.yaml` eval case passes on the deployed build.
- [ ] Crisis helpline text checked against the official source pages again (numbers unchanged).
- [ ] Test users deleted with delete-my-data; their rows are gone.
- [ ] Logs from the last day searched for 10-digit numbers: none found.

**Demo paths**
- [ ] `/demo` works from a phone on mobile data and from a laptop, in a private window.
- [ ] Demo rate limit and `DAILY_COST_CAP_USD` set for the judging window.
- [ ] `wa.me` link and QR code in the submission open the right number.
- [ ] Fallback video recorded, in case live WhatsApp fails during the finals.
- [ ] Latest eval scorecard in the README matches the deployed commit.

**Recovery**
- [ ] Neon branch snapshot taken before submission.
- [ ] Deploy rollback command written down and tried once on staging.

## 5. Interfaces

| Module | Public names |
|---|---|
| `app/pipeline/budget.py` | `TurnBudget(started_at: datetime, budget_s: float, reserve_s: float, clock: Clock)` with `deadline_for(step: StepName, step_timeout_s: float) -> float \| None` (returns `None` when the step mustn't start) |
| `app/telemetry/spend.py` | `SpendGuard` (§4.5) |
| `app/api/health.py` | new probe factories: `database_probe`, `queue_probe`, `model_api_probe`, `safety_probe`, `sidecar_probe`, `whatsapp_probe`, each `-> ReadinessProbe`, plus `CachedProbe(probe, ttl_s, clock)` |
| `app/worker/maintenance.py` | maintenance jobs registered as `MaintenanceJob(name: str, run: Callable[[AsyncSession], Awaitable[int]])`; each returns the row count it changed |
| `app/channels/sink.py` | `SinkSender` implementing `ChannelSender` (staging and load tests only) |
| `scripts/load/run.py` | `main(argv: Sequence[str] \| None = None) -> int` |

`app/telemetry/spend.py` depends on `store` and `core`, both allowed for `telemetry` (s01 §4.12).
`app/api/health.py` builds probes from adapters passed in by `app/wiring.py`, never by importing
providers directly.

## 6. Data

No new tables. Reads `turn_steps` (spend, latency), `inbox_messages` (queue age), Alembic's
`alembic_version`. The maintenance jobs update `media_blobs`, `inbox_messages`, `turns`,
`rate_limit_counters` per data-model.md §4. No migration, unless the load test shows a missing
index. Any index added then gets an `s16_<what>` migration and a note in data-model.md.

## 7. Configuration

Uses `TIMEOUT_<STEP>_S`, `TURN_BUDGET_S`, `LEASE_DURATION_S`, `DAILY_COST_CAP_USD`,
`DEMO_RATE_LIMIT_PER_HOUR`, `RETENTION_RAW_PAYLOAD_DAYS`, `RETENTION_TURN_TEXT_DAYS`, `ENVIRONMENT`,
`CHANNEL_SINK_ENABLED`, `MAINTENANCE_INTERVAL_S` (30), `PURGE_SWEEP_AFTER_S`, `OUTBOX_SENDING_STUCK_S`
(all in contracts §7).

Startup validation (raises `ConfigError`):
- `LEASE_DURATION_S ≥ 2 × TURN_BUDGET_S` (s04).
- `TURN_BUDGET_S > TIMEOUT_SAFETY_OUT_S + 2`.
- `CHANNEL_SINK_ENABLED` is false when `ENVIRONMENT=prod`.

## 8. Failure modes

S16 *is* the failure-mode step: §4.1 lists the per-step behaviour, §4.7 the system-level faults.
The remaining cases are failures of S16's own machinery:

| Failure | Behaviour |
|---|---|
| A readiness probe itself errors | `ok=False` with the error class; never crashes `/readyz` |
| A maintenance job fails | Logged at `error` with the job name; other jobs still run; retried next interval |
| The spend query fails | `SpendGuard` treats it as over the cap for demo turns (fail closed for strangers' spend) and logs `error`. WhatsApp turns are unaffected. |
| Load test run against production by mistake | Impossible by configuration: the driver refuses a target whose `/readyz` reports `ENVIRONMENT=prod` (the readiness response includes the environment name for this purpose), and the sink sender refuses to start in prod |

## 9. Tests

**Unit**
- `TurnBudget`: deadline is the step timeout when there's plenty of time; is clipped to
  `remaining − reserve` when not; returns `None` under 2 s; never negative.
- `test_config_rejects_lease_shorter_than_turn`: `LEASE_DURATION_S=40`, `TURN_BUDGET_S=25` → `ConfigError` naming both settings.
- `test_config_rejects_sink_in_prod`.
- `CachedProbe`: reuses the result within TTL (fake clock), refreshes after; a failing result is cached too (so a down provider isn't hammered).
- Each probe factory: ok case, failure case (exact `detail`), timeout case.
- `SpendGuard`: under cap passes; at exactly the cap raises `BudgetExceeded`; over cap raises;
  query failure raises `BudgetExceeded` for `demo_turn`; the 80% warning logs once per day.
- Fixed-reply coverage: every `(FixedReplyKind, Language)` pair used by §4.1 exists (complements S5's test).

**Property**
- `TurnBudget.deadline_for`, for any started time, elapsed time and timeouts: the result is
  `None` or `0 < deadline ≤ step_timeout` and `elapsed + deadline + reserve ≤ budget`.
- Retention SQL selection (run in integration against generated rows): for any set of rows with
  random timestamps, exactly those older than the retention cutoff are cleared, and nothing newer is touched.

**Negative**: every row in §4.1 is a parametrised case in
`tests/integration/test_degradation_ladder.py`, asserting the exact fixed reply, the `turn_steps`
row (`step`, `outcome`, `failure_kind`) and the turn status. Plus the cross-check: across all
those cases, no generated text exists in `outbox_messages` without an `ALLOW` `safety_out` row.

**Integration**: the hermetic chaos tests in §4.7; maintenance jobs against real tables
(`test_maintenance_clears_only_expired_rows`); `queue_probe` fails when a pending row is older than 60 s.

**Load and manual chaos**: §4.6 and §4.7, results in the load-test report, not in CI.

## 10. Exit check

1. Every row of the §4.1 table has a passing test, and the cross-check test passes.
2. `make check` and `make test-int` are green.
3. On staging, `/readyz` shows all six probes. Stopping the sidecar flips only `sidecar` (non-critical).
4. The load test passes every gated criterion in §4.6 with the manual kill-worker test performed
   during the run. The report is committed.
5. Timeout settings updated to measured values in s05 and this doc.
6. The pre-demo checklist exists in `docs/submission/`, and its first run is complete with any
   failing item fixed or tracked.
7. Feature freeze declared in plan.md §11 (S16 ticked).

## 11. Open questions

| Question | Recommendation |
|---|---|
| Should WhatsApp turns have a cost cap too? | Not by default; real users and judges must not be cut off. Add a separate, much higher alert-only threshold (log warning) if spend becomes a worry. |
| ~~Staging environment cost~~ | **Resolved (decision B7):** approved. One extra Fly/Railway app with scale-to-zero plus a Neon branch, torn down after the event. |
| Is a 25 s turn budget too generous for WhatsApp? | Keep it as the hard ceiling; the latency targets in §4.6 are what we optimise for. Users see the typing indicator within a second. |
| Run the load test with real Model API calls? | Yes, once, about 100 turns. Estimate the cost from spike E token counts before running and confirm it fits the credits. |

## Contract changes (resolved 2026-10-25)

1. **`CHANNEL_SINK_ENABLED`, `MAINTENANCE_INTERVAL_S`:** **applied** (contracts §7). The interval
   default is **30 s** (contracts and s04), not the 600 s first proposed here; this doc follows the contract.
2. **`TIMEOUT_<STEP>_S` defaults in one place:** **applied** (contracts §7). §4.2 now mirrors them.
3. **`ReadinessResponse.environment`:** **applied** in s01 §4.11
   (`Literal["local","test","staging","prod"]`).
4. **`turn_steps.grounded`:** **deferred**. Search grounding is off for the MVP (decision B8).
   The safety verdict has its own column, `turn_steps.decision` (data-model.md), instead of `detail`.

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-25 | Worker is the `app/worker/` package; timeouts, lease rule and maintenance interval follow contracts §7; maintenance owns lease takeover, stuck sends and the purge sweep; `NudgeLoop` and post-turn tasks in the audit and chaos tests; IST cost day; staging approved (B7); `safety_out` BLOCK sends REFUSE/GENERIC; webhook DB outage is `503` | Consolidation against the updated foundation docs | owner (defaults) |
