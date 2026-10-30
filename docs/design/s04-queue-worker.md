# S4 — Queue, turns and the worker

> **Hackathon build level: Exception E1. Build the single-process dispatcher in mvp-scope.md §4.1 until E1's upgrade trigger fires; then this full design.** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

> Draft v1, 2026-10-25. Reviewed and approved at the start of S4, before any code.

## 1. Purpose

Turn rows in `inbox_messages` into replies in `outbox_messages`, and deliver them. It must hold up
when things go wrong: duplicates, crashes, deploys mid-turn, and a student sending three voice
notes in a row.

This step builds the engine. The pipeline that runs inside a turn is S5's orchestrator, which S4
calls through one function.

Guarantees this step provides:
1. **Nothing lost.** Every stored inbound message ends in a reply or a recorded failure, even if
   the worker dies at any point.
2. **Nothing doubled.** One turn produces one set of reply parts. The single exception, a crash
   in the instant between Meta accepting a send and our database recording it, is documented in §4.9.
3. **In order.** One turn at a time per user. Replies are delivered in `part_no` order.

## 2. Read first

- [00-overview.md](00-overview.md) §3 (life of a message), §4 (pipeline steps)
- [contracts.md](contracts.md): §1 `InboxStatus`, `TurnStatus`, `OutboxStatus`, `StepName`, `StepOutcome`, `FailureKind`, `FixedReplyKind`; §2.2 `TurnContext`; §2.3 `StepFailure`, `StepUsage`; §2.5 `OutboundPart`; §3 `ChannelSender`, `Clock`; §4 `LeaseLost`, `DeliveryFailed`; §7 `LEASE_DURATION_S`, `WORKER_CONCURRENCY`, `RECENT_EXCHANGES`, retention settings
- [data-model.md](data-model.md): `users` (lease columns), `inbox_messages`, `turns`, `turn_steps`, `outbox_messages`, §4 retention
- [s03-whatsapp-ingress-auth.md](s03-whatsapp-ingress-auth.md) §4.6 (inbox insert + `NOTIFY inbox_new`), §4.10 (send error classification)
- [CLAUDE.md](../../CLAUDE.md) §12 (reliability rules)

## 3. Scope

**In**
- Worker process `app/worker/` (package, run as `python -m app.worker`): the supervisor, turn loop, outbox loop, listener, maintenance loop, and hosting s10b's `NudgeLoop`
- Per-user lease on `users` (decision A3): claim, renew, release, takeover after expiry
- Combining pending inbox rows into one turn; a short debounce for bursts
- `turns` creation, `TurnContext` loading, `turn_steps` recording + `NOTIFY turn_progress`
- `process_user_turn(user_hash)`: the single-turn entry point used by `TurnRunner` and by s15 evals
- The turn finalize transaction: `TurnWrite`s + outbox parts + turn update + inbox done + lease release, atomically (B2)
- Post-turn tasks (`PostTurnTask`) after finalize, each in its own transaction
- Stale and poisoned turns, handled before `run_turn` is called
- Purge-after-delivery for confirmed deletions (B4), plus the maintenance sweep
- Retry and backoff for turns (inbox) and deliveries (outbox); poison-message handling
- `LISTEN/NOTIFY` wake-ups with a polling fallback and reconnects
- Graceful shutdown on SIGTERM
- Retention jobs from data-model.md §4
- Alembic migration `s04_queue_tables`

**Out**
- What happens inside a turn (steps, routing, fallback selection) → S5. S4 only calls `run_turn`.
- WhatsApp request details → S3 (`WhatsAppSender`). Web delivery → S14 (`WebSender`).
- `TurnWrite` variants (profile changes, learners, roadmap, activities, nudge preferences, deletion) →
  defined by their owner docs (contracts §2.4); applied by the mechanism here
- What `ExtractSignals` and `UpdateMemory` do → S13 and S12. S4 only runs them after finalize.
- What `NudgeLoop` sends and when → s10b §4.11. S4 only supervises it.
- Choosing the active learner → s10b (`choose_active_learner`). S4 only calls it while loading the context.

## 4. Design

### 4.1 Worker process layout

```
python -m app.worker
└── Supervisor (asyncio)
    ├── Listener          one dedicated asyncpg connection: LISTEN inbox_new, outbox_new
    │                     sets wake events; reconnects with backoff
    ├── TurnLoop          claims users while fewer than WORKER_CONCURRENCY turns are running;
    │                     each claimed user → asyncio Task(TurnRunner)
    ├── OutboxLoop        claims deliverable parts, sends with up to OUTBOX_CONCURRENCY in flight;
    │                     triggers purge-after-delivery (§4.15)
    ├── NudgeLoop         s10b §4.11: every 60 s, creates NUDGE turns with one TEMPLATE part
    └── MaintenanceLoop   every MAINTENANCE_INTERVAL_S: expired leases, stuck 'sending', purge sweep, retention
```

- Each loop waits on its `asyncio.Event` with a timeout of `POLL_INTERVAL_S` (2 s). A NOTIFY
  wakes it at once; if notifications are lost (listener reconnecting), polling still finds the work.
- `worker_id = f"{hostname}:{pid}:{uuid4().hex[:8]}"` is set once per process and written to
  `users.lease_owner` and `turns.worker_id`.
- Several worker processes can run against one database. Every claim uses `FOR UPDATE SKIP
  LOCKED`, so they never block each other or take the same work.
- Database access goes through the async SQLAlchemy session factory (`app/store/db.py`). The
  listener uses a raw asyncpg connection, because `LISTEN` needs a connection that stays
  open and isn't returned to the pool.

### 4.2 The life of a turn

```
TurnLoop                       TurnRunner (one task per leased user)                 Postgres
   │ claim_user() ──────────────────────────────────────────────────────────────────▶ lease users row
   │◀─ user_hash                                                                     (tx 1, commits)
   ├─▶ spawn TurnRunner(user_hash)
                                │ process_user_turn(user_hash):
                                │ start_turn(): create turn, attach pending rows ──▶ (tx 2, commits)
                                │ stale or poisoned? → finalize directly (§4.4, §4.9), skip run_turn
                                │ load TurnContext
                                │ sender.acknowledge(newest message)   (best effort)
                                │ start lease heartbeat task
                                │ outcome = await run_turn(ctx, recorder, observer)   (observer = NullTurnObserver)
                                │     └─ recorder.record(step …) per step ──────────▶ turn_steps + NOTIFY turn_progress
                                │ finalize(outcome) ──────────────────────────────▶ (tx 3: lease check, TurnWrites,
                                │                                                    enqueue(delivery), turn completed,
                                │                                                    inbox done, release lease,
                                │                                                    NOTIFY outbox_new)
                                │ run outcome.post_turn tasks (§4.16), each its own tx, outside the lease
                                │ if the user has more pending rows → set the TurnLoop wake event
```

### 4.3 Claiming a user (lease)

A user is claimable when they have a due pending message, no live lease, and no message newer
than the debounce window. The debounce means a burst of voice notes becomes one turn instead of
three replies.

```sql
-- tx 1: claim_user(worker_id, lease_s, debounce_s) → user_hash | None
WITH candidate AS (
    SELECT u.user_hash
    FROM inbox_messages i
    JOIN users u ON u.user_hash = i.user_hash
    WHERE i.status = 'pending'
      AND i.available_at <= now()
      AND (u.lease_owner IS NULL OR u.lease_expires_at < now())
      AND NOT EXISTS (
            SELECT 1 FROM inbox_messages newer
            WHERE newer.user_hash = i.user_hash
              AND newer.status = 'pending'
              AND newer.received_at > now() - make_interval(secs => :debounce_s))
    ORDER BY i.available_at, i.id
    LIMIT 1
    FOR UPDATE OF u SKIP LOCKED
)
UPDATE users
SET lease_owner = :worker_id,
    lease_expires_at = now() + make_interval(secs => :lease_s),
    updated_at = now()
FROM candidate
WHERE users.user_hash = candidate.user_hash
RETURNING users.user_hash;
```

- `FOR UPDATE OF u SKIP LOCKED` locks the **users** row, so two workers can't lease the same
  user, and a worker skips users another worker is in the middle of claiming.
- An expired lease (`lease_expires_at < now()`) can be taken over, but only by this query and
  only once maintenance has reset the dead turn's rows (§4.8). Until then the user's rows are
  `processing`, not `pending`, so this query doesn't match them. That ordering is deliberate: a
  takeover never races a worker that's merely slow.
- Debounce is `TURN_DEBOUNCE_MS` (default 1000 ms). It adds up to one second to a reply, in
  exchange for answering "message 1 + 2 + 3" once and correctly.

### 4.4 Starting the turn and combining messages

```sql
-- tx 2: start_turn(user_hash, worker_id, max_messages) → turn_id + attached inbox ids
INSERT INTO turns (id, user_hash, status, prompt_versions, worker_id, started_at)
VALUES (:turn_id, :user_hash, 'processing', '{}'::jsonb, :worker_id, now());

WITH picked AS (
    SELECT id FROM inbox_messages
    WHERE user_hash = :user_hash AND status = 'pending' AND available_at <= now()
    ORDER BY provider_sent_at, id
    LIMIT :max_messages
    FOR UPDATE SKIP LOCKED
)
UPDATE inbox_messages i
SET status = 'processing', turn_id = :turn_id
FROM picked WHERE i.id = picked.id
RETURNING i.id, i.channel, i.external_id, i.kind, i.text, i.media_provider_id,
          i.media_blob_id, i.media_mime_type, i.interactive_reply_id,
          i.provider_sent_at, i.received_at;
```

Combining rules:
- **Order** is by `provider_sent_at` (when the user sent it), so an older message delivered late
  by Meta is still placed correctly. `id` breaks ties.
- **Cap:** `MAX_MESSAGES_PER_TURN` (default 5). Anything beyond the cap stays pending for the next turn.
- **Arrived mid-turn:** a message inserted after tx 2 stays `pending`. When the turn finalizes and
  releases the lease, the runner sees there's more and wakes the loop, so the late message
  starts the next turn, which sees the previous exchange in `recent_exchanges`.
- **Stale messages:** if every picked row's `provider_sent_at` is older than `STALE_MESSAGE_HOURS`
  (default 23), `StartedTurn.stale` is set and `run_turn` is **not called**. A free-form WhatsApp
  reply would fail with `131047` anyway (the 24h window has closed). S4 finalizes the turn as
  `completed` with zero parts and marks the rows `done`. Meta's 7-day webhook retry is what produces
  these. `TurnContext` carries no stale flag.
- **Zero rows picked** (a race with deletion): close the turn as `completed` with no parts and release the lease.

### 4.5 Loading the turn context

`load_turn_context(session, started) -> TurnContext`, in one read-only transaction:
- `profile` ← `users`, including `pending_question`
- `recent_exchanges` ← last `RECENT_EXCHANGES` turns with `status = 'completed'` and non-null
  `user_text`, oldest first
- `is_session_start` ← the gap between this turn's first message and the previous turn's
  `started_at` is greater than `SESSION_GAP` (`app/domain/rules/session_rules.py`, the only definition);
  `True` when there's no previous turn
- `learners` ← `learners WHERE owner_user_hash = :u` (S8; `[]` for teachers)
- `open_activity` ← the latest `learner_activities` row with `status = 'offered'` for any of those
  learners, offered less than 48 h ago (s10b; `None` until that table exists)
- `child_session` ← the open `child_sessions` row for the active learner (`ended_at IS NULL`) if it
  started less than `CHILD_SESSION_MAX_MINUTES` ago; an older open row is treated as expired
  (housekeeping closes it). `speaker` ← `LEARNER` when `child_session` is set, else `GUIDE`.
  A `ChildSessionStart` write in this turn makes later turns load it (s10b §4.16, C13)
- `active_learner` ← `choose_active_learner(learners, messages, recent_offered)`, the pure function
  owned by s10b (`app/domain/learners.py`, rules in s10b §4.2). S4 only passes the inputs; it
  doesn't encode any of the rules
- `memory` ← `profile_memory` (S12; `None` until that table exists)
- `active_roadmap` ← `roadmaps` where `status = 'active'` (S12; `None` until then)

A table that doesn't exist yet isn't a reason for an `if`. Each source is a repository function,
added to the loader in the step that creates its table.

### 4.6 What S4 asks of the orchestrator

```python
# app/pipeline/orchestrator.py  (implemented in S5; contracts §3)
async def run_turn(ctx: TurnContext, recorder: StepRecorder, observer: TurnObserver) -> TurnOutcome: ...
```

- `run_turn` **never raises** for an expected failure. Provider errors become `StepFailure`s
  inside it, and it always returns a `TurnOutcome` (contracts §2.3) whose `delivery` is a sealed
  `ReplyDelivery` with at least one part (a fixed fallback, if needed).
- It writes nothing to the database except through `recorder`. All other persistent changes come
  back as `outcome.writes` (`list[TurnWrite]`, contracts §2.4) and are applied in the finalize
  transaction. That's what makes a turn all-or-nothing: if the lease is lost, or `safety_out`
  blocked the reply, nothing the turn decided is half-applied.
- Work that must not delay the reply comes back as `outcome.post_turn` (`list[PostTurnTask]`) and
  runs after finalize (§4.16).
- `turn_steps` rows **are** written live through `recorder`, outside the finalize transaction.
  The web SSE stream needs them while the turn is running. They're telemetry: an abandoned
  turn's steps stay, and that's correct, because they happened.
- In production the observer is `NullTurnObserver`. s15's eval runner passes its own.

`StepRecorder` is the protocol in contracts §3, implemented by S4 in
`app/store/repositories/turn_step_repository.py`. Each `record` call is its own short transaction:

```sql
INSERT INTO turn_steps (turn_id, step, outcome, failure_kind, decision, detail, provider, model,
                        input_tokens, output_tokens, audio_seconds, cost_usd, started_at, duration_ms)
VALUES (...);
SELECT pg_notify('turn_progress', :turn_id::text);
```

`decision` is filled only for `safety_in` / `safety_out` rows (s07, read by the s14 trace).

**`process_user_turn(user_hash, observer=NullTurnObserver()) -> TurnId | None`** (`app/worker/turn_processor.py`) is the whole of §4.4–§4.7
plus §4.16 for one already-leased user: start the turn, handle stale or poisoned, load the
context, acknowledge, run, finalize, run post-turn tasks. It returns the turn id, or `None` when no
rows were picked. `TurnRunner` calls it after `claim_user`; s15's eval runner calls it directly,
so evals exercise exactly the production path.

`set_turn_text` and `set_turn_route` update `turns.user_text` and `turns.route` as soon as they're
known (after transcription, after routing), so the web trace can show the transcript before the
reply exists (S14). It's the same column with the same retention, just written earlier.

### 4.7 Finalizing the turn (tx 3)

```
finalize(started, worker_id, outcome):
  BEGIN
  1. SELECT 1 FROM users WHERE user_hash = :u AND lease_owner = :worker_id FOR UPDATE
       → no row: raise LeaseLost (ROLLBACK; nothing below happens)
  2. for write in outcome.writes: await write_appliers[write.kind].apply(session, user_hash, write)
       (a ProfileChange whose expected_state no longer matches raises LeaseLost → ROLLBACK)
  3. await outbox.enqueue(session, turn_id, user_hash, channel, outcome.delivery)
       → INSERT INTO outbox_messages (…, kind, text, audio_blob_id, buttons, template, status 'pending', …)
         one row per ReplyDelivery part, ON CONFLICT (turn_id, part_no) DO NOTHING
  4. UPDATE turns SET status = 'completed', route = :route,
                      user_text = CASE WHEN :fixed = 'crisis' THEN NULL ELSE :user_text END,
                      reply_text = :reply_text, reply_register = :register,
                      fixed_reply_kind = :fixed, prompt_versions = :versions,
                      failure_step = :fs, failure_kind = :fk, completed_at = now()
     WHERE id = :turn_id
  5. UPDATE inbox_messages SET status = 'done' WHERE turn_id = :turn_id
  6. UPDATE users SET lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
     WHERE user_hash = :u
  7. SELECT pg_notify('outbox_new', '')        (only if parts were inserted)
  COMMIT
```

- **Turn status (B3):** `completed` whenever `run_turn` returned, including when a step failed and a
  fallback reply was sent; `first_failure` fills `failure_step` / `failure_kind`. `failed` is
  reserved for turns that crashed, raised unexpectedly, lost their lease, or were requeued at
  shutdown (§4.8, §4.9, §4.12). Those turns enqueue nothing and their inbox rows are retried.
- **Crisis turns (B5):** `user_text` was written early by `StepRecorder.set_turn_text` for the web
  trace. Step 4 overwrites it with `NULL` when `fixed_reply_kind = 'crisis'`, so crisis text is
  never kept past the turn.
- **`OutboxRepository.enqueue`** accepts only a `ReplyDelivery` (sealed, contracts §2.6). It's the
  only code that inserts `outbox_messages` rows, which s07's AST test checks.
- **Write appliers** are registered by `TurnWrite.kind` in `app/wiring.py` (`profile_change` →
  users repo, `learner_upsert` → learners repo, `save_roadmap` → roadmaps repo, …). At startup, a
  wiring check iterates the variants of the `TurnWrite` union and raises `ConfigError` naming any
  variant with no applier, so a missing applier fails the deploy, not a turn.
- **Lease loss** (step 1 or 2): the runner logs `warning lease_lost`, drops the outcome, and writes
  nothing. The turn that took over (§4.8) produces the reply. The abandoned `turns` row was already
  marked `failed` by maintenance during the takeover.

### 4.8 Lease heartbeat, expiry and takeover

- While `run_turn` runs, a heartbeat task renews the lease every `LEASE_DURATION_S / 3`:

```sql
UPDATE users SET lease_expires_at = now() + make_interval(secs => :lease_s)
WHERE user_hash = :u AND lease_owner = :worker_id
RETURNING 1;
```

  No row returned → the lease is lost. The heartbeat cancels the turn task, and the runner exits
  without finalizing. `TURN_BUDGET_S` (25 s) is well below `LEASE_DURATION_S` (60 s), so a healthy
  turn never loses its lease. Loss means the process stalled, the database connection broke, or
  maintenance judged the worker dead.

- **Maintenance takeover** of expired leases (worker died or stalled), every `MAINTENANCE_INTERVAL_S`:

```sql
WITH expired AS (
    SELECT user_hash FROM users
    WHERE lease_owner IS NOT NULL AND lease_expires_at < now()
    FOR UPDATE SKIP LOCKED
),
dead_turns AS (
    UPDATE turns t SET status = 'failed', failure_kind = 'internal',
                       completed_at = now()
    FROM expired WHERE t.user_hash = expired.user_hash AND t.status = 'processing'
    RETURNING t.id
),
reset_inbox AS (
    UPDATE inbox_messages i
    SET status = 'pending', turn_id = NULL, attempts = i.attempts + 1,
        available_at = now() + make_interval(secs => least(60, 5 * power(2, i.attempts)))
    FROM dead_turns WHERE i.turn_id = dead_turns.id AND i.status = 'processing'
    RETURNING i.id
)
UPDATE users u SET lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
FROM expired WHERE u.user_hash = expired.user_hash;
```

  Takeover always goes through maintenance, never directly through `claim_user`. That keeps "who
  owns the processing rows" unambiguous.

### 4.9 Turn retries and poison messages

| What happened | Inbox rows | Turn | User gets |
|---|---|---|---|
| `run_turn` returned (with or without a step failure) | `done` | `completed` (`failure_step`/`failure_kind` set if a step failed) | a reply (real or fallback) |
| `run_turn` raised an unexpected exception (a bug) | back to `pending`, `attempts + 1`, backoff | `failed`, `failure_kind = 'internal'` | nothing yet; retried |
| Worker died / lease expired | back to `pending` via maintenance, `attempts + 1` | `failed` | nothing yet; retried |
| Lease lost at finalize | untouched by this worker (maintenance already reset them) | `failed` (by maintenance) | the takeover turn's reply |
| A row reaches `attempts >= MAX_TURN_ATTEMPTS` (3) at claim time | `failed` | a new turn is finalized as `completed` with a `TRY_AGAIN_LATER` fixed part | the fixed fallback, once |

- Backoff: `available_at = now() + min(60 s, 5 s × 2^attempts)`.
- The unexpected-exception branch is the one place a broad `except Exception` is allowed: the
  turn supervisor's boundary. It logs at `error` with the exception attached, records the
  failure on the turn, and puts the rows back. That satisfies CLAUDE.md §1, because the
  failure is recorded and is distinguishable from success. `asyncio.CancelledError` is never caught there.
- Poison handling happens in `start_turn`. Rows picked with `attempts >= MAX_TURN_ATTEMPTS`
  aren't passed to `run_turn`. The runner builds the reply through the same sealed path as every
  other fixed reply: `FixedReplyService.localise(TRY_AGAIN_LATER, DEFAULT, language)` →
  `SafetyGate.clear_fixed(...)` → `ReplyPartsBuilder.build(safe_reply, None)` → `ReplyDelivery`. It finalizes the
  turn with that delivery (`fixed_reply_kind = 'try_again_later'`, no writes, no post-turn tasks) and
  marks those rows `failed`. The reply stays sealed, so the outbox invariant holds here too.

### 4.10 Outbox delivery

```sql
-- claim_deliverable(batch) → rows to send
WITH due AS (
    SELECT o.id FROM outbox_messages o
    WHERE o.status = 'pending'
      AND o.available_at <= now()
      AND NOT EXISTS (                       -- strict part order within a turn
            SELECT 1 FROM outbox_messages earlier
            WHERE earlier.turn_id = o.turn_id
              AND earlier.part_no < o.part_no
              AND earlier.status IN ('pending', 'sending'))
    ORDER BY o.available_at, o.id
    LIMIT :batch
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox_messages o
SET status = 'sending', attempts = o.attempts + 1, sending_since = now()
FROM due WHERE o.id = due.id
RETURNING o.*;
```

For each claimed row:
1. Load the recipient. WhatsApp: decrypt `users.address_ciphertext` → `ChannelAddress`
   (S3 `UserIdentity`; a failed decrypt raises `InvalidAddressCiphertext` → `failed`). Web:
   `ChannelAddress(channel=WEB, address=SecretStr(user_hash))` (S14).
   If the user row is gone (deleted), the outbox row is already gone too, thanks to the cascade.
2. WhatsApp only, and **not for `kind = 'template'`**: if `users.last_inbound_at < now() - 24h`,
   don't call Meta. Mark `failed`, `last_error = 'window_closed'`. Template parts (s10b nudges) are
   the one kind Meta delivers outside the 24-hour window, so they skip this check.
3. Load the audio from `media_blobs` if `kind = 'audio'`.
4. `receipt = await sender.send(part, recipient, audio)` (contracts §3 `ChannelSender`).
5. Success → `mark_sent`: `status = 'sent'`, `sent_at`, `provider_message_id`, `sending_since = NULL`.
   For web parts, `mark_sent` also runs `pg_notify('turn_progress', turn_id)` in the same
   transaction so the API can emit `turn.completed` (s14). Status webhooks later move WhatsApp parts
   to delivered/read (S3 §4.8).
6. Retryable `ProviderError`, with `attempts < OUTBOX_MAX_ATTEMPTS` (5) → `status = 'pending'`,
   `sending_since = NULL`, `available_at = now() + min(60 s, 2 s × 2^attempts)` (or `Retry-After`),
   `last_error = <code>`.
7. Non-retryable, or attempts exhausted → `status = 'failed'`, `last_error`, log as `DeliveryFailed`.
8. After 5 or 7: if this was the last part of its turn to leave `pending`/`sending`, run the
   purge-after-delivery check (§4.15).

A failed earlier part doesn't block later parts (the `NOT EXISTS` only waits for `pending` and
`sending`). If the audio fails, the text still goes out. That's the degradation we want.

**The one duplicate window:** a crash after Meta accepts a send but before step 5 commits
leaves the row in `sending`. Maintenance resets `sending` rows older than `OUTBOX_SENDING_STUCK_S`
(60 s) to `pending`, and the part is sent again. The Cloud API has no idempotency key, so this
at-least-once window can't be closed. It's rare, it's logged as `outbox_resend_after_stuck`, and a
duplicate message is better than a lost one.

### 4.11 Listener

- One asyncpg connection runs `LISTEN inbox_new; LISTEN outbox_new;` and sets `turn_wake` /
  `outbox_wake` on each notification. Payloads are ignored: a notification means "look", never "here's the work".
- Connection loss: log `warning listener_disconnected`, reconnect with backoff (0.5 s → 30 s cap,
  with jitter). The loops keep polling meanwhile, so the only cost is up to `POLL_INTERVAL_S` of extra latency.
- `turn_progress` isn't listened to by the worker. It's for the API's SSE streams (S14).

### 4.12 Graceful shutdown

On SIGTERM (Fly/Railway send it on deploy):
1. Stop claiming (TurnLoop, OutboxLoop and NudgeLoop stop taking new work). A post-turn task
   already running gets the grace period too; one not yet started is dropped (it's telemetry or memory, §4.16).
2. Wait up to `SHUTDOWN_GRACE_S` (20 s) for running turns and in-flight sends to finish normally.
3. Cancel turns still running. For each, in one transaction: `turns.status = 'failed'`, its inbox
   rows back to `pending` **without** incrementing `attempts` (a deploy isn't the message's
   fault), `available_at = now()`, lease released. Another worker (or this one after restart)
   picks them up immediately.
4. In-flight sends that don't finish are left in `sending`, and maintenance recovers them (§4.10).
5. Close the listener and the pool, then exit 0.

The platform's kill timeout must be longer than `SHUTDOWN_GRACE_S` (set Fly `kill_timeout = 30`).

### 4.13 Maintenance loop

Every `MAINTENANCE_INTERVAL_S` (30 s), each job in its own transaction, each idempotent:

| Job | Action |
|---|---|
| Expired leases | §4.8 takeover query |
| Stuck sends | `UPDATE outbox_messages SET status = 'pending', sending_since = NULL WHERE status = 'sending' AND sending_since < now() - OUTBOX_SENDING_STUCK_S` |
| Child sessions | `UPDATE child_sessions SET ended_at = now(), end_reason = 'expired' WHERE ended_at IS NULL AND started_at < now() - CHILD_SESSION_MAX_MINUTES` … `RETURNING id`; for each, run the `SendChildSessionSummary` post-turn task (topics only), inside the 24 h window (C13) |
| Purge sweep | §4.15: purge users whose `purge_after_turn_id` turn completed more than `PURGE_SWEEP_AFTER_S` (600 s) ago |
| Inbound audio | `DELETE FROM media_blobs WHERE purpose = 'inbound_audio' AND expires_at < now()` (S6 deletes on successful transcription; this catches the rest) |
| Reply audio | `DELETE FROM media_blobs WHERE purpose = 'reply_audio' AND expires_at < now()` |
| Raw payloads | `UPDATE inbox_messages SET raw_payload = NULL WHERE raw_payload IS NOT NULL AND received_at < now() - RETENTION_RAW_PAYLOAD_DAYS` |
| Turn text | `UPDATE turns SET user_text = NULL, reply_text = NULL WHERE completed_at < now() - RETENTION_TURN_TEXT_DAYS AND (user_text IS NOT NULL OR reply_text IS NOT NULL)` |
| Rate-limit windows | `DELETE FROM rate_limit_counters WHERE window_start < now() - interval '2 days'` (from S14) |

Retention updates run in batches of 1000 rows (`WHERE id IN (SELECT … LIMIT 1000)`) so one
maintenance pass never holds long locks.

### 4.14 Crash-safety analysis

| Crash point | State left behind | Recovery | Result for the user |
|---|---|---|---|
| Webhook, before commit | nothing stored | Meta retries (non-200, or no response) | reply arrives a little later |
| Webhook, after commit, before 200 | row stored | Meta retries; `ON CONFLICT DO NOTHING` | one reply |
| After claim (tx 1), before `start_turn` | user leased, rows still `pending` | lease expires; maintenance clears it (no processing rows to reset); the next claim takes the user | reply delayed by ≤ `LEASE_DURATION_S` |
| After `start_turn`, during `run_turn` | turn `processing`, rows `processing`, lease live | lease expires → maintenance marks the turn failed, resets the rows (attempts + 1) → new turn | reply delayed by ≤ ~60 s; no duplicate (the dead turn wrote no parts) |
| During finalize (tx 3) | transaction rolled back entirely | same as the previous row | same |
| After finalize, before sending | parts `pending` | OutboxLoop sends them after restart | reply arrives after the restart |
| After claiming a part (`sending`), before calling Meta | part `sending` | maintenance resets it after 60 s | delayed, sent once |
| After Meta accepted, before recording `sent` | part `sending`, message on the phone | maintenance resets it after 60 s → **sent again** | **possible duplicate** (§4.10) |
| After `sent` recorded | done | — | one reply |
| SIGTERM (deploy) | handled by §4.12 | — | reply delayed by the deploy |
| Database unreachable | loops fail their transactions | each loop logs, backs off and retries; leases expire naturally; nothing is marked done without a commit | delayed |

### 4.15 Purge after delivery (B4)

A confirmed delete-my-data (or a declined consent) can't delete the user inside the turn: the
cascade would remove the confirmation's outbox row and the encrypted address needed to send it.
So s08 returns a `MarkPurgeAfterDelivery` write, and the purge happens after delivery:

1. **Finalize** applies `MarkPurgeAfterDelivery` → `UPDATE users SET purge_after_turn_id = :turn_id`.
2. **Outbox loop**, after a part reaches `sent` or `failed` (§4.10 step 8):
   ```sql
   SELECT u.user_hash FROM users u
   WHERE u.purge_after_turn_id = :turn_id
     AND NOT EXISTS (SELECT 1 FROM outbox_messages o
                     WHERE o.turn_id = :turn_id AND o.status IN ('pending','sending'));
   ```
   A row means this was the last part, so the loop calls `users.purge_user(user_hash)`
   (`DELETE FROM users …`, cascading everywhere, s08 §4.11) in its own transaction.
3. **Maintenance sweep** (safety net for crashes between steps 1 and 2):
   ```sql
   SELECT u.user_hash FROM users u JOIN turns t ON t.id = u.purge_after_turn_id
   WHERE t.completed_at < now() - make_interval(secs => :purge_sweep_after_s);
   ```
   Each match is purged, whatever its outbox state.

Messages that arrive between the confirmation and the purge are deleted with the user, which is
what they asked for. A message after the purge creates a fresh `NEW` user (s08 §4.10).

### 4.16 Post-turn tasks

After finalize commits, the runner executes each `PostTurnTask` in `outcome.post_turn`, in order,
outside the lease:

| Task | Runs | Step row |
|---|---|---|
| `ExtractSignals` | s13 `SignalExtractor` (aspiration signals for student turns, curiosity signals for parent reports); writes `aspiration_signals` / `curiosity_signals` with `ON CONFLICT (turn_id) DO NOTHING` | `EXTRACT_SIGNALS` |
| `UpdateMemory` | s12 `MemoryLayer`; upserts `profile_memory` | `UPDATE_MEMORY` |

- Each task gets `TIMEOUT_EXTRACT_SIGNALS_S` / `TIMEOUT_UPDATE_MEMORY_S` and runs its model call
  outside any transaction, then writes in **its own short transaction**, recording one `turn_steps`
  row (`OK`, `FAILED` or `SKIPPED`).
- A task never affects the reply: it runs after the reply is committed, and its failure is only
  the step row and a `warning` log.
- If the user was deleted in the meantime (a foreign-key violation on insert, or `NotFound`), the
  task logs `info post_turn_user_gone` and records nothing further. That's the expected outcome of
  a fast deletion, not an error.
- A worker crash during post-turn tasks loses only that telemetry or memory update. The reply is
  already committed, so nothing is retried, and the next turn's tasks catch up.
- Post-turn tasks run before the runner checks `more_pending`, so a user's next turn starts after
  their previous turn's memory update. That keeps memory in order at the cost of up to
  `TIMEOUT_UPDATE_MEMORY_S` of extra delay for a back-to-back message.

## 5. Interfaces

```python
# app/worker/__main__.py   (the worker is the package app/worker/; `python -m app.worker`)
def main() -> None: ...                       # builds wiring, runs Supervisor

# app/worker/supervisor.py
class Supervisor:
    def __init__(self, deps: WorkerDeps, settings: WorkerSettings, clock: Clock) -> None: ...
    async def run(self) -> None: ...          # until shutdown
    def request_shutdown(self) -> None: ...   # signal handler

# app/worker/turn_processor.py
class TurnLoop:     async def run(self, stop: asyncio.Event) -> None: ...
class TurnRunner:   async def run(self, user_hash: UserHash) -> None: ...    # calls process_user_turn
async def process_user_turn(user_hash: UserHash, observer: TurnObserver = NullTurnObserver()) -> TurnId | None: ...  # contracts §3; s15 passes its observer

# app/worker/post_turn.py
async def run_post_turn(started: StartedTurn, tasks: Sequence[PostTurnTask], runners: PostTurnRunners) -> None: ...

# app/worker/nudges.py  (owned by s10b; supervised here)
class NudgeLoop: async def run(self, stop: asyncio.Event) -> None: ...

# app/worker/outbox.py
class OutboxLoop:   async def run(self, stop: asyncio.Event) -> None: ...

# app/worker/listener.py
class NotificationListener:
    async def run(self, stop: asyncio.Event) -> None: ...   # sets turn_wake / outbox_wake

# app/worker/maintenance.py
class MaintenanceLoop: async def run(self, stop: asyncio.Event) -> None: ...

# app/store/repositories/leases.py
async def claim_user(session: AsyncSession, worker_id: str, lease_s: int, debounce_s: float) -> UserHash | None: ...
async def renew_lease(session: AsyncSession, user_hash: UserHash, worker_id: str, lease_s: int) -> bool: ...
async def take_over_expired_leases(session: AsyncSession) -> int: ...

# app/store/repositories/turn_repository.py
async def start_turn(session: AsyncSession, user_hash: UserHash, worker_id: str, max_messages: int) -> StartedTurn: ...
async def load_turn_context(session: AsyncSession, started: StartedTurn) -> TurnContext: ...
async def finalize_turn(session: AsyncSession, started: StartedTurn, worker_id: str,
                        outcome: TurnOutcome, appliers: WriteAppliers) -> FinalizeResult: ...  # raises LeaseLost
async def finalize_fixed(session: AsyncSession, started: StartedTurn, worker_id: str,
                         delivery: ReplyDelivery | None, fixed: FixedReplyKind | None) -> FinalizeResult: ...
                                              # stale (delivery None) and poisoned turns
async def requeue_turn(session: AsyncSession, turn_id: TurnId, count_attempt: bool) -> None: ...

# app/worker/writes.py
class WriteApplier(Protocol[W]):
    async def apply(self, session: AsyncSession, user_hash: UserHash, write: W) -> None: ...
WriteAppliers = Mapping[str, WriteApplier[TurnWrite]]       # keyed by TurnWrite.kind
def check_write_appliers(appliers: WriteAppliers) -> None: ... # startup: every variant covered, else ConfigError

# app/store/repositories/outbox_repository.py  (adds to S3's apply_status_update)
class OutboxRepository:
    async def enqueue(self, session: AsyncSession, turn_id: TurnId, user_hash: UserHash,
                      channel: Channel, delivery: ReplyDelivery) -> int: ...   # the only outbox insert
async def claim_deliverable(session: AsyncSession, batch: int) -> list[OutboxRow]: ...
async def mark_sent(session: AsyncSession, outbox_id: int, receipt: DeliveryReceipt) -> None: ...
async def mark_retry(session: AsyncSession, outbox_id: int, error_code: str, delay_s: float) -> None: ...
async def mark_failed(session: AsyncSession, outbox_id: int, error_code: str) -> None: ...
async def purge_due_after_delivery(session: AsyncSession, turn_id: TurnId) -> UserHash | None: ...
async def purge_sweep(session: AsyncSession, older_than_s: int) -> list[UserHash]: ...

class StartedTurn(BaseModel):     # frozen
    turn_id: TurnId
    user_hash: UserHash
    messages: list[InboundMessage]
    poisoned: bool                # every picked row hit MAX_TURN_ATTEMPTS
    stale: bool                   # every picked row is older than STALE_MESSAGE_HOURS

class FinalizeResult(BaseModel):  # frozen
    parts_enqueued: int
    more_pending: bool            # the user has newer pending rows → wake the TurnLoop
```

`OutboxRow` is a frozen dataclass mirroring the `outbox_messages` columns the loop needs.

## 6. Data

- **Migration `s04_queue_tables`**:
  - adds `users.lease_owner`, `users.lease_expires_at` and their index
  - adds `inbox_messages.attempts`, `available_at`, `turn_id`, and the partial index on `(status, available_at)`
  - creates `turns` (without `learner_id`, which s10b adds), `turn_steps` (including `decision`),
    and `outbox_messages` (including `sending_since` and `template`)
  - `users.purge_after_turn_id` and its index are added by s08's migration, with the deletion flow
- **Writes:** `users` (lease columns; `purge_after_turn_id` via the s08 write; purge deletes),
  `inbox_messages` (status, attempts, available_at, turn_id), `turns`, `turn_steps`, `outbox_messages`,
  plus every table a `TurnWrite` applier or `PostTurnTask` touches (owned by those steps). Retention
  updates `media_blobs`, `inbox_messages`, `turns`, `learner_activities`, `rate_limit_counters`.
- **Reads:** everything `load_turn_context` needs (`users`, `turns`, `learners`, `learner_activities`,
  `profile_memory`, `roadmaps`, `roadmap_steps`).
- **Notification channels:** `inbox_new` (S3/S14 → worker), `outbox_new` (finalize → outbox loop),
  `turn_progress` (recorder and web delivery → API SSE).

## 7. Configuration

All from contracts.md §7 (turn engine table): `LEASE_DURATION_S` (60), `WORKER_CONCURRENCY` (8),
`TURN_BUDGET_S` (25), `TURN_DEBOUNCE_MS` (1000), `MAX_MESSAGES_PER_TURN` (5), `MAX_TURN_ATTEMPTS`
(3), `STALE_MESSAGE_HOURS` (23), `RECENT_EXCHANGES` (6), `OUTBOX_CONCURRENCY` (4),
`OUTBOX_MAX_ATTEMPTS` (5), `OUTBOX_SENDING_STUCK_S` (60), `POLL_INTERVAL_S` (2),
`MAINTENANCE_INTERVAL_S` (30), `SHUTDOWN_GRACE_S` (20), `PURGE_SWEEP_AFTER_S` (600),
`TIMEOUT_EXTRACT_SIGNALS_S` (6), `TIMEOUT_UPDATE_MEMORY_S` (6), `RETENTION_*`, `DATABASE_URL`.

Startup check: `LEASE_DURATION_S ≥ 2 × TURN_BUDGET_S`, else `ConfigError` naming both.

## 8. Failure modes

| Failure | User sees | Recorded |
|---|---|---|
| Orchestrator returns a step failure | a fixed fallback reply | turn `completed` with `failure_step`/`failure_kind`, the failing `turn_steps` row |
| Orchestrator raises (a bug) | nothing, then a reply on retry, or `TRY_AGAIN_LATER` after 3 attempts | turn `failed` `internal`, log `error` with the exception, attempts incremented |
| A `TurnWrite` variant has no applier | — (deploy fails) | `ConfigError` at startup naming the variant |
| Post-turn task fails | nothing (the reply already went) | `EXTRACT_SIGNALS` / `UPDATE_MEMORY` row `FAILED`, `warning` log |
| Purge after delivery fails (database error) | the user already got `DATA_DELETED` | `error` log; the maintenance sweep purges within `PURGE_SWEEP_AFTER_S` |
| Worker crash / deploy | a delayed reply | per §4.14 |
| Lease lost mid-turn | one reply (from the takeover turn) | log `warning lease_lost` |
| Send fails, retryable | a delayed reply | outbox `attempts`, `last_error` |
| Send fails permanently | no reply (or text without audio) | outbox `failed`, log `error` `delivery_failed` with the code |
| 24h window closed before delivery | no reply | outbox `failed` `window_closed` |
| Listener down | up to 2 s extra latency | log `warning`, reconnect attempts |
| Database down | delays | each loop logs `error` and backs off; nothing is half-written |

## 9. Tests

**Unit** (fakes: a `FakeOrchestrator` returning scripted `TurnOutcome`s, a `FakeSender`, `FakeClock`)
- `process_user_turn` calls `acknowledge` with the newest message, then `run_turn(ctx, recorder, NullTurnObserver())`, then finalize, then the post-turn tasks; `acknowledge` raising doesn't stop the turn
- Backoff functions: values at attempts 0, 1, 2, 5, and the 60 s cap
- Poison path: a `StartedTurn` with `poisoned=True` never calls `run_turn` and finalizes exactly one `TRY_AGAIN_LATER` part, built through `clear_fixed` → `ReplyPartsBuilder.build` (a `ReplyDelivery`, not raw parts); the turn is `completed`
- Stale path: `stale=True` never calls `run_turn`, finalizes zero parts, marks rows done
- Turn status: a scripted outcome with `first_failure` set → turn `completed` with `failure_step`/`failure_kind`; an orchestrator that raises → `failed`
- Crisis outcome (`fixed_reply_kind=CRISIS`, `user_text` set) → the finalize statement writes `user_text = NULL`
- `check_write_appliers` with one `TurnWrite` variant missing → `ConfigError` naming that `kind`
- Post-turn: a task raising → its step row is `FAILED` and the remaining tasks still run; a task hitting a foreign-key violation (user deleted) → logged, no further writes; tasks never run when finalize raised `LeaseLost`
- `load_turn_context`: `is_session_start` true with no previous turn, true at a gap of 6 h + 1 s, false at exactly 6 h; `choose_active_learner` is called with the loaded learners and messages (fake asserts its inputs)
- Heartbeat: when `renew_lease` returns `False`, the turn task is cancelled and `finalize_turn` is never called
- Shutdown: running turns past the grace period are requeued with `count_attempt=False`
- Outbox error mapping: each `ProviderError` subclass → retry or failed, per §4.10, using S3's classifier output
- Settings validation: `TURN_BUDGET_S = 40`, `LEASE_DURATION_S = 60` → `ConfigError` naming both

**Property** (hypothesis, pure functions extracted from the loops)
- Combining: for any generated set of pending messages for one user (random `provider_sent_at`,
  random arrival order), the picked batch is the oldest `min(n, MAX_MESSAGES_PER_TURN)` by
  `(provider_sent_at, id)`, and the rest stay pending, unchanged.
- Delivery order: for any interleaving of part outcomes (sent, failed, retry), a part is never
  sent while an earlier part of the same turn is `pending` or `sending`, and every part ends in `sent` or `failed`.
- Status monotonicity: covered in S3.

**Negative**
- `finalize_turn` with a lease owned by another worker → `pytest.raises(LeaseLost, match=<user_hash prefix>)`, and **no** outbox row, no inbox status change, no write applied.
- A `TurnWrite` variant with no applier → startup `ConfigError` naming its `kind`.
- A `ProfileChange` whose `expected_state` no longer matches → `LeaseLost`, nothing written.
- `claim_user` with all pending rows inside the debounce window → `None`.
- Delivering a part for a user whose `last_inbound_at` is 25 h old → `failed` `window_closed`, sender never called.
- The same, for a `TEMPLATE` part → the sender **is** called (templates skip the window check).
- `OutboxRepository.enqueue` given anything other than a `ReplyDelivery` is a mypy error (type-level test in `tests/typing/`), and a `ReplyDelivery` built without the seal raises `TypeError` (s07).

**Integration** (`@pytest.mark.integration`, real Postgres)
- **Concurrent claims:** two workers × 50 users with pending rows → every user claimed exactly once, no row in two turns.
- **Same user, two workers:** only one gets the lease; the other gets `None`.
- **Duplicate webhook → one reply:** insert the same `(channel, external_id)` 3 times, run the worker → 1 turn, 1 set of parts (CLAUDE.md §3 inbox property).
- **Kill mid-turn:** start a turn with a `FakeOrchestrator` that blocks; expire the lease (set `lease_expires_at` in the past); run maintenance → turn `failed`, rows `pending` with `attempts = 1`; run the worker again → exactly one set of parts.
- **Lease lost at finalize:** finalize after maintenance took over → `LeaseLost`, zero parts from the first turn, one set from the second.
- **Message mid-turn:** insert a message while the first turn is running → it's not in the first turn, and it becomes the next turn after finalize.
- **Burst:** 3 messages 300 ms apart → one turn with 3 messages (debounce).
- **Poison:** a message whose orchestrator call raises 3 times → one `TRY_AGAIN_LATER` part, row `failed`.
- **Outbox order:** parts 0, 1, 2 where part 0 fails retryably twice → part 1 isn't sent before part 0 succeeds; when part 0 fails permanently, parts 1 and 2 still go out.
- **Stuck sending:** a row in `sending` older than 60 s is reset to `pending` by maintenance.
- **NOTIFY wake-up:** with polling set to 60 s, an inserted inbox row is claimed within 500 ms (the listener works); with the listener disabled, it's claimed within one poll interval.
- **Deletion cascade:** deleting a user removes their turns, turn_steps and outbox rows (supports s08).
- **Purge after delivery:** a turn finalized with `MarkPurgeAfterDelivery` and two parts → after part 0 is sent the user still exists; after part 1 is sent (or fails permanently) the user and every dependent row are gone.
- **Purge sweep:** a user with `purge_after_turn_id` whose turn completed 11 minutes ago and whose part is stuck `pending` → purged by maintenance.
- **Writes are atomic with the outbox:** a fake applier that raises after a `ProfileChange` is applied → no outbox row, the users row unchanged, the inbox rows still `processing` (retried by takeover).
- **Post-turn after deletion:** delete the user between finalize and the post-turn task → no `aspiration_signals` row and no exception escapes.
- **Template part:** a `NUDGE` turn's `TEMPLATE` part for a user whose last inbound was 3 days ago is sent.
- **Web `mark_sent`** emits a `turn_progress` notification with the turn id.
- **Retention:** rows past each window are cleared; rows inside it are untouched.
- The migration upgrades, downgrades and upgrades again.

## 10. Exit check

1. Run `api` and `worker` against Neon, with S5's orchestrator returning a simple real reply
   (the S5 text round trip) or, before S5 lands, S5's fixed-reply path only.
2. Send one WhatsApp text → exactly one reply. `turns` has one `completed` row; `turn_steps` has rows; outbox part `sent` then `delivered`, with `sending_since` NULL again.
3. Send three texts within one second → **one** reply that addresses all three.
4. Start a slow turn (a debug setting adding a 30 s delay inside the fake step), then `kill -9`
   the worker. Restart it. Within about 60 s there is exactly one reply, and the dead turn is `failed`.
5. Re-POST the same signed webhook body with `curl` → no second reply.
6. Deploy while a turn is running → the reply still arrives, once.

## 11. Open questions

1. **Debounce default:** 1 s adds latency to every turn. *Recommendation:* keep 1 s, and measure
   in S16 how often bursts actually happen. Drop it to 500 ms if they're rare.
2. ~~**Deletion and the confirmation message.**~~ **Resolved (B4):** the `MarkPurgeAfterDelivery`
   write sets `users.purge_after_turn_id`; the outbox loop purges after the last part is delivered,
   and maintenance sweeps after `PURGE_SWEEP_AFTER_S` (§4.15).
3. **Worker in the same process as the api** (one Fly machine, two processes vs one): *Recommendation:*
   separate processes in one Fly app (`[processes]` app + worker), sharing the image.

## Contract changes (resolved 2026-10-25)

| Request | Resolution |
|---|---|
| `TurnOutcome` | Applied in contracts §2.3, in s05's shape (`delivery: ReplyDelivery`, `writes`, `post_turn`, `first_failure`). s04's `parts`/`effects` draft is withdrawn |
| `TurnEffect` + `EffectApplier` | Replaced by `TurnWrite` (contracts §2.4, B2) and `WriteApplier` keyed by `kind` (§5) |
| `StepRecorder` | Applied in contracts §3 (keyword `record` with `detail`, plus `set_turn_text` / `set_turn_route`) |
| `TurnContext.stale` | Withdrawn: stale and poisoned turns are handled by s04 before `run_turn` (§4.4, §4.9) |
| `run_turn(ctx, recorder)` | Applied as `run_turn(ctx, recorder, observer)` (contracts §3), with `process_user_turn` added |
| Settings in §7 | Applied in contracts §7, plus `PURGE_SWEEP_AFTER_S` |
| `outbox_messages.sending_since`, the `outbox_new` channel, `turns.user_text`/`route` written during the turn | Applied in data-model.md; crisis `user_text` NULL at finalize (B5) |
| `app/worker/` package instead of `app/worker.py` | Applied in 00-overview.md §2 |

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-28 | **E1 upgrade built** (owner's build order, step 5). `LeaseRepository` (`app/store/repositories/lease_repository.py`: `claim_user`, `acquire`, `renew`, `release`, `take_over_expired`, `until_claimable`); finalize checks the lease first (`LeaseLost` naming the user prefix) and releases it in the same transaction, abandon releases it too; `TurnLoop` (claim up to `WORKER_CONCURRENCY`, heartbeat every third of `LEASE_DURATION_S`, a lost lease cancels the turn), `OutboxLoop` (`OUTBOX_CONCURRENCY` turns at a time), `MaintenanceLoop` (takeover, stuck sends after `OUTBOX_SENDING_STUCK_S`, retention, sweeps, nudges), `NotificationListener` (`app/store/`, its own unpooled engine), `Supervisor`, `python -m app.worker`; migration `s04_user_leases`. `TurnDispatcher`, startup recovery and `reset_sending` are removed. **Choices, pending owner review:** (1) the worker still runs inside the api by default (`RUN_WORKER_IN_API=true`, one process for local use and the demo); `false` plus `python -m app.worker` splits them, and any mix is safe; (2) the takeover also fails a `processing` turn whose user holds **no** lease (nobody can be running it), so turns left by the old single-process build are recovered; (3) the runner still sends its own reply straight after finalize (lowest latency), and the outbox loop only retries and recovers; (4) `DATABASE_LISTEN_URL`: Neon's pooled endpoint can't hold a `LISTEN`, so the listener takes the direct URL when it's set; when it isn't, the loops poll every 2 s; (5) `process_user_turn` stays the single-turn entry point; a caller outside the loop (s15 evals) takes the lease first with `LeaseRepository.acquire` | s04 §4.1-§4.13; mvp-scope E1 upgrade trigger | pending owner review |
| 2026-10-27 | **E1 build.** In-process `TurnDispatcher` (`app/worker/turn_dispatcher.py`): one task per user, debounce, startup recovery (`processing` turns → failed, rows → pending with attempts + 1; `sending` parts → pending), a maintenance pass (due parts, missed wakes, retention). `TurnProcessor.process_user_turn` (`app/worker/turn_processor.py`), `Deliverer` (`app/worker/reply_deliverer.py`), `DatabaseStepRecorder` (`app/worker/database_step_recorder.py`); stores in `app/store/repositories/{turns,outbox,turn_steps}.py`. No leases, heartbeat, LISTEN/NOTIFY or outbox loop (Phase 2) | mvp-scope §4.1, exception E1 | owner (E1) |
| 2026-10-27 | **Staged contract types:** `TurnContext`, `UserProfile` and `TurnOutcome` carry only what exists after S4; S8 adds `TurnWrite`/`writes`, learners and profile fields, S10b/S12/S13 their fields and `post_turn`, each with its table. Write appliers and `check_write_appliers` arrive with the first `TurnWrite` (S8) | Same staged-delivery rule as s05 §4.4; no stub fields | owner (S4 review) |
| 2026-10-27 | **Sealed fixed path built in S4:** `SafeReply` + `SafetyGate.clear_fixed` (`app/safety/safety_gate.py`), `ReplyDelivery` + `ReplyPartsBuilder.build` (`app/pipeline/reply_parts_builder.py`), `MessageSplitter.split`, `FixedReplyService.localise` with `TRY_AGAIN_LATER` in hi/hinglish/en (copy v1, **for owner review**), `RetryPolicy` (`app/providers/http.py`). S5 adds `check_input`/`check_output` and the other fixed kinds | The poisoned-turn reply must go through the seal | owner (S4 review) |
| 2026-10-27 | **Layering:** `store` may import `pipeline.parts` (only), so `enqueue(delivery: ReplyDelivery)` keeps the compile-time seal. The recorder and the outcome → row mapping live in `worker` (store can't import `pipeline.steps`); `StepRecorder`/`TurnObserver` protocols live in `app/pipeline/step_models.py` (ports can't import the pipeline) | store/pipeline rule conflicted with s07's seal | owner (S4 review) |
| 2026-10-27 | Poisoned = **any** picked message at `MAX_TURN_ATTEMPTS`. Retry times come from the database clock (`now() + delay`), the one claims compare against. `apply_status_update` (s03 §4.8) uses the pure `next_delivery_status` under a row lock, and the webhook applies status webhooks from S4 (503 on a store failure). `outbox_messages.audio_blob_id`/`image_blob_id` have no FK until S6 creates `media_blobs`; AUDIO/IMAGE parts fail `media_not_loadable` until then (ReplyPartsBuilder.build never produces them before S6) | Implementation choices the doc left open | owner (S4 review) |
| 2026-10-27 | **Wiring lands with S5:** the dispatcher needs `run_turn`, so `Container.dispatcher`, its start/stop in the lifespan, and the webhook's `wake(user_hash)` are added in S5. S4's exit is the integration suite (one reply, duplicates, burst, mid-turn message, crash → retry → poison, restart recovery, part order); the phone exit runs with S5 | No orchestrator exists before S5, and a placeholder one is banned | owner (S4 review) |
| 2026-10-25 | Consolidated against the foundation docs: contracts' `TurnOutcome`/`TurnWrite`/`PostTurnTask`; `WriteApplier` registry; turn status per B3; crisis `user_text` NULL (B5); stale and poisoned turns before `run_turn`; `process_user_turn`; post-turn tasks (§4.16); purge after delivery and sweep (§4.15, B4); template parts skip the 24h check; `sending_since`; web `mark_sent` notify; `NudgeLoop` hosted; context loads learners, open activity, `is_session_start`, `active_learner` | Resolve conflicts between the step docs and add the parent journey | owner (A1–A5, B1–B12) |
| 2026-10-26 | Context loads `child_session` and sets `speaker`; housekeeping expires child sessions past `CHILD_SESSION_MAX_MINUTES` and queues the parent summary | Owner decision C13 | owner |
| 2026-10-30 | **The loop wakes when a burst window ends** (`TurnLoop._until_next_claim`): after a claim finds nothing, it waits until the next pending message is claimable (`until_claimable`), at least 200 ms and at most the poll interval, instead of always the poll interval. The 1 s debounce now costs up to 1 s, as §4.3 says | Timed on the demo: every button tap took 2.1 s, even a fixed reply with no model call. The ingress wake came inside the burst window, the claim found nothing, and the loop slept the 2 s poll | owner |
