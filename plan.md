# Marg.ai — Build Plan (Meta Global AI Developer Hackathon, Indie Track)

> Status: **draft v1**, written 2026-10-24, before kickoff. Revisit at the end of every build day.
> Engineering rules are in [CLAUDE.md](CLAUDE.md). This file covers *what* gets built and *when*.

---

## 0. What the hackathon rewards (researched 2026-10-24)

Sources: <https://dev.meta.ai/events/global-hackathon>, <https://cerebralvalley.ai/e/meta-ai-developer-hackathon>,
<https://dev.meta.ai/docs/models>, <https://dev.meta.ai/docs/pricing-rate-limits>.

| Fact | Value | What it means for us |
|---|---|---|
| Indie track judging | **"creativity, technical ambition, and whether it works"** | Three axes, no published weights. Every feature has to help at least one of them (§2). |
| Prize pool | **$1,000,000 total across both tracks** (not $400k). No per-track split published | — |
| Theme fit | "Build for Your World" — a problem you know firsthand | Marg.ai fits well. Lead the story with the rural exposure gap. |
| Kickoff | **Mon Oct 26, 9:00 AM ET = 18:30 IST** | Day 1 starts in the evening IST |
| Submission deadline | **Wed Nov 4, 9:00 PM ET = Thu Nov 5, 07:30 IST** (US DST ends Nov 1, so this is EST) | Plan to submit by **Nov 4, 23:00 IST**. Don't use the overnight buffer. |
| Judging / finals | Nov 4–8 judging, Nov 9 closing ceremony with live finals | Judges must be able to **try it themselves**. Plan: a real WhatsApp number anyone can message (it works without business verification, see §4.1), with the public web demo (§4.7) as the guaranteed path. |
| Official rules | "To be published before the hackathon begins" | **Read them on Oct 26.** Check: whether code written before kickoff counts, submission format (video length, repo visibility), required models. |
| Partner credits | Baseten $100 (+2M TPM), Modal $100, Fireworks $25 | Use these for open-weights models (Llama Guard, TTS, embeddings) |

### Meta Model API — what's actually available

| Need | Model | Notes |
|---|---|---|
| Reasoning, curriculum mapping, mentoring, vernacular adaptation | `muse-spark-1.3` (text), `muse-spark-1.2` (when audio input is used) | OpenAI-compatible at `https://api.meta.ai/v1`. 1M context, tool calling, **structured output**, search grounding. $1.25 / $4.25 per 1M tokens. 3,000 RPM. |
| Speech-to-text | `muse-voice-transcribe-1.0` | `POST /v1/asr/transcribe`, $0.18/hr. 25 languages with code-switching, but **Hindi is not confirmed** and accepted audio formats aren't documented. Day-1 spike. |
| Cheap high-volume calls | `muse-spark-1.x-contributor` | 10–20× cheaper, but Meta trains on the content. **Never use it for student data** (minors). Fine for evals over synthetic prompts. |
| Text-to-speech | **None on Model API** | Use open-weights **Meta MMS-TTS** (`facebook/mms-tts-hin`), so the stack stays Meta. Fallback: AI4Bharat Indic Parler-TTS. |
| Safety classifier | **Not on Model API** | Use open-weights **Llama Guard 4** on a partner host (Baseten / Fireworks / Groq) or Modal. Day-1 spike. |
| Embeddings | **None on Model API** | Use an open multilingual embedding model (`intfloat/multilingual-e5-small` or BGE-M3) |
| Llama 3 | **Not on Model API** | See decision D1 |

### Decisions — all four recommendations accepted 2026-10-24

D1 Muse Spark for every generation step, translation included · D2 Modal ml-sidecar plus a hosted
Llama Guard 4 · D3 Fly.io/Railway with Neon Postgres + pgvector · D4 the dependency set in §6.
The options as originally weighed are kept below for the record. ADRs go in `docs/decisions/` on Day 1.

- **D1 — Translation layer model.** *Recommended: Muse Spark for all generation, including the
  Hinglish/Hindi adaptation.* The hackathon is about "Meta's newest models", Muse Spark is the
  strongest Meta model available, and one model means one client, one rate limit and one eval
  baseline. The translation layer stays a **separate step with its own prompt and its own eval
  rubric**, which keeps it a distinct architectural layer for the judges. Alternative: Llama 3.x
  via Fireworks/Baseten credits (adds a second provider, weaker Hindi, more latency).
- **D2 — Where TTS, embeddings and Llama Guard run.** *Recommended: one small "ml-sidecar" on
  Modal* (MMS-TTS + embeddings, scale-to-zero, $100 credits), plus Llama Guard 4 on a hosted
  partner endpoint. This keeps PyTorch out of the API image. Alternative: everything on CPU in the
  app container (simpler to deploy, but a ~1 GB image and slower cold starts).
- **D3 — App hosting.** *Recommended: Fly.io or Railway for the FastAPI app and worker, and Neon
  Postgres with pgvector.* The webhook needs a stable public HTTPS URL from Day 1.
- **D4 — Dependency approval** for the initial set in §6.

---

## 1. Product in one paragraph

A rural student or teacher sends a **WhatsApp voice note** in Hindi or Hinglish. Marg.ai
transcribes it, checks it for safety, works out what the person needs, and replies with a
**voice note plus a short text** in the same register. A **teacher** gets a lesson bridge: today's
textbook chapter mapped to real-world fields (public policy, sports science, entrepreneurship,
space), with a 5-minute classroom hook. A **student** gets a mentor that remembers their
ambitions, cites real Indian pathways (exams, scholarships, schemes) from a curated corpus, and
builds a step-by-step **roadmap**. Every turn adds to a **trajectory of intent**: a measurable
record of how a student's aspirations widen and sharpen over time.

---

## 2. Mapping features to the judging axes

| Axis | What we show | Where it lives |
|---|---|---|
| **Creativity** | Voice-first WhatsApp for low-literacy users. Curriculum-to-career "exposure bridges" for teachers. Hinglish adaptation with local cultural references (cricket, kabaddi, the mandi, the panchayat). Trajectory-of-intent visualisation. | §4.3–4.6, §4.8 |
| **Technical ambition** | Five Meta models in one pipeline: Muse Spark, Muse Voice Transcribe, Llama Guard 4, MMS-TTS, plus search grounding. Structured output everywhere. RAG with citations. Durable inbox/outbox processing. Safety gate on both input and output. An LLM-judge eval harness with published scores. | §3, §4, §5.4 |
| **Whether it works** | A public web simulator running the same pipeline. A live WhatsApp number on the demo video. Real voice notes from real students and teachers (Day 9 field test). Latency and success-rate numbers on a `/status` page. | §4.7, §7 Day 9 |

**Scope rule:** a feature that helps none of the three axes doesn't get built. A half-finished
feature costs more than a missing one, because "whether it works" is judged live.

---

## 3. Architecture

### 3.1 Request flow

```
WhatsApp Cloud API ──POST /webhooks/whatsapp──▶ [API]  verify X-Hub-Signature-256
                                                  │  parse → InboundMessage (typed)
                                                  │  INSERT inbox ON CONFLICT (wa_message_id) DO NOTHING
                                                  └─▶ 200 OK in < 1 s  (WhatsApp retries slow webhooks)

[Worker]  claim inbox row (SELECT … FOR UPDATE SKIP LOCKED)
   │
   ├─ 1. media      download audio (ogg/opus) → transcode if needed (ffmpeg)
   ├─ 2. transcribe Muse Voice Transcribe → Transcript(text, language, confidence)
   ├─ 3. safety-in  Llama Guard 4 → SafetyVerdict ── unsafe ─▶ safe refusal / crisis path
   ├─ 4. route      conversation state machine + intent classifier (Muse Spark, structured)
   ├─ 5. layer      Exposure | Mentor (RAG) | Roadmap | Onboarding
   ├─ 6. translate  Translation layer → user's register (Hindi / Hinglish / English)
   ├─ 7. safety-out Llama Guard 4 on the generated reply ── unsafe ─▶ fallback reply
   ├─ 8. synthesize MMS-TTS → wav → ogg/opus
   ├─ 9. outbox     INSERT outbox row (text + audio) → sender delivers with retries
   └─10. telemetry  TurnEvent + AspirationSignals → trajectory
```

A failed step never fails silently. Each step either produces its typed output or produces a
typed `StepFailure`. The orchestrator maps every `StepFailure` to a user-visible fallback (for
example, "I couldn't hear that clearly, could you say it again?") **and** records it in telemetry.

### 3.2 Layering (one direction only)

```
app/api/        thin HTTP: verify, parse, enqueue, project. No domain logic.
app/pipeline/   orchestrator + router. Depends on ports, never on concrete providers.
app/layers/     Exposure, Translation, Mentor, Roadmap. Prompt + typed I/O + port calls.
app/domain/     pure: models, conversation state machine, trajectory math. No I/O.
app/providers/  adapters behind ports (LLM, STT, TTS, Safety, Embeddings). The only place an SDK is imported.
app/channels/   WhatsApp / Web. The only place that knows a WhatsApp payload shape.
app/store/      Postgres repositories. The only place SQL lives.
```

`domain/` imports nothing from the other packages. `pipeline/` and `layers/` depend on
**Protocols in `app/providers/ports.py`**, so every unit test runs on fakes with no network.

### 3.3 Why a Postgres inbox and outbox, not BackgroundTasks or Redis

- WhatsApp **redelivers** webhooks. The unique `wa_message_id` makes ingestion idempotent.
- `BackgroundTasks` loses work on a restart or deploy, which would lose a student's message mid-demo.
- `SKIP LOCKED` gives a durable, concurrent work queue with no extra infrastructure. Postgres is
  already needed for users, turns, telemetry and pgvector, so this adds one table and no new service.
- The outbox separates "reply generated" from "reply delivered", so a WhatsApp send failure is
  retried rather than the whole turn being regenerated.

---

## 4. Components

### 4.1 Channels — WhatsApp Cloud API
- `GET /webhooks/whatsapp`: `hub.verify_token` challenge.
- `POST /webhooks/whatsapp`: HMAC-SHA256 check of the raw body against the app secret, using a
  constant-time compare. Reject with `401` before parsing anything.
- Typed parsing of `messages[]` (text, audio, interactive replies) and `statuses[]` (delivered or
  read, used for telemetry). Anything unknown is stored raw and logged. It is never dropped.
- Sending: text is capped at 4096 characters, so long replies are split on sentence boundaries.
  Audio is uploaded through `/media` as `audio/ogg; codecs=opus` to play as a voice note.
  Interactive buttons (max 3) handle onboarding choices.
- **24-hour customer-service window:** free-form replies only within 24h of the user's last
  message. Outside it, use a pre-approved template (needed for roadmap nudges, a stretch goal).
- Mark as read, plus a typing indicator as soon as work starts, so the user knows we heard them.
- **Number strategy (doesn't depend on business verification).** Verification only raises the
  limit on *business-initiated* messages. Without it, a portfolio can still register a real number
  (after display-name approval), reply without limit to anyone who messages first within the 24h
  window, and send 250 business-initiated conversations a day.
  1. **Primary:** a fresh prepaid SIM registered on the Cloud API with display name "Marg.ai",
     backed by a one-page public site so the display name gets approved. Judges and field testers
     can message it directly. Put the `wa.me` link and a QR code in the submission.
  2. **Fallback:** the test number (5 recipients) for the demo video, plus `/demo` for judges.
  3. Verification, if it arrives, only matters for proactive roadmap nudges at scale.
- **The pipeline is channel-agnostic** (`channels/base.py`). WhatsApp is the first channel, not
  the only one. That's what makes the distribution story in §4.10 believable.

### 4.2 Voice
- **STT:** Muse Voice Transcribe, with keyword biasing for Indian exam and scheme names (NEET,
  JEE, NMMS, Khelo India). Fallback adapter: open-weights Whisper (`large-v3-turbo`) on the
  sidecar if the Hindi spike fails.
- **TTS:** MMS-TTS Hindi on the sidecar. Romanised Hinglish is transliterated to Devanagari before
  synthesis (MMS reads script, not romanisation). This needs its own unit and property tests.
- Audio is transcoded with ffmpeg in a subprocess with a timeout. It is never shelled out through a string.
- Target latency for a voice turn: **p50 under 8 s, p95 under 15 s**, measured and shown on `/status`.

### 4.3 Exposure Layer (teachers) — Muse Spark
Input: grade, subject, chapter or topic (spoken), district (from the profile).
Output (structured `ExposureBridge`): 3 real-world fields, each with
`{field, why_it_connects, indian_role_model_or_example, five_minute_activity, careers[], local_hook}`.
The prompt is grounded in NCERT chapter names, so bridges stay tied to what the class is studying.
Search grounding can be turned on for current examples, behind a flag and a per-turn cost cap.

### 4.4 Translation Layer — Muse Spark (see D1)
A separate step after content generation:
`(canonical_reply, user_profile) → LocalisedReply{text, register, reading_level, spoken_text}`.
- Register follows the user: Devanagari Hindi, romanised Hinglish, or English.
- `spoken_text` is written for the ear (short sentences, no bullets or URLs). `text` is written for the screen.
- Cultural adaptation rules live in the prompt and are checked by the eval rubric: local analogies,
  no urban-elite assumptions (no laptop, no paid coaching, intermittent data).

### 4.5 Aspirational Layer (students) — Mentor + Roadmap with RAG
- **Corpus** (`corpus/`): curated markdown from **official public sources**, each file carrying a
  `source_url` and a `retrieved_on` date in its frontmatter. Topics: entrance exams, scholarships
  (NMMS, NSP, PM YASASVI), sports pathways (Khelo India, SAI), entrepreneurship (Atal Innovation
  Mission, Startup India), public service (UPSC, state PSCs, panchayat roles), skilling (PMKVY,
  ITIs). Target 80–150 documents. **No invented facts.** If there's no source, it doesn't go in the corpus.
- **Retrieval:** chunk → multilingual embeddings → pgvector cosine similarity, plus keyword
  boosting on exam and scheme names → top-k chunks with their citations.
- **Mentor reply:** grounded answer plus citations. If retrieval finds nothing relevant, the
  mentor says it doesn't know rather than guessing.
- **Roadmap** (structured `Roadmap`): 3–6 steps, each `{action, by_when, cost_inr, source_url}`.
  Stored, so the next session can pick up where the last one left off ("did you register for NMMS?").
- **Memory:** a rolling profile summary (ambitions, constraints, grade, interests) is updated at
  the end of each session. This keeps the context window small without losing who the student is.

### 4.6 Safety — Llama Guard 4 (input and output) plus domain policy
- Both safety checks are **mandatory steps in the orchestrator**. There is no code path that
  sends a reply without passing `safety-out`.
- On top of Llama Guard's categories, a domain policy for minors: no collecting personal details
  beyond grade and district, no romantic or medical advice, and no promising admission or jobs.
- **Crisis path:** self-harm or abuse signals get a fixed, human-reviewed reply with Indian
  helplines (Tele-MANAS 14416, Childline 1098). This reply is never LLM-generated. The event is flagged in telemetry.
- If the safety service is unavailable, the system **fails closed**: a safe holding reply goes
  out, and nothing unclassified is sent.

### 4.7 Web simulator (so judges can try it) — `/demo`
A one-page web UI with mic recording and a text box. It posts to a `web` channel adapter that runs
the **same orchestrator**, and shows each step's output and timing (transcript, safety verdict,
route, retrieved sources, reply, audio). This is the main "whether it works" proof and shows the
architecture at the same time. Abuse protection: per-IP rate limiting, a daily cost cap, and safety checks unchanged.

### 4.8 Telemetry — trajectory of intent
- Every turn emits a `TurnEvent` (latency per step, models used, tokens, cost, safety verdicts, route).
- Each student message also yields `AspirationSignals` (structured extraction): fields mentioned,
  **specificity level** (0 none → 1 curiosity → 2 named field → 3 named role → 4 concrete next
  step taken), constraints mentioned, and sentiment.
- **Trajectory metrics** per student: breadth (distinct fields explored), specificity slope over
  sessions, roadmap step completion, and return rate. Cohort view per teacher or school.
- `/dashboard`: aggregate and anonymised. Phone numbers are stored as salted hashes only. No raw
  transcripts are shown on the dashboard.

### 4.9 Conversation state machine (domain, pure)
`NEW → CONSENT → ROLE (student | teacher) → PROFILE (grade, district, language) → ACTIVE`
`ACTIVE` modes: `exposure` (teacher), `mentor`, `roadmap`. Switching modes ("roadmap banao") is
handled by the router. Transitions are a typed table, and an invalid transition raises an error.
Property-tested: every reachable state has a way out, and `CONSENT` can never be skipped.

**Consent:** India's DPDP Act 2023 requires verifiable parental consent to process a child's data.
For the MVP, onboarding asks students under 18 to confirm a parent or teacher is present and
agrees. Consent is recorded with a timestamp, and `delete my data` ("mera data hatao") purges the
user. The demo materials call this out explicitly.

### 4.10 Distribution beyond WhatsApp (pitch, not MVP scope)
The engine sits behind a `Channel` port, so new channels are adapters, not rewrites. The story for judges:
- **Teacher as the distribution node:** one teacher's phone on a classroom speaker reaches 40
  students. Teacher mode is the cheapest way to reach students without smartphones.
- **IVR / missed-call callback** for 2G feature phones (common in rural India): the same
  STT → LLM → TTS pipeline over a phone call through a telephony provider. A stretch goal at most;
  in the pitch it's the next channel.
- **Web/PWA** for school computer labs and NGOs, already proven by `/demo`.
- **Messenger / Instagram DMs:** the same Meta Graph API family, so a short step from WhatsApp.

---

## 5. Cross-cutting engineering

### 5.1 Reliability
- Every external call (Model API, WhatsApp, sidecar, Llama Guard) gets an explicit timeout,
  bounded retries with exponential backoff plus jitter, `Retry-After` honoured on 429, and a typed error.
- Idempotency keys on inbox (`wa_message_id`) and outbox (`turn_id, part_no`).
- A degradation ladder per step, for example: TTS down → text-only reply with a note; RAG empty →
  mentor without citations, which says so; search grounding down → skip it.
- `/healthz` (liveness) and `/readyz` (database plus provider reachability).

### 5.2 Observability
- Structured JSON logs with `turn_id`, `user_hash` and `step` on every line. No raw phone numbers or transcripts in logs.
- Per-step latency and cost recorded in `turn_events`, which feed `/status`.

### 5.3 Prompts as code
- Prompts live in `app/prompts/*.md.j2` with a version in their frontmatter. The version is
  recorded on every turn, so an eval regression can be traced to a prompt change.
- Every LLM call uses **structured output** into a Pydantic model. A response that fails
  validation is retried once with the validation error included, then becomes a `StepFailure`.

### 5.4 Evaluation harness
- `evals/golden/*.yaml`: about 60 cases covering teacher prompts, student prompts in Hindi,
  Hinglish and English, multi-turn, adversarial (jailbreaks, PII fishing, self-harm), and off-topic.
- The rubric is scored by an LLM judge (Muse Spark at high reasoning effort): factual grounding,
  cultural resonance, reading level, actionability, and safety. Plus deterministic checks:
  citations present, no URLs in `spoken_text`, crisis cases return the fixed reply.
- `marg eval` prints a scorecard. Results are committed to `evals/results/`, and the latest
  scorecard goes in the README and the submission.

### 5.5 Data protection
Users are mostly minors. Rules: hashed phone identifiers, minimum data collected, no
Contributor-mode models on user content, a retention window on audio (delete raw audio after
transcription), and a working delete command.

---

## 6. Tech stack (initial dependency set, approved 2026-10-24 — D4)

| Concern | Choice |
|---|---|
| Runtime | Python 3.13, `uv` for env and lockfile, `.venv/bin/python` |
| Web | FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| HTTP | httpx (async) and `openai` SDK pointed at `https://api.meta.ai/v1` |
| DB | PostgreSQL 16 + pgvector, SQLAlchemy 2 (async) + asyncpg, Alembic |
| Retries | tenacity |
| Templating | Jinja2 (prompts) |
| Logging | structlog |
| Audio | ffmpeg (system binary, in the Docker image) |
| Sidecar (Modal) | transformers + torch (MMS-TTS), sentence-transformers (embeddings) |
| Dev | ruff, mypy (strict), pytest, pytest-asyncio, hypothesis, respx (HTTP fakes) |

---

## 7. Ten-day schedule

Day boundaries are IST. **Feature freeze: end of Day 8.** Days 9 and 10 are for proof and polish only.

| Day | Date | Goal (exit criterion in **bold**) |
|---|---|---|
| Pre | Oct 24–25 | Plan, CLAUDE.md, accounts: Meta developer app + WhatsApp test number, Model API key, Modal / Baseten / Fireworks credits, Neon, Fly/Railway. Collect 10 real Hindi/Hinglish voice-note samples (with consent). **No product code until the rules on pre-existing work are confirmed.** |
| 1 | Mon Oct 26 (from 18:30) | Read official rules. Scaffold repo, pyproject, verification loop, CI, docker-compose Postgres. Spikes: (a) Muse Voice Transcribe on Hindi ogg samples, (b) Llama Guard 4 host, (c) MMS-TTS Hindi quality. **Webhook deployed, signature verified, echoes text back on a real phone.** |
| 2 | Tue Oct 27 | Inbox/outbox, worker with SKIP LOCKED, idempotency, Muse Spark client with structured output and retries. **Text in → Muse Spark → text out, surviving a worker restart mid-turn.** |
| 3 | Wed Oct 28 | Audio download, transcode, STT, TTS on the sidecar, audio upload and send. **Voice note in → voice note out end to end.** |
| 4 | Thu Oct 29 | Safety gate on both sides, crisis path, domain policy. Onboarding state machine + consent + delete. **Adversarial golden cases all handled. Onboarding works on the phone.** |
| 5 | Fri Oct 30 | Translation layer + Exposure layer (teacher mode). **A teacher speaks a chapter name and gets an ExposureBridge as voice + text.** |
| 6 | Sat Oct 31 | Corpus curation (80+ sourced docs), ingestion, retriever, Mentor + Roadmap, profile memory. **A student asks about a career and gets a cited answer and a stored roadmap. The next session recalls it.** |
| 7 | Sun Nov 1 | Telemetry events, aspiration-signal extraction, trajectory metrics, `/dashboard`, `/status`. **Dashboard shows real data from the past days' testing.** |
| 8 | Mon Nov 2 | Web simulator `/demo`, eval harness + scorecard, hardening (timeouts, degradation ladder, a load test with 20 concurrent users). **FEATURE FREEZE. Eval scorecard committed.** |
| 9 | Tue Nov 3 | **Field test** with real teachers and students from your network: record sessions (with consent), collect quotes, fix bugs only. **3+ real users have completed a full session.** |
| 10 | Wed Nov 4 | Demo video (voice-first story: student → teacher → trajectory), README, architecture diagram, eval scorecard, submission form. **Submitted by 23:00 IST**, which leaves 8.5 h of buffer before the 07:30 IST Nov 5 deadline. |

**Stretch goals, in order, only if a day finishes early:** roadmap nudges through approved
templates (outside the 24h window) · an IVR channel adapter (§4.10) · Muse Image visual explainer cards for teachers · Hindi
dialect biasing in STT · a second regional language.

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Muse Voice Transcribe weak or missing for Hindi | Medium | Day-1 spike. A Whisper adapter behind the same port. |
| Real-number display name rejected or delayed (business verification itself isn't needed, see §4.1) | Medium | Apply in S0 with a simple public site behind it. Fallback: test number (5 recipients) for the video, `/demo` for judges. Verification runs in parallel but nothing depends on it. |
| MMS-TTS Hindi sounds robotic | Medium | Day-1 listening test. Indic Parler-TTS as a fallback adapter. Always send text alongside audio. |
| Llama Guard 4 hosting unavailable on partner credits | Low–Med | Modal self-host (12B fits one A10G/L4). Fail closed while it's down. |
| Latency above 15 s on voice turns | Medium | Typing indicator immediately. Parallelise safety-in with routing. Stream TTS per sentence (stretch). |
| Scope creep | High | §2 scope rule. Feature freeze on Day 8. |
| Cost overrun on the public demo | Low | Per-IP rate limit, daily spend cap, no search grounding on `/demo` by default. |
| Fabricated career facts | Medium | RAG with mandatory citations, the "don't know" path, and a grounding score in evals. |

---

## 9. Project folder structure

```
marg-ai/
├── CLAUDE.md                      # binding engineering rules for agents
├── plan.md                        # this file
├── README.md                      # pitch, demo links, architecture, eval scorecard, setup
├── pyproject.toml                 # deps, ruff, mypy strict, pytest config
├── uv.lock
├── .env.example                   # every setting, no values
├── .gitignore
├── Dockerfile                     # app + worker image (includes ffmpeg)
├── docker-compose.yml             # postgres+pgvector, app, worker (local dev)
├── docker-compose.test.yml        # ephemeral postgres for integration tests
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── .github/
│   └── workflows/
│       └── ci.yml                 # ruff format --check, ruff check, mypy, pytest
│
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory, router registration, lifespan
│   ├── worker.py                  # inbox + outbox worker entrypoint
│   ├── cli.py                     # `marg` CLI: ingest-corpus, eval, replay-turn, purge-user
│   │
│   ├── core/
│   │   ├── config.py              # pydantic-settings; model ids, timeouts, flags, cost caps
│   │   ├── errors.py              # MargError hierarchy (ProviderError, SafetyUnavailable, …)
│   │   ├── logging.py             # structlog JSON, PII redaction processor
│   │   ├── ids.py                 # turn ids, salted user hashing
│   │   └── clock.py               # injectable clock (no datetime.now() in domain code)
│   │
│   ├── domain/                    # pure — imports nothing else from app/
│   │   ├── models.py              # User, Profile, Turn, Language, Role, Mode, Transcript, …
│   │   ├── conversation.py        # onboarding/mode state machine (typed transition table)
│   │   ├── aspiration.py          # AspirationSignals, specificity levels
│   │   ├── trajectory.py          # breadth, specificity slope, completion — pure math
│   │   └── text.py                # WhatsApp message splitting, spoken-text sanitising
│   │
│   ├── api/                       # thin HTTP layer
│   │   ├── deps.py
│   │   ├── webhooks_whatsapp.py   # GET verify, POST ingest → inbox
│   │   ├── demo.py                # /demo web simulator endpoints
│   │   ├── dashboard.py           # /dashboard, /status (aggregates only)
│   │   └── health.py              # /healthz, /readyz
│   │
│   ├── channels/
│   │   ├── base.py                # Channel protocol: parse inbound, send outbound
│   │   ├── whatsapp/
│   │   │   ├── payloads.py        # Pydantic models of Cloud API webhook + send payloads
│   │   │   ├── signature.py       # X-Hub-Signature-256 verification
│   │   │   ├── client.py          # send text/audio/interactive, mark read, typing
│   │   │   └── media.py           # download + upload media
│   │   └── web/
│   │       └── adapter.py         # simulator channel, same orchestrator
│   │
│   ├── pipeline/
│   │   ├── orchestrator.py        # the 10 steps in §3.1, StepFailure → fallback mapping
│   │   ├── router.py              # intent → layer (structured Muse Spark call + state)
│   │   ├── steps.py               # typed step results and StepFailure
│   │   └── fallbacks.py           # fixed user-facing fallback replies per failure kind
│   │
│   ├── layers/
│   │   ├── exposure.py            # ExposureBridge generation (teachers)
│   │   ├── translation.py         # LocalisedReply: register, reading level, spoken_text
│   │   ├── mentor.py              # RAG-grounded mentor answer with citations
│   │   ├── roadmap.py             # Roadmap generation + progress check-ins
│   │   └── memory.py              # rolling profile summary
│   │
│   ├── prompts/
│   │   ├── registry.py            # load + render + version prompts
│   │   ├── router.md.j2
│   │   ├── exposure.md.j2
│   │   ├── translation.md.j2
│   │   ├── mentor.md.j2
│   │   ├── roadmap.md.j2
│   │   ├── memory.md.j2
│   │   ├── aspiration_extract.md.j2
│   │   └── eval_judge.md.j2
│   │
│   ├── providers/                 # the only place SDKs are imported
│   │   ├── ports.py               # Protocols: LLM, Transcriber, Synthesizer, SafetyClassifier, Embedder
│   │   ├── http.py                # shared httpx client, timeouts, retry policy
│   │   ├── llm/
│   │   │   └── meta_model_api.py  # Muse Spark via OpenAI-compatible API, structured output
│   │   ├── speech/
│   │   │   ├── muse_transcribe.py # Muse Voice Transcribe
│   │   │   ├── whisper_sidecar.py # fallback STT
│   │   │   └── mms_tts.py         # MMS-TTS via sidecar
│   │   ├── safety/
│   │   │   └── llama_guard.py     # Llama Guard 4, verdict parsing
│   │   └── embeddings/
│   │       └── sidecar.py         # multilingual embeddings via sidecar
│   │
│   ├── audio/
│   │   ├── transcode.py           # ffmpeg subprocess wrapper (ogg/opus ↔ wav)
│   │   └── transliterate.py       # romanised Hinglish → Devanagari for TTS
│   │
│   ├── safety/
│   │   ├── gate.py                # safety-in / safety-out steps, fail-closed
│   │   ├── policy.py              # minor-specific domain policy on top of Llama Guard
│   │   └── crisis.py              # fixed crisis replies + helplines
│   │
│   ├── rag/
│   │   ├── corpus.py              # load + validate corpus frontmatter (source_url required)
│   │   ├── chunker.py
│   │   ├── ingest.py              # chunk → embed → upsert pgvector
│   │   └── retriever.py           # hybrid vector + keyword, returns cited chunks
│   │
│   ├── telemetry/
│   │   ├── events.py              # TurnEvent, step timings, cost accounting
│   │   ├── signals.py             # AspirationSignals extraction step
│   │   └── aggregates.py          # cohort + trajectory queries for dashboard
│   │
│   ├── store/
│   │   ├── db.py                  # async engine, session factory
│   │   ├── tables.py              # SQLAlchemy models
│   │   └── repositories/
│   │       ├── users.py
│   │       ├── turns.py
│   │       ├── inbox.py           # idempotent insert, SKIP LOCKED claim
│   │       ├── outbox.py
│   │       ├── roadmaps.py
│   │       ├── chunks.py          # pgvector
│   │       └── telemetry.py
│   │
│   └── static/
│       ├── demo/                  # simulator page (single HTML + JS, mic recording)
│       └── dashboard/             # trajectory dashboard
│
├── services/
│   └── ml_sidecar/                # Modal app (separate deploy)
│       ├── app.py                 # /tts, /embed, (/stt fallback) endpoints
│       └── README.md
│
├── corpus/                        # curated RAG sources, markdown + frontmatter(source_url, retrieved_on)
│   ├── exams/
│   ├── scholarships/
│   ├── sports/
│   ├── entrepreneurship/
│   ├── public_service/
│   └── skilling/
│
├── evals/
│   ├── golden/                    # *.yaml cases (teacher, student, multi-turn, adversarial)
│   ├── rubrics/                   # judge rubrics per layer
│   └── results/                   # committed scorecards (date + prompt versions)
│
├── docs/
│   ├── architecture.md            # diagrams + flow (exported for submission)
│   ├── decisions/                 # ADRs: 0001-muse-spark-over-llama3.md, 0002-postgres-queue.md, …
│   ├── spikes/                    # Day-1 spike findings (STT Hindi, Llama Guard host, TTS)
│   └── submission/                # demo script, video storyboard, judge walkthrough
│
├── scripts/
│   ├── dev_tunnel.sh              # expose local webhook for testing
│   └── seed_demo_user.py
│
└── tests/
    ├── conftest.py
    ├── fakes/                     # FakeLLM, FakeTranscriber, FakeSynthesizer, FakeSafety, FakeChannel
    ├── fixtures/
    │   ├── whatsapp/              # real-shaped webhook payloads (text, audio, interactive, status)
    │   └── audio/                 # short consented Hindi/Hinglish samples
    ├── unit/                      # pure + fake-backed, incl. hypothesis property tests
    ├── integration/               # postgres (docker-compose.test.yml), inbox/outbox, repositories
    └── contract/                  # WhatsApp payload parsing, provider response parsing
```

---

## 10. Definition of done (MVP)

- [ ] A voice note on WhatsApp gets a voice + text reply in the same register, p50 under 8 s.
- [ ] Teacher mode: chapter → ExposureBridge. Student mode: question → cited mentor answer → stored roadmap.
- [ ] Safety on input and output, crisis path, fail-closed. All adversarial golden cases pass.
- [ ] Onboarding with consent; delete-my-data works.
- [ ] Worker restart mid-turn loses nothing; duplicate webhooks produce one reply.
- [ ] `/demo` publicly usable by judges; `/dashboard` shows trajectory metrics from real usage.
- [ ] Eval scorecard committed and shown in the README.
- [ ] Verification loop (format, lint, mypy strict, pytest) green on CI.
- [ ] Demo video, README and submission done by Nov 4, 23:00 IST.

---

## 11. Build steps and session workflow

The MVP is built **one step at a time**, directly on `main` (single developer, no feature
branches for now). Each step is one session and ends in a working, tested, committed state. A
step that doesn't reach its exit criterion is not committed, and the next step doesn't start on
top of it.

### 11.1 The loop for every step

1. **Design first.** The agent reads `CLAUDE.md` and the relevant plan sections, then proposes:
   files to add or change, the main types and Protocols, the tests it will write (including the
   negative cases from CLAUDE.md §4), and open questions. **No code until the design is approved.**
2. **Build** on `main`.
3. **Verify.** Run the full loop (format, lint, mypy, pytest), plus integration tests or evals if
   the step touches the store or prompts.
4. **Prove it.** Run the step's exit check for real: on a phone, with curl, or in the simulator.
5. **Review and commit.** You read the diff, it's committed to `main` with the step id in the
   message, and the step is ticked below.

The prompt to start a step:

> Step S<n>: <name>. Read CLAUDE.md and plan.md (§11 and the sections listed for this step).
> Propose the design first and wait for my approval. Then implement on main, run the
> verification loop, and report against the step's exit criterion.

### 11.2 Steps

Some steps need the official rules confirmed (any product code) or the Model API key.

| | Step | Plan refs | Exit criterion | Day |
|---|---|---|---|---|
| [ ] S0 | **Prep (no product code):** accounts, WhatsApp business verification, 10 consented voice samples, a list of corpus sources, draft golden eval cases | §0, §4.5, §5.4 | Accounts ready; `docs/spikes/samples.md` and `evals/golden/` drafts exist | Pre |
| [ ] S1 | **Scaffold:** pyproject + uv, ruff/mypy/pytest config, `core/` (config, errors, logging with redaction, clock), `/healthz` and `/readyz`, layering test, Dockerfile, compose, CI | §3.2, §5.1–5.2, §6 | Verification loop green locally and on CI; `/healthz` answers in Docker | 1 |
| [ ] S2 | **Spikes:** Muse Voice Transcribe on Hindi samples, Llama Guard 4 host, MMS-TTS quality. Findings written to `docs/spikes/`, plus ADRs | §0, §8 | A recorded go/fallback decision for each of the three | 1 |
| [ ] S3 | **WhatsApp channel:** payload models, signature check, webhook GET/POST, send text, deploy | §4.1 | A real phone message is echoed back by the deployed app | 1 |
| [ ] S4 | **Store + queue:** tables, Alembic, inbox/outbox repositories, worker with SKIP LOCKED | §3.3, §5.1 | Duplicate webhooks produce one reply; a worker killed mid-turn loses nothing | 2 |
| [ ] S5 | **LLM provider:** ports, Muse Spark adapter, retry policy, prompt registry, structured output, orchestrator skeleton | §3.1, §5.3 | Text in → Muse Spark → text out on the phone | 2 |
| [ ] S6 | **Voice:** media download, ffmpeg transcode, STT adapter, ML sidecar on Modal, TTS, audio send | §4.2 | Voice note in → voice note out | 3 |
| [ ] S7 | **Safety:** gate on input and output, domain policy, crisis replies, fallbacks, fail closed | §4.6 | Every adversarial golden case is handled; safety outage → holding reply | 4 |
| [ ] S8 | **Onboarding:** state machine, consent, role/grade/district/language, delete-my-data | §4.9, §5.5 | A full onboarding works on the phone; deletion purges every table | 4 |
| [ ] S9 | **Translation layer** | §4.4 | The same answer comes back in Hindi, Hinglish and English, with `spoken_text` | 5 |
| [ ] S10 | **Exposure layer** (teacher mode) | §4.3 | A spoken chapter name returns an ExposureBridge as voice + text | 5 |
| [ ] S11 | **RAG:** corpus validation, chunker, embeddings, pgvector, retriever | §4.5 | 80+ sourced docs ingested; retrieval returns cited chunks | 6 |
| [ ] S12 | **Mentor + Roadmap + memory** | §4.5 | A cited answer, then a stored roadmap that the next session recalls | 6 |
| [ ] S13 | **Telemetry:** turn events, aspiration signals, trajectory metrics, `/dashboard`, `/status` | §4.8 | The dashboard shows real data from testing | 7 |
| [ ] S14 | **Web simulator** `/demo` | §4.7 | A stranger can use it from a link; rate limit and cost cap work | 8 |
| [ ] S15 | **Eval harness** + scorecard | §5.4 | `marg eval` runs; scorecard committed | 8 |
| [ ] S16 | **Hardening:** degradation ladder audit, load test with 20 concurrent users. **FEATURE FREEZE** | §5.1 | p50 and p95 latency recorded; no lost turns under load | 8 |
| [ ] S17 | **Field test:** bug fixes only | §7 | 3+ real users have completed a full session | 9 |
| [ ] S18 | **Submission:** README, architecture diagram, demo video, form | §7, §10 | Submitted by Nov 4, 23:00 IST | 10 |
