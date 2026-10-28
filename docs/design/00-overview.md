# 00 — System overview

Read this first. It's the whole system on one page. Details live in the step docs.

> **Hackathon build:** the MVP is the parent journey, run as a single process with a simplified
> dispatcher, direct localisation and a polling web demo. See [mvp-scope.md](mvp-scope.md). This
> overview describes the full design, which the MVP grows into in Phase 2.

## 1. What the system does

Marg.ai follows a **learner** from early childhood to their first career decisions, through the
adults around them and, later, the learner themself. Everyone uses **WhatsApp** (or the **web
demo**), by voice note or text, in Hindi, Hinglish or English, and gets a voice note plus text back.

| Who's messaging | Learner | What they get | Doc |
|---|---|---|---|
| **Parent** of a child aged 3–8 | their child | a daily two-minute *khoj* (discovery) using the world around them, and serve-and-return replies to what the child said | s10b |
| **Teacher** | their class (aggregate only) | *exposure bridges*: today's chapter mapped to real-world fields, plus a classroom activity | s10 |
| **Student** (classes 6–12) | themself | a *mentor* grounded in official sources, and a stored *roadmap* | s12 |

Every turn adds to a measurable **trajectory**: curiosity signals for young children, aspiration
signals for students, keyed by learner so one child's record can span the years (s13).

## 2. Processes and external systems

```
                    ┌──────────────────────── Meta ────────────────────────┐
  WhatsApp user ───▶│ WhatsApp Cloud API          Model API (api.meta.ai)  │
                    └───────┬────────▲──────────────────▲──────────────────┘
                 webhook    │        │ send / media /   │ Muse Spark, Voice Transcribe
                 (signed)   ▼        │ templates        │
  Browser ──HTTPS──▶ ┌────────────┐  │           ┌──────┴─────┐      ┌──────────────────┐
  (/demo, SSE)       │  api       │  │           │  worker    │─────▶│ ml-sidecar       │
                     │  FastAPI   │  └───────────│  (asyncio) │      │ (Modal, CPU)     │
                     │            │              │            │      │ MMS-TTS, e5      │
                     └─────┬──────┘              └─────┬──────┘      └──────────────────┘
                           │      ┌──────────────┐     │             ┌──────────────────┐
                           └─────▶│ PostgreSQL   │◀────┘────────────▶│ Llama Guard 4    │
                                  │ + pgvector   │                   │ (hosted partner) │
                                  └──────────────┘                   └──────────────────┘
```

| Process | Entry point | Does | Never does |
|---|---|---|---|
| **api** | `uvicorn app.main:create_app --factory` | Verify, parse, write `inbox_messages`, return quickly. Serve `/demo`, its SSE stream, `/dashboard`, `/status`, health. | Call a model. Process a turn. |
| **worker** | `python -m app.worker` (package `app/worker/`) | Turn loop (lease a user, run the pipeline, finalize), outbox loop (deliver), post-turn tasks, **nudge loop** (daily parent templates), maintenance (leases, purges, retention). | Serve HTTP. |
| **ml-sidecar** | FastAPI service in `services/ml_sidecar/` (its own Python 3.12 environment) | `/tts` (Kokoro-82M, Hindi and English), `/embed` (multilingual-e5-small). | Hold state or touch the database. |
| **PostgreSQL** | Neon (deployed), docker compose (local) | System of record, work queue (`SKIP LOCKED` + leases), notifications (`LISTEN/NOTIFY`), vectors (pgvector). | — |

There's no Redis, no broker and no object store. Postgres covers all three at MVP scale.
Tables and notification channels are in [data-model.md](data-model.md).

## 3. The life of one message

```
 ① INGRESS (api, under 1 s)              ② TURN (worker, a few seconds)             ③ DELIVERY (worker)
 ───────────────────────────            ────────────────────────────────           ───────────────────
 authenticate the sender                lease the user (one turn at a time,        claim pending parts in order
   WhatsApp: X-Hub-Signature-256          1 s debounce combines a burst)           send through the channel
   Web: signed session cookie           collect pending inbox rows → one turn        WhatsApp: Graph API
 parse → InboundMessage                 acknowledge (read receipt + typing)          Web: NOTIFY → SSE
 upsert users (hash + encrypted addr)   run_turn: the pipeline steps (§4)          record provider id
 INSERT inbox_messages                    every step → turn_steps + NOTIFY         status webhooks update
   ON CONFLICT DO NOTHING               FINALIZE (one transaction):                  delivered / read
 NOTIFY inbox_new                         lease check, TurnWrites, outbox parts,   purge the user if this
 WhatsApp → 200                           turn completed, inbox done, release        was a confirmed deletion
 Web → 202 {message_id}; progress       POST-TURN (own transactions, after reply):
   arrives on the session's SSE stream    extract signals, update memory
```

- **Everything is asynchronous.** WhatsApp forces it: the webhook response can't carry a reply.
  The web channel uses the same path, so there's one pipeline, one set of failure semantics, and
  live progress over one SSE stream per browser session (s14).
- **Idempotency** comes from unique constraints: `inbox_messages (channel, external_id)` and
  `outbox_messages (turn_id, part_no)`.
- **All-or-nothing turns.** Layers never write to the database. They return `TurnWrite`s, applied
  in the finalize transaction with the outbox rows. A turn that loses its lease, or whose reply is
  blocked by safety, leaves no partial state (s04, contracts §2.4).
- **Failure:** a step returns `StepFailure`, never raises into the void. The orchestrator maps it
  to a fixed fallback reply and records it (s05). Safety fails closed (s07). A turn that runs to
  the end is `completed` even with a fallback reply; `failed` means it crashed or was abandoned.
- **Proactive messages** (parent nudges) are `NUDGE` turns created by the nudge loop. They have no
  inbound message and one Meta-approved `TEMPLATE` part, and go through the same sealed outbox path (s10b §4.11).

## 4. Pipeline steps (inside `run_turn`)

| # | `StepName` | Owner doc | Input → output | Fallback when it fails |
|---|---|---|---|---|
| 1 | `fetch_media` | s06 | `MediaRef` → `AudioClip` | `REPEAT_PLEASE` |
| 2 | `transcribe` | s06 | `AudioClip` → WAV → `Transcript` | `REPEAT_PLEASE` (silent/short), `TOO_LONG`, `UNSUPPORTED_MEDIA` |
| 3 | `safety_in` ‖ `route` | s07 / s05, s08 | user text → `SafetyVerdict` ‖ `RouteDecision` (run together; the route result is discarded unless safety allows) | safety: `HOLDING` (fail closed; the crisis lexicon still decides). Route: `TRY_AGAIN_LATER` |
| 4 | `generate` | s08, s10, s10b, s12, s13 | route + context → `CanonicalReply` (+ `TurnWrite`s) | `TRY_AGAIN_LATER` |
| 5 | `translate` | s09 | `CanonicalReply` (English) → `LocalisedReply` | canonical as-is if already in the user's register, else `TRY_AGAIN_LATER` |
| 6 | `safety_out` ‖ `synthesize` | s07 / s06 | `LocalisedReply` → `SafeReply` ‖ audio (speculative: used only if safety passes) | safety: `HOLDING`. Synthesis: text-only reply (degraded) |
| 7 | `enqueue_reply` | s04 | `ReplyDelivery` → handed to finalize | turn fails, inbox rows retried |

**Post-turn tasks** (after finalize, off the critical path, own transactions, never affect the reply):
`extract_signals` (s13: aspiration signals for students, curiosity signals for parent reports) and
`update_memory` (s12).

Steps 1–2 run only for audio. Crisis verdicts skip 3's route result and steps 4–5, and send the
fixed crisis text. Fixed replies (crisis, holding, repeat-please, onboarding copy, nudges) skip
the LLM and translation, pass `safety_out` through `SafetyGate.clear_fixed`, and are synthesized
to audio when the user spoke.

## 5. Code layering (enforced by `tests/unit/test_layering.py`)

```
api ──▶ pipeline ──▶ layers ──▶ domain ──▶ core.errors / core.types
 │          │           │
 │          └──▶ providers.ports (Protocols only) ◀── providers.* (adapters, the only SDK imports)
 └──▶ channels (the only code that knows payload shapes)     store (the only SQL)
```

Allowed imports, by package (s01 §4.12 has the full table):
- `domain`: `core.errors`, `core.types` only.
- `layers`: `domain`, `providers.ports`, `prompts`, `rag` (retrieval interfaces).
- `pipeline`: `domain`, `layers`, `providers.ports`, `safety`, `store`, `telemetry`.
- `safety`: `domain`, `providers.ports`, `prompts`.
- `api`: `channels`, `store`, `core`, `domain`, `telemetry`, and `pipeline` only to hand off.
- `worker`: everything except `api`.
- Composition happens in one place, `app/wiring.py`, which builds concrete adapters and injects them.

## 6. Glossary

| Term | Meaning |
|---|---|
| **Learner** | The person whose journey we track: a parent's child, or a student themself. Has an optional nickname and a birth year. |
| **Guide** | The adult messaging on a learner's behalf: a parent (or, later, a teacher). |
| **Khoj** | "Discovery": one free, two-minute activity for a parent and a child aged 3–8, from the reviewed catalogue, personalised. |
| **Serve and return** | The back-and-forth between an adult and a child that builds learning. Marg.ai's replies to parents follow it: praise the child's idea, ask one question that extends it. |
| **Nudge** | The once-a-day opt-in template that invites a parent to today's khoj. |
| **Turn** | One unit of work: every pending inbound message from one user, combined, processed once, producing one reply. A `NUDGE` turn has no inbound message. |
| **Part** | One outbound message within a turn's reply (audio, text, buttons, template), ordered by `part_no`. |
| **Lease** | A time-limited claim a worker holds on a user while processing their turn. |
| **TurnWrite** | A state change a layer returns instead of writing; applied in the finalize transaction with the outbox rows. |
| **Fixed reply** | Human-written text sent without an LLM (crisis, holding, repeat-please, onboarding, nudge). Versioned, in every language. |
| **Register** | The language form of a reply: Devanagari Hindi, romanised Hinglish, or English. |
| **Exposure bridge** | Teacher-mode output: a chapter → three real-world fields, an activity, careers. |
| **Canonical reply** | What a layer produces before translation: correct content, in English. |
| **Localised reply** | The translated result: `text` for the screen, `spoken_text` for the ear. |
| **Curiosity signals** | What one parent report says the child engaged with: domains, engagement 0–3, whether the child asked their own question. |
| **Aspiration signals** | What one student turn says about their ambitions: fields, specificity 0–4, constraints. |
| **Trajectory** | How a learner's signals change over time: breadth, engagement or specificity slope, return rate. |
| **user_hash** | `HMAC-SHA256(USER_HASH_SALT, "<channel>:<address>")`, hex. The only user identifier outside the `users` table. |
