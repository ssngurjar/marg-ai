# Marg.ai: architecture and debugging guide

A working map of the running system: what runs, how one message travels through it, where each
feature lives, and how to find out why something didn't happen. Read it next to the code.
Design intent lives in `docs/design/`; this guide describes what is built (as of 2026-10-27,
commit `a785b2d`). Every module and class is listed in [`docs/code-map.md`](../code-map.md).

---

## 1. The picture in one minute

```
 Parent's phone ──WhatsApp──▶ Meta Cloud API ──webhook──┐
 Browser (/demo) ─────────────────────────────JSON──────┤
                                                        ▼
                ┌──────────────── one Python process (uvicorn) ─────────────────┐
                │  api/      verify, parse, insert into inbox, wake the user    │
                │  worker/   dispatcher → processor → orchestrator → finalize   │
                │            → deliverer (send parts) → post-turn (signals, card)│
                │            + maintenance pass every 30 s (retries, retention, │
                │              purges, expired media, child sessions, nudges)   │
                └───────────────┬──────────────────────────────┬───────────────┘
                                │                              │
                      Postgres (docker)               external providers
                      inbox, turns, steps,            Muse Spark 1.3 (Model API)
                      outbox, users, learners,        Muse Spark Open (Baseten)
                      activities, sessions,           Muse Voice Transcribe, Muse Image
                      signals, media, nudges          Llama Guard 4 (DeepInfra)
                                                      voice server (marg-ai-tts, local)
```

- **One process** (exception E1, `docs/design/mvp-scope.md` §4.1): the API and the worker share
  one event loop. There's no separate worker process and no queue service. The inbox and outbox
  tables are the queue.
- **Nothing calls a model inside the webhook.** The webhook stores the message and returns in
  under a second; the turn runs in the background.
- **Every reply is sealed by safety.** A `SafeReply` can only be created by `SafetyGate`, and the
  outbox accepts only a `ReplyDelivery` built from one (`pipeline/reply_parts_builder.py`).

---

## 2. Running everything locally

Order matters: database, migrations, voice server, API, tunnel.

| # | What | Command | Check |
|---|---|---|---|
| 1 | Postgres | `docker compose up -d postgres` | `docker compose ps` shows healthy |
| 2 | Migrations | `make migrate` | `.venv/bin/alembic current` → `s14_web_demo (head)` |
| 3 | Voice server (other folder) | see §2.1 | `curl -s 127.0.0.1:8100/healthz` → `"engine":"mms"` |
| 4 | API + worker | `.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log` | `curl -s 127.0.0.1:8000/readyz` → `ready`, database and ffmpeg `ok` |
| 5 | Public tunnel | `scripts/dev_tunnel.sh 8000` | prints a `https://…trycloudflare.com` URL |
| 6 | WhatsApp callback | point Meta at `<tunnel>/webhooks/whatsapp` (new URL on every tunnel start) | send "Hi" from the phone |
| 7 | Web demo | open `<tunnel>/demo` (or `http://127.0.0.1:8000/demo`) | the page greets you |

**From VS Code:** Run and Debug → **"Marg.ai: API + voice server"** starts steps 1, 3 and 4 with
breakpoints (`.vscode/launch.json`; Postgres comes up first through `.vscode/tasks.json`). Run the
tunnel with Terminal → Run Task → "tunnel: public URL for WhatsApp and /demo".

Logs: uvicorn prints JSON lines (structlog) to stdout. Redirect them to a file when running in
the background: `… >> /tmp/marg-app.log 2>&1`.

### 2.1 The voice server (`/Users/santramgurjar/personal/marg-ai-tts`)

A separate project (FastAPI). It loads **one** engine, the one `TTS_ENGINE` names:

```sh
cd ../marg-ai-tts
TTS_ENGINE=mms SIDECAR_TOKEN=<same as marg-ai .env> HF_TOKEN=<from .env> \
  .venv/bin/uvicorn server.tts_server:app --host 127.0.0.1 --port 8100 --no-access-log
```

- `mms` (MMS-TTS on the CPU): local testing only. Licence CC-BY-NC, never in the submission.
- `indic_parler` (Indic Parler-TTS): demo and final tests, needs a GPU host (too slow on the Mac).
- marg-ai's `.env` must have the same `TTS_ENGINE`, plus `SIDECAR_BASE_URL` and `SIDECAR_TOKEN`.
  A mismatch returns 422 and every reply goes text-only (`synthesize` FAILED in the trace).

### 2.2 Settings that change behaviour (`.env`)

| Setting | Effect |
|---|---|
| `TTS_ENGINE`, `SIDECAR_BASE_URL`, `SIDECAR_TOKEN` | which voice the replies use, and where |
| `REPLY_AUDIO_FOR_TEXT_INPUT` | `true`: typed messages also get a voice reply (default: only voice notes do) |
| `CHILD_TALK_ENABLED` | child talk on or off; the "Main bachcha hoon" button disappears when off |
| `NUDGES_ENABLED` | daily khoj messages; **off** until Meta approves the templates |
| `KHOJ_CARD_ENABLED` | illustrated cards after a good report |
| `SAFETY_POLICY_MODEL_ENABLED` | the Muse Spark safety check that runs with Llama Guard |
| `TIMEOUT_*` | per-step limits; `TURN_BUDGET_S` (25 s) caps the whole turn |
| `DAILY_COST_CAP_USD`, `DEMO_*` | web demo limits |

All settings, with defaults, are in `app/core/config.py` and `.env.example`.

---

## 3. Layers: who may import whom

Enforced by `tests/unit/test_layering.py` on every test run (`tests/support/layering.py`).

```
api/        HTTP only: verify, parse, insert, project. No domain logic.
pipeline/   the orchestrator and router. Depends on ports (protocols), never on SDKs.
layers/     the generative features: onboarding, journey, curiosity moment, child talk, cards.
safety/     the gate: crisis words, Llama Guard, the Muse Spark policy check, child rules.
domain/     pure models and rules (state machine, chooser, schedules, matchers). No I/O.
providers/  adapters behind providers/ports.py: the only place an SDK is imported.
channels/   the only place that knows a WhatsApp or web payload shape.
store/      the only place SQL lives (repositories, one per table or aggregate).
audio/      ffmpeg conversions, TTS text preparation.
telemetry/  curiosity signal extraction.
constants/  reviewed copy (fixed replies, crisis texts, word lists) and external limits.
worker/     the dispatcher, processor, deliverer, post-turn runner, nudge and card senders.
wiring.py   the only place concrete classes are built and connected.
```

When you read a feature, start from `app/wiring.py`: it shows every object and what it gets.

---

## 4. One message, end to end

### 4.1 In

| Step | Where | What happens |
|---|---|---|
| 1 | `api/routers/whatsapp_webhook.py` | checks the body size and Meta's signature (`channels/whatsapp/webhook_signature.py`) |
| 2 | `channels/whatsapp/webhook_parser.py` | turns Meta's JSON into `InboundMessage`s (text, audio, image, button) |
| 3 | `api/whatsapp_webhook_ingestor.py` | `InboxRepository.save` (deduplicated on the WhatsApp message id), then `dispatcher.wake(user)` |
| 3w | `api/routers/demo.py` → `api/web_demo_ingestor.py` | the web: cookie → visitor, origin check, rate limits, cost cap, `WebMessageParser`, inbox |

### 4.2 The turn (`worker/`)

| Step | Where | What happens |
|---|---|---|
| 4 | `turn_dispatcher.py` | one task per user; waits `TURN_DEBOUNCE_MS` so several quick messages become one turn |
| 5 | `turn_processor.py` | claims the user's pending messages into a `turns` row, loads the `TurnContext` (profile, learners, open activity, child session), acknowledges (blue ticks, typing) |
| 6 | `pipeline/orchestrator.py` | runs the steps (§5) and returns a `TurnOutcome`: sealed delivery, writes, post-turn tasks |
| 7 | `store/repositories/turn_repository.py` `finalize` | **one transaction**: the turn row, every `TurnWrite`, the outbox parts, the inbox rows marked done |
| 8 | `reply_deliverer.py` | sends each part in order through the channel's sender; retries; the 24-hour window check (templates exempt) |
| 9 | `post_turn_runner.py` | in the background: curiosity signals, then a khoj card |
| 10 | maintenance (every 30 s) | resend due parts, wake users with pending messages, retention, purges, expired media, abandoned child sessions, nudges |

A crash during 6 puts the messages back with backoff (`turn_crashed`); after
`MAX_TURN_ATTEMPTS` they're "poisoned" and get a fixed reply (`turn_poisoned`).

---

## 5. Inside the orchestrator

`pipeline/orchestrator.py`, class `_Turn`. Each step writes one `turn_steps` row (§7.2).

| Step (`StepName`) | What | If it fails |
|---|---|---|
| `fetch_media` | download the voice note (WhatsApp or web), convert to 16 kHz WAV, measure speech | too big or unreadable → UNSUPPORTED_MEDIA; otherwise REPEAT_PLEASE |
| `transcribe` | silence/length check, then Muse Voice Transcribe | too short or silent or "umm" → REPEAT_PLEASE; over 3 min → TOO_LONG; down → REPEAT_PLEASE |
| `route` | `TurnRouter.decide`: deterministic rules, no model | — |
| `fetch_image` | a photo, only with a khoj open (WhatsApp download or the web's `inbound_photo` blob), memory only | the photo is dropped; the report goes on without it |
| `analyze_image` | SAM 3.1: first the person check (`person_check=pass/reject`), then counting the activity's `photo_count_phrases` (`stone=5`) | anyone in it → PHOTO_HAS_PERSON; SAM down → photo dropped |
| `safety_in` (photo) | Llama Guard on the image, while SAM counts (`photo decision=…`) | flagged → REFUSE; down → photo dropped (no backup for images) |
| `safety_in` | crisis words first, then Llama Guard ‖ Muse Spark policy | both down → HOLDING (fail closed) |
| `generate` | the routed layer (runs **in parallel** with `safety_in`; discarded unless it allows) | TRY_AGAIN_LATER |
| `translate` | always SKIPPED: layers write in the user's language (C3c) | — |
| `safety_out` | d8 and child rules, d7 hazards, then Llama Guard (+ second opinion) on text **and spoken text** | blocked → REFUSE; both down → HOLDING |
| `synthesize` | only when the user spoke (or the setting): voice server → OGG voice note → `media_blobs` | text-only reply, turn DEGRADED |

Post-turn steps: `extract_signals`, `make_card` (recorded on the same turn).

### 5.1 Routes (`pipeline/turn_router.py`, in order)

1. An open child session → `CHILD_TALK` (nothing a child sends reaches deletion or settings).
2. A deletion phrase ("mera data hatao") → `DATA_DELETION`.
3. Not yet `ACTIVE` (consent, role, child) → `ONBOARDING`.
4. A parent's `kid:start` or "Main Munni hoon" → `CHILD_TALK` (consent and cooldown checked in the layer).
5. `onb:` buttons → `ONBOARDING`; `jrn:` and `nudge:` buttons → `JOURNEY`; any other button → REPEAT_PLEASE.
6. Teachers → `ONBOARDING` (the invite); a language name → `ONBOARDING`; "ek aur bachcha" → `ONBOARDING`.
7. A blank message → REPEAT_PLEASE. Otherwise → `JOURNEY`.

The turn row's `route` column and the `route` step's `detail` tell you which rule fired.

---

## 6. Where each feature lives

| Feature | Main code | Prompts / copy | Tables |
|---|---|---|---|
| Onboarding (consent, parent/teacher, child) | `layers/onboarding_layer.py`, `domain/rules/conversation_machine.py` | `prompts/profile_extraction.md.j2`, `constants/onboarding_copy.py` | `users`, `consent_events`, `learners` |
| Delete my data | router rule 2 → onboarding; `UserRepository.purge_user` after the reply is delivered | — | every table (cascade) |
| Today's khoj (flow A) | `layers/journey_layer.py` `_today`, `domain/rules/activity_chooser.py`, `content/activities/*.yaml` | `activity_personalise.md.j2`, `constants/journey_copy.py` | `learner_activities` |
| Report back (flow B) | `journey_layer.py` `_reflect` | `parent_reflection.md.j2` (Muse Spark Open, falls back to Spark) | `learner_activities` |
| Parent question (flow D) | `layers/parent_question_layer.py` | `parent_answer.md.j2` | — |
| Curiosity moment (C11) | `layers/curiosity_moment_layer.py`, `domain/rules/child_question_detector.py` | `curiosity_moment.md.j2` | — |
| Child talk (C13) | `layers/child_talk_layer.py`, `domain/rules/child_session_rules.py`, `orchestrator._child_talk` | `child_talk.md.j2`, `constants/child_talk_copy.py`, `constants/child_safety_words.py` | `child_sessions` |
| Nudges (flow E/F) | `journey_layer._nudge_settings`, `worker/nudge_sender.py`, `domain/rules/nudge_schedule.py` | `journey_copy.py` (NUDGE_*), `fixed_replies.py` (NUDGE) | `nudge_subscriptions` |
| Curiosity signals (S13) | `telemetry/curiosity_signal_extractor.py`, `worker/post_turn_runner.py`, `domain/rules/curiosity_trajectory.py` | `curiosity_extract.md.j2` (Muse Spark Open) | `curiosity_signals` |
| Photos (C7) | `orchestrator._photo_for` / `_look`, `providers/image/sam_image_segmenter.py`, `safety_gate.check_photo` | `parent_reflection.md.j2` (counts only), `constants/photo_check.py`, `photo_count_phrases` in each activity YAML | `learner_activities.photo_findings`, `media_blobs` (`inbound_photo`, ≤ 10 min) |
| Khoj card (C6) | `layers/khoj_card_maker.py`, `worker/khoj_card_sender.py`, `providers/image/` | `khoj_card_text.md.j2`, `constants/khoj_card_style.py` | `media_blobs`, `learner_activities.card_blob_id` |
| Voice in/out (S6) | `orchestrator._hear` / `_with_voice`, `audio/`, `providers/speech/` | `audio/tts_text_preparer.py` (what the voice may say) | `media_blobs` |
| Safety | `safety/safety_gate.py`, `safety/domain_policy.py`, `domain/rules/crisis_phrase_matcher.py` | `minor_policy.md.j2`, `reply_policy.md.j2`, `constants/crisis_*.py`, `child_hazards.py` | — |
| Web demo (S14) | `api/routers/demo.py`, `api/web_demo_ingestor.py`, `channels/web/`, `app/static/demo/` | — | `rate_limit_counters`, `inbox_messages.media_blob_id` |

Fixed replies (never generated): `constants/fixed_replies.py` and `constants/crisis_replies.py`,
looked up by `pipeline/fixed_reply_service.py`. Helpline numbers are copied from official pages,
with the source in the file.

---

## 7. Debugging toolbox

### 7.1 Logs

JSON lines on stdout. They never contain phone numbers, message text or replies, only ids,
hashes and fixed words (`core/logging.py` redacts the rest). Useful events:

| Event | Means |
|---|---|
| `dispatcher_recovered` | startup finished; messages requeued, parts reset |
| `turn_crashed` / `turn_poisoned` | a bug raised inside a turn; after the attempts limit, a fixed reply |
| `turn_lease_lost` | the user's state changed under a turn; it's rerun |
| `delivery_failed` (with `error`) | a part couldn't be sent: `window_closed`, `media_expired`, a Graph error code |
| `llama_guard_down`, `second_opinion_failed` | safety fell back to the Muse Spark check |
| `open_model_fallback` | Muse Spark Open failed or was slow; Spark 1.3 answered |
| `curiosity_extraction_failed`, `khoj_card_failed` | post-turn work failed (the reply was already sent) |
| `maintenance_failed` | the 30-second pass raised (often a missing migration) |
| `webhook_unparseable`, `webhook_store_failed` | a Meta payload we couldn't read or store |

Follow one turn: `grep <turn_id> /tmp/marg-app.log`.

### 7.1b Numbers at a glance: /status and the dashboard

- `GET /status` (public): turns, the share served well, how long parents wait for a reply
  (p50/p95, from the `turn_metrics` view), every step's p50/p95 and OK rate, journey counts.
  `/status.json` is the same as JSON.
- `marg admin-link` (`.venv/bin/python -m app.cli admin-link [--base-url <tunnel URL>]`)
  prints a 15-minute link. Opening it sets a 2-hour cookie; then `/dashboard` shows the young
  learners, and `/status` adds today's cost, crisis replies and failures by step.
- The admin view shows counts from a single child (`K_ANONYMITY_FLOOR_ADMIN=1`); don't film it
  or share a screenshot without blurring (owner, 2026-10-28).
- A `503` page means the database query failed: look for `status_unavailable` or
  `dashboard_unavailable` in the logs (often a missing migration: `make migrate`).

### 7.2 The database: the best debugger

Open a shell: `docker compose exec postgres psql -U marg marg`.

**The last turns, with every step:**

```sql
SELECT t.started_at AT TIME ZONE 'Asia/Kolkata' AS ist, t.status, t.route, t.fixed_reply_kind,
       t.failure_step, t.failure_kind, t.id
FROM turns t ORDER BY t.started_at DESC LIMIT 10;

SELECT step, outcome, duration_ms, detail, failure_kind, provider, model, cost_usd
FROM turn_steps WHERE turn_id = '<turn id>' ORDER BY id;
```

`detail` is fixed vocabulary that explains a decision: the router's rule, `decision=allow
guard_flagged=s2` (Llama Guard flagged, the second opinion cleared it), `guard=down`,
`duration_ms=… voiced_ms=…` (voice), `catalogue_fallback=…` (the reviewed text went out),
`source=parent_report engagement=2` (signals), `engagement=1` / `one card a day` (no card).

**What was sent, and did it arrive?**

```sql
SELECT part_no, kind, status, last_error, attempts, sent_at, delivered_at, read_at
FROM outbox_messages WHERE turn_id = '<turn id>' ORDER BY part_no;
```

`status` goes `pending → sending → sent → delivered → read` (the last two from Meta's status
webhooks). `failed` with `last_error` tells you why.

**Messages waiting or stuck:**

```sql
SELECT channel, kind, status, attempts, available_at, received_at
FROM inbox_messages WHERE status <> 'done' ORDER BY received_at DESC;
```

**A user's state** (users are identified by `user_hash`; take it from a turn):

```sql
SELECT state, role, language, consented_at, pending_question, last_inbound_at
FROM users WHERE user_hash = '<hash>';
SELECT id, nickname, birth_year, child_talk_consented_at FROM learners WHERE owner_user_hash = '<hash>';
SELECT activity_id, status, offered_at, child_response_summary, card_blob_id
FROM learner_activities WHERE learner_id = '<learner id>' ORDER BY offered_at DESC;
```

**Feature tables:**

```sql
SELECT learner_id, started_at, ended_at, turns_count, topics, end_reason FROM child_sessions ORDER BY started_at DESC;
SELECT user_hash, enabled, local_time, next_due_at, last_sent_at FROM nudge_subscriptions;
SELECT source, domains, engagement, child_asked_question, extracted_at FROM curiosity_signals ORDER BY id DESC;
SELECT purpose, mime_type, size_bytes, created_at, expires_at FROM media_blobs ORDER BY created_at DESC;
```

**Cost today (India day):**

```sql
SELECT step, provider, model, count(*), sum(cost_usd)
FROM turn_steps WHERE started_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata'
GROUP BY 1, 2, 3 ORDER BY 5 DESC;
```

### 7.3 Health and readiness

- `GET /healthz`: the process is up. `GET /readyz`: database (critical) and ffmpeg (not
  critical: voice degrades to text without it).
- Voice server: `GET 127.0.0.1:8100/healthz` shows the engine and models loaded.

### 7.4 Tests

| Command | Runs |
|---|---|
| `make check` | format, lint, type check, unit tests: the CLAUDE.md §2 loop |
| `.venv/bin/pytest tests/unit/pipeline/test_orchestrator_voice.py -q` | one file |
| `.venv/bin/pytest -k child_talk -q` | tests whose names match |
| `make test-db-up` then `make test-int` | migrations up, down and up, `alembic check`, then integration tests on the test database (port 55432) |

Unit tests never call a real model or service (fakes in `tests/fakes/`).
`tests/integration/test_real_pipeline.py` runs the real dispatcher, orchestrator and Postgres with
fake models: the best place to reproduce a whole conversation.

### 7.5 Trying a prompt live

Each prompt was checked with a small script against the real model (synthetic messages only),
the pattern being: load settings, build the adapter and `prompt_registry(settings)` from
`app/wiring.py`, call the layer, print the reply. The scripts used on 2026-10-27 are in the
session's scratchpad, not the repo; recreate one when a prompt changes (CLAUDE.md §10).

---

## 8. Symptom → where to look

| Symptom | First check | Usual cause |
|---|---|---|
| No reply at all | `inbox_messages` for the message; the logs for `webhook_*` | tunnel URL changed and Meta still posts to the old one; signature fails (`401`); app not running |
| A reply, but "try again later" | the turn's `failure_step` / `failure_kind` | a model timed out or the turn budget ran out |
| "Abhi aapka message dekhne mein dikkat…" (HOLDING) | `safety_in` / `safety_out` rows FAILED | Llama Guard **and** the Muse Spark check both failed (fail closed, by design) |
| A refusal for a harmless question | `safety_in` `detail` categories | Llama Guard flag confirmed by the policy check; tune the prompt or word list, never bypass |
| The reviewed activity text instead of the personalised one | `generate` `detail` `catalogue_fallback=…` | personalisation failed its checks twice; `safety_out` blocked it (d7) |
| Voice note → "samajh nahi aaya" | `fetch_media` detail (`voiced_ms`), `transcribe` FAILED kind | silent or under 0.7 s; speech-to-text down; only "umm" |
| Photo → "koi insaan dikh raha hai" | `analyze_image` detail `person_check=reject` | anyone in the frame, a hand too (by design, owner 2026-10-28) |
| Photo → "Photo ke liye shukriya!…" | `analyze_image` SKIPPED `photo_not_needed` | no khoj open (none offered, already reported, or older than 48 h) |
| A photo report with no number in the reply | `fetch_image` / `analyze_image` / `safety_in` FAILED `photo_dropped`, `counts_dropped` | a failure dropped the photo; or the activity counts nothing |
| No voice reply | `synthesize` row | voice server down or the wrong engine (422); spoken text not speakable (`TtsTextInvalid`, e.g. Latin letters for the Hindi voice) |
| Reply in English for a Hinglish speaker | the turn's `reply_register`, the transcript | short or mostly-Roman text detected as English (open owner question) |
| No khoj card after a report | `make_card` row `detail` | engagement under 2, a card already today, safety blocked, `KHOJ_CARD_ENABLED=false`, the window closed |
| "Main bachcha hoon" does nothing | `route` row; `learners.child_talk_consented_at` | no consent (the parent gets the switch-on message), the 30-minute cooldown, `CHILD_TALK_ENABLED=false` |
| Child stuck in child talk | `child_sessions` with `ended_at IS NULL` | the child left without "bye"; maintenance closes it after 10 minutes |
| No daily nudge | `nudge_subscriptions.next_due_at`, `NUDGES_ENABLED` | off until templates are approved; quiet hours; a khoj already today; the daily cap |
| `delivery_failed window_closed` | `users.last_inbound_at` | the parent's last message was over 24 h ago; only templates can be sent |
| `delivery_failed media_expired` | `media_blobs` | the audio or card expired (24 h / 7 days) before sending |
| `maintenance_failed` every 30 s | the exception in the log | usually a missing migration: `make migrate` |
| Web demo `401 no_session` | the browser cookie | cookie cleared or `SESSION_SIGNING_KEY` changed: reload the page |
| Web demo `403 bad_origin` | the request's Origin vs Host | the page was opened from a different address than it posts to |
| Web demo `429` / `503` | `rate_limit_counters`; today's web cost | hourly limits, or `DAILY_COST_CAP_USD` reached |

---

## 9. What must never happen (the invariants to check in review)

- Nothing reaches the outbox without `safety_out` (`SafeReply` and `ReplyDelivery` are sealed).
- A safety outage never lets generated text through: HOLDING instead.
- Crisis replies are fixed text with official helpline numbers; after a child's abuse
  disclosure the parent is told nothing.
- Logs never contain phone numbers, transcripts or replies.
- WhatsApp voice notes are never stored; web voice notes are deleted once heard; reply audio
  lasts 24 hours, cards 7 days.
- "Delete my data" removes the user from every table (`test_real_pipeline` checks each one).
- The image prompt never contains the child's name or the parent's words; the reflection never
  sees a photo (photos are not built yet).

---

## 10. Not built yet

- The dashboard's student section and teacher links (they come with S11/S12 and S10).
- The web consent text variant, the teacher exposure layer (S10), RAG and mentor (S11, S12),
  the eval scorecard (S15).

Pending decisions and everything awaiting review: `docs/reviews/owner-review-pending.md`.
