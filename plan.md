# Marg.ai — Build Plan (Meta Global AI Developer Hackathon, Indie Track)

> **Hackathon MVP = the parent journey ("Aaj ki Khoj").** What's built in 10 days, what's a
> stretch, what's Phase 2, and the hard lines: [docs/design/mvp-scope.md](docs/design/mvp-scope.md).
> We build to full enterprise grade by default; lite steps only where the 10 days demand it
> (listed exceptions with upgrade triggers). Phase 2 completes the rest of the product.

> Status: **draft v1**, written 2026-10-24, before kickoff. Revisit at the end of every build day.
> Engineering rules are in [CLAUDE.md](CLAUDE.md). This file covers *what* gets built and *when*.

---

## 0. What the hackathon rewards (researched 2026-10-24; Official Rules read 2026-10-26)

Sources: <https://dev.meta.ai/events/global-hackathon>, <https://cerebralvalley.ai/e/meta-ai-developer-hackathon>,
<https://dev.meta.ai/docs/models>, <https://dev.meta.ai/docs/pricing-rate-limits>, and the Official Rules +
waiver at <https://cerebralvalley.ai/e/meta-ai-developer-hackathon/waiver> (read 2026-10-26).

| Fact | Value | What it means for us |
|---|---|---|
| **Project judging (Official Rules)** | **Impact 30%** (real-world potential, who benefits, could people use it, theme fit) · **Use of Meta AI Tooling 25%** (creative use, beyond basic integration, surfacing unexpected capabilities) · **Technical Depth & Execution 20%** (sound, refined engineering, real craft) · **Demo 25%** (working, impressive, holds up live, quality of the demo video) | These weights replace the event page's one-line summary. Every feature must earn points on at least one (§2). |
| Prizes | **Indie track $400,000**: 1st $150k, 2nd $100k, 3rd $75k, 4th $50k, 5th $25k. Startup track $550k. Up to $50k bonus prizes (e.g. community vote, **most viral project**) | A shareable artefact (e.g. a khoj card) also competes for the viral bonus. |
| Team size | Indie: individuals, students, or teams of up to 4 | Solo is allowed; a teammate (e.g. for content review or the video) is an option. |
| Credits | $150 Meta Model API credits (Credit Terms): claimed through the form in the "Know Before You Go" email by Nov 4, 9 PM ET; needs a Model API account with a payment method and its Team ID; applied within ~2 business days; **don't expire** once applied; usage beyond them is charged to the card | Claim on Day 1 so credits land by Day 2–3; set a spending alert. $150 covers development, evals and the demo. |
| Original work and open source | The Submission must be our original work and solely ours; third-party technical help is allowed if we own the result; open source is allowed **if its licences are followed** and we build on it. No rule against preparing before kickoff was found | Design docs prepared before kickoff are fine. **Every model and library licence must be honoured**, which puts MMS-TTS (CC-BY-NC) in question (§8). |
| Rights | We keep ownership; Organizers get a perpetual, royalty-free licence to use and show the Submission, and no confidentiality | Never put secrets in the repo or video. Anyone appearing in the demo video must consent to Meta's public use of it (§8). |
| Eligibility | 18+, not in sanctioned countries, not Meta/CV staff or family | Owner is eligible. |
| Theme fit | "Build for Your World" — a problem you know firsthand | Marg.ai fits well. Lead the story with the rural exposure gap. |
| Kickoff | **Mon Oct 26, 9:00 AM ET = 18:30 IST** | Day 1 starts in the evening IST |
| Submission deadline | **Wed Nov 4, 9:00 PM ET = Thu Nov 5, 07:30 IST** (US DST ends Nov 1, so this is EST) | Plan to submit by **Nov 4, 23:00 IST**. Don't use the overnight buffer. |
| Judging / finals | Nov 4–8 judging, Nov 9 closing ceremony with live finals | Judges must be able to **try it themselves**. Plan: a real WhatsApp number anyone can message (it works without business verification, see §4.1), with the public web demo (§4.7) as the guaranteed path. |
| Pre-existing work | The rules published so far only require "original work product"; no clause on code written before the event was found (re-checked 2026-10-26). The organisers can still add rules | We assume the strict reading: **no product code or content before kickoff**. Planning and design docs only, tagged `pre-kickoff`, disclosed in the README. Re-read the rules after the kickoff livestream. |
| Submission | Through the Cerebral Valley portal: <https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit> | The rules name a demo video; check the portal's form for its other fields (repo, description, video length) on Day 1. |
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

Marg.ai builds a person, not just answers. It follows a **learner** from early childhood to their
first career decisions, by voice on WhatsApp, in Hindi or Hinglish. A **parent** of a 3–8-year-old
gets a daily two-minute *khoj* (discovery) using the world around them (the field, the kitchen,
the sky) and replies that build on what the child said: "the world is the curriculum, the phone is
the coach". A **teacher** gets a lesson bridge: today's textbook chapter mapped to real-world
fields (public policy, sports science, entrepreneurship, space), with a 5-minute classroom hook. A
**student** gets a mentor that cites real Indian pathways (exams, scholarships, schemes) from a
curated corpus, and builds a step-by-step **roadmap**. Every turn adds to a **trajectory**:
curiosity signals from age 3, aspiration signals later, keyed by learner, so by the time a child
asks "what should I become?", Marg.ai already knows what they've noticed and loved for years.

---

## 2. Mapping features to the judging criteria (Official Rules weights)

| Criterion (weight) | What we show | Where it lives |
|---|---|---|
| **Impact (30%)** | Rural parents of 3–8-year-olds, by voice, in Hindi/Hinglish, at no cost: a daily discovery ritual that builds a child's curiosity from age 3, and a trajectory that follows the learner to their first career choice. Real parents in the video and field test. | §1, §4.11 |
| **Use of Meta AI Tooling (25%)** | Muse Spark (structured personalisation, serve-and-return reflection, curiosity extraction), Muse Voice Transcribe (Hinglish voice notes), Llama Guard 4 (child-safety gate both ways), Meta open-weights TTS, **Muse Image** khoj cards (shareable illustrations of a child's discovery) and **SAM 3.1** counting what a child collected in a photo, with a person check that protects children (decisions C6, C7). Go beyond "a chatbot calling an LLM". | §4 |
| **Technical Depth & Execution (20%)** | Sealed safety types, learner-centred data model, durable idempotent processing, property tests, the eval scorecard, `/status` latency numbers. | §3, §5 |
| **Demo (25%)** | A live WhatsApp number and `/demo` that hold up when judges try them, and a polished video. | §4.7, §7 |

The original three-axis summary from the event page, kept for reference:

| Axis | What we show | Where it lives |
|---|---|---|
| **Creativity** | A journey from age 3, not a Q&A bot: daily parent-child *khoj* with serve-and-return coaching. Voice-first WhatsApp for low-literacy users. Curriculum-to-career "exposure bridges" for teachers. Hinglish adaptation with local cultural references (cricket, kabaddi, the mandi, the panchayat). A trajectory that spans childhood to career choice. | §4.3–4.8, §4.11 |
| **Technical ambition** | Four Meta models in one pipeline: Muse Spark, Muse Voice Transcribe, Llama Guard 4, MMS-TTS. A learner-centred data model, proactive opt-in nudges, structured output everywhere, RAG with citations, durable inbox/outbox processing, a sealed safety gate on input and output, and an LLM-judge eval harness with published scores. | §3, §4, §5.4 |
| **Whether it works** | A public web simulator running the same pipeline. A live WhatsApp number on the demo video. Real voice notes from real parents, students and teachers (field test from Day 6). Latency and success-rate numbers on a `/status` page. | §4.7, §7 |

**Scope rule:** a feature that earns no points on the four criteria doesn't get built. A half-finished
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
- **TTS:** MMS-TTS Hindi on the sidecar (licence CC-BY-NC: hackathon only, replaced before any
  commercial use). The translation layer writes `spoken_text` in Devanagari for Hindi and Hinglish,
  and `app/audio/tts_text.py` checks it before synthesis (docs/design/s06-voice.md §4.6).
- **STT input:** Muse Voice Transcribe accepts only WAV, so ogg/opus and webm are converted first.
  It returns no language or confidence; the register is detected locally.
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
- Each parent report about a young child yields `CuriositySignals`: the domains the child engaged
  with (nature, sky, numbers, stories, making, movement, art, people, everyday work), engagement
  0–3, and whether the child asked their own question. Signals are keyed by **learner**, so one
  child's record can run from age 3 to their first career choice.
- **Trajectory metrics** per learner: breadth, engagement or specificity slope over sessions,
  return rate, roadmap creation. Cohort view per district (classroom codes were trimmed).
- `/dashboard`: aggregate and anonymised. Phone numbers are stored as salted hashes only. No raw
  transcripts are shown on the dashboard.

### 4.9 Conversation state machine (domain, pure)
`NEW → CONSENT → ROLE (student | teacher | parent)`, then:
- student → `GUARDIAN` → `PROFILE` (grade, district) → `ACTIVE`
- teacher → `PROFILE` (subject, grade, district) → `ACTIVE`
- parent → `CHILD` (age and optional nickname) → `ACTIVE`, with the first khoj in the same turn

`ACTIVE` modes: `exposure` (teacher), `mentor` and `roadmap` (student), `journey` (parent).
Switching modes ("roadmap banao") is handled by the router. Transitions are a typed table, and an
invalid transition raises an error. Property-tested: every reachable state has a way out, and
`CONSENT` can never be skipped. Full design: docs/design/s08-onboarding.md.

**Consent:** India's DPDP Act 2023 requires verifiable parental consent to process a child's data.
For the MVP, students confirm a parent or teacher knows and agrees (self-declared, stated as a
known limit). Parents consent for themselves and their child. Consent is recorded with a
timestamp and the copy version, and `delete my data` ("mera data hatao") purges the user. The
demo materials call this out explicitly.

### 4.10 Distribution beyond WhatsApp (pitch, not MVP scope)
The engine sits behind a `Channel` port, so new channels are adapters, not rewrites. The story for judges:
- **Parents through people they trust:** the school's class WhatsApp group for parents (the
  teacher posts one join link), anganwadi workers (the village childcare centres for 0–6), school
  management committee meetings, QR posters. Value comes in the first 30 seconds: consent, the
  child's age, and today's khoj straight away.
- **Teacher as the distribution node:** one teacher's phone on a classroom speaker reaches 40
  students. Teacher mode is the cheapest way to reach students without smartphones.
- **IVR / missed-call callback** for 2G feature phones (common in rural India): the same
  STT → LLM → TTS pipeline over a phone call through a telephony provider. A stretch goal at most;
  in the pitch it's the next channel.
- **Web/PWA** for school computer labs and NGOs, already proven by `/demo`.
- **Messenger / Instagram DMs:** the same Meta Graph API family, so a short step from WhatsApp.

### 4.11 Parent journey (ages 3–8) — "Aaj ki Khoj"
Full design: [docs/design/s10b-parent-journey.md](docs/design/s10b-parent-journey.md).
- **Who:** parents (and later anganwadi workers) of children aged 3–8, the NEP foundational stage.
- **What:** a daily two-minute activity from a reviewed catalogue of 30 free, local activities,
  personalised by Muse Spark (the child's nickname, the season, what the child said last time).
  The parent reports back by voice, and Marg.ai replies serve-and-return: it praises the child's
  specific idea and asks one question that extends it.
- **How it reaches people:** one opt-in WhatsApp template a day at the parent's chosen time. The
  activity itself is sent only after the parent taps, inside the normal 24-hour window.
- **Data:** an optional nickname and a birth year only. No careers for under-11s; curiosity
  signals record what the child engages with and never label them.
- **Later:** ages 0–2 and 8–11, fully generated activities with the same guardrails (owner's direction).

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
Users are mostly minors or speak for minors. Rules: hashed phone identifiers with the number
encrypted for replies only; minimum data collected; for young children, an optional nickname and
a birth year only (no photos, no names, no exact birth dates); no Contributor-mode models on user
content; inbound audio never stored; crisis-turn text never stored; and a working delete command.
Full rules: docs/design/data-model.md §3–4.

---

## 6. Tech stack (approved 2026-10-24 — D4; updated 2026-10-25 — B6)

| Concern | Choice |
|---|---|
| Runtime | Python 3.13, `uv` for env and lockfile, `.venv/bin/python` |
| Web | FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| HTTP | httpx (async) and `openai` SDK pointed at `https://api.meta.ai/v1` |
| DB | PostgreSQL 16 + pgvector, SQLAlchemy 2 (async) + asyncpg, Alembic, `pgvector` (Python) |
| Retries | our own deadline-aware `RetryPolicy` (no `tenacity`) |
| Security | `cryptography` (AES-GCM for phone numbers) |
| Content files | `pyyaml` (activity catalogue, curriculum, golden evals) |
| Templating | Jinja2 (prompts) |
| Logging | structlog |
| Audio | ffmpeg (system binary, in the Docker image) |
| Sidecar (Modal) | transformers + torch (MMS-TTS), sentence-transformers (embeddings) |
| Dev | ruff, mypy (strict), pytest, pytest-asyncio, hypothesis, respx (HTTP fakes), types-PyYAML |

---

## 7. Ten-day schedule

Day boundaries are IST. **Feature freeze: end of Day 8.** Days 9 and 10 are for proof and polish only.

| Day | Date | Goal (exit criterion in **bold**) |
|---|---|---|
| Pre | Oct 24–25 | Plan, CLAUDE.md, design docs. Accounts and the real-number setup. 10 consented voice samples. Draft the golden evals (test data). **No product code or product content before kickoff**: the activities are written from Day 1. The repo is tagged `pre-kickoff` at the boundary. |
| 1 | Mon Oct 26 (from 18:30) | Re-read the rules after the kickoff livestream. S1, S2, S3; submit the nudge template; start drafting the 10 activities. **A reply sent to a real phone.** |
| 2 | Tue Oct 27 | S4 (exception E1), S5 with the safety core. **Text in → checked Muse Spark reply out; a restart mid-turn loses nothing.** |
| 3 | Wed Oct 28 | S6 voice. **Voice note in → voice note out.** |
| 4 | Thu Oct 29 | S7 safety, S8 onboarding. **Crisis and adversarial cases pass; parent onboarding works on the phone.** |
| 5 | Fri Oct 30 | S10b core: catalogue, selection, personalisation, reflection; activities reviewed. **Khoj → voice report → serve-and-return reply.** |
| 6 | Sat Oct 31 | S10b nudges and polish, S13 curiosity signals. **Field testing with parents starts; the nudge arrives at the chosen time.** |
| 7 | Sun Nov 1 | S14 (E2) web demo, S13 `/status` and admin dashboard. **A stranger can use `/demo`.** |
| 8 | Mon Nov 2 | S15 scorecard. **Checkpoint:** if the parent journey is demo-ready, S10 teacher exposure-lite (half a day); otherwise polish. **Scorecard committed.** |
| 9 | Tue Nov 3 | S16 hardening (E4). **Feature freeze at end of day**; field-test fixes only after that. |
| 10 | Wed Nov 4 | S18: demo video (a mother and her 5-year-old, then the full-journey pitch), README, architecture diagram, scorecard, submission form. **Submitted by 23:00 IST**, which leaves 8.5 h of buffer before the 07:30 IST Nov 5 deadline. |

**Hackathon cut (owner decisions C1–C4, 2026-10-25):** the MVP is the parent journey. Teacher
exposure-lite is a stretch after the Day 8 checkpoint. The student mentor, RAG and roadmaps, the
full multi-worker queue, the separate translation call and SSE are Phase 2, already designed in
`docs/design/`. Full details and the hard lines: [docs/design/mvp-scope.md](docs/design/mvp-scope.md).

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
| An unsafe activity suggestion for a young child | Low | Reviewed catalogue only; personalisation can't add steps or materials; the `d7` hazard rule on every reply; a fixed supervision line appended by code; fallback to the reviewed text. |
| Nudge template not approved in time | Medium | Submit on Day 1. Without it, parents start each day by tapping "Aaj ki khoj" or typing it; the journey works, just not proactively. |
| MMS-TTS licence is non-commercial (CC-BY-NC) while the Official Rules require every open-source licence to be followed, and grant Meta a licence to use the Submission for marketing | Medium | A prize competition may not count as non-commercial use. Ask the organisers on Discord on Day 1; spike Indic Parler-TTS (Apache 2.0) alongside MMS in S2; decision pending with the owner. |
| Demo video shows real people (a parent and a child) | Certain | The Official Rules give Organizers perpetual rights to the video. Written consent from the parent covering public and Meta marketing use; no child's face; the child's voice only with that consent, or an adult re-enactment. |
| Launch activities not reviewed in time | Low | 10 drafted in S0, reviewed by Day 5; launch with a minimum of 7 (decision C4). |
| Single app instance (MVP) | Known | Deliberate (C2): one Fly machine, no autoscaling; startup recovery covers restarts. Phase 2 restores multi-worker leases. |

---

## 9. Project folder structure

The top-level layout. The design docs in `docs/design/` are authoritative for exact module paths;
where this tree and a design doc differ, the design doc wins.

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
│   ├── wiring.py                  # composition root: builds adapters, injects ports
│   ├── worker/                    # `python -m app.worker`: turn, outbox, nudge, post-turn, maintenance loops
│   ├── cli.py                     # `marg` CLI: ingest-corpus, eval, replay-turn, purge-user
│   │
│   ├── core/
│   │   ├── config.py              # pydantic-settings; model ids, timeouts, flags, cost caps
│   │   ├── errors.py              # MargError hierarchy (ProviderError, SafetyUnavailable, …)
│   │   ├── logging.py             # structlog JSON, PII redaction processor
│   │   ├── ids.py                 # turn ids, salted user hashing
│   │   └── clock.py               # injectable clock (no datetime.now() in domain code)
│   │
│   ├── domain/                    # pure — imports only core.errors / core.types
│   │   ├── enums.py, models.py    # shared vocabulary (docs/design/contracts.md)
│   │   ├── writes.py              # TurnWrite variants applied atomically with the reply
│   │   ├── conversation.py        # onboarding state machine (typed transition table)
│   │   ├── learners.py, stages.py # learners, age bands, active-learner choice
│   │   ├── activities.py          # activity model, validation, deterministic selection
│   │   ├── aspiration.py          # AspirationSignals, CuriositySignals
│   │   ├── trajectory.py          # breadth, slopes, sessions — pure math
│   │   ├── language.py            # register detection
│   │   └── text.py                # message splitting, spoken-text sanitising, keyword matching
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
│   │   ├── onboarding.py          # consent, role, child, profile, deletion (+ onboarding_copy.py)
│   │   ├── journey.py             # parent journey: khoj, reflection, parent questions, nudges
│   │   ├── exposure.py            # ExposureBridge generation (teachers)
│   │   ├── translation.py         # LocalisedReply: register, reading level, spoken_text
│   │   ├── mentor.py              # RAG-grounded mentor answer with citations
│   │   ├── roadmap.py             # roadmap drafting and storage
│   │   ├── off_topic.py           # short redirect
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
│   │   ├── analysis.py            # duration and silence checks
│   │   └── tts_text.py            # prepares Devanagari spoken text for TTS
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
├── content/
│   └── activities/                # reviewed khoj catalogue (*.yaml) + _materials.yaml, _hazards.yaml
│
├── corpus/                        # curated RAG sources, markdown + frontmatter(source_url, retrieved_on)
│   ├── curriculum/                # NCERT chapter catalogue (s10), not ingested
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
- [ ] Parent mode: today's khoj for a 3–8-year-old, a serve-and-return reply to the child's answer, a daily nudge at the chosen time.
- [ ] Stretch: teacher mode, chapter → ExposureBridge. (Student mentor and roadmaps are Phase 2.)
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

1. **Design first.** The agent reads `CLAUDE.md`, the foundation docs in `docs/design/` and the
   step's design doc (`docs/design/sNN-*.md`), then proposes:
   files to add or change, the main types and Protocols, the tests it will write (including the
   negative cases from CLAUDE.md §4), and open questions. **No code until the design is approved.**
2. **Build** on `main`.
3. **Verify.** Run the full loop (format, lint, mypy, pytest), plus integration tests or evals if
   the step touches the store or prompts.
4. **Prove it.** Run the step's exit check for real: on a phone, with curl, or in the simulator.
5. **Review and commit.** You read the diff, it's committed to `main` with the step id in the
   message, and the step is ticked below.

The prompt to start a step:

> Step S<n>: <name>. Read CLAUDE.md, docs/design/README.md, the three foundation docs and
> docs/design/s<nn>-*.md.
> Propose the design first and wait for my approval. Then implement on main, run the
> verification loop, and report against the step's exit criterion.

### 11.2 Steps

Some steps need the official rules confirmed (any product code) or the Model API key.

| | Step | Build level | Design doc | Exit criterion | Day |
|---|---|---|---|---|---|
| [ ] S0 | **Prep (no product code or content):** accounts, real-number setup, 10 consented voice samples, golden eval drafts, reviewers lined up | Full | `docs/s0-setup.md` | Accounts ready; samples and `evals/golden/` drafts exist; repo tagged `pre-kickoff` | Pre |
| [ ] S1 | **Scaffold** (single process while E1 holds) | Full | s01 | Verification loop green locally and on CI; `/healthz` answers in Docker | 1 |
| [ ] S2 | **Spikes:** STT, Llama Guard 4, MMS-TTS, structured output | Full | s02 | A recorded go/fallback decision for each | 1 |
| [ ] S3 | **WhatsApp channel:** webhook, signature, parsing, identity, sending (text, buttons, audio, template) | Full | s03 | A real phone message is stored and answered by the CLI sender | 1 |
| [ ] S4 | **Processing:** inbox dedupe, in-process dispatcher, finalize, direct send, startup recovery | Exception E1 | mvp-scope §4.1 (full: s04) | Duplicate webhooks produce one reply; a restart mid-turn loses nothing | 2 |
| [ ] S5 | **Model API, router, orchestrator, safety core** | Full (with C3) | s05 + mvp-scope §4.2–4.3 | Text in → checked Muse Spark reply out on the phone | 2 |
| [ ] S6 | **Voice:** media, ffmpeg, STT, ML sidecar, TTS, audio replies | Full | s06 | Voice note in → voice note out | 3 |
| [ ] S7 | **Safety:** domain policy, crisis lexicon and texts, refuse texts, `d7` | Full | s07 | Every adversarial and crisis golden case handled; safety outage → holding reply | 4 |
| [ ] S8 | **Onboarding:** parent and teacher paths, consent, learners, delete-my-data | Full (scoped) | s08 + mvp-scope §4.4 | Parent onboarding works on the phone; deletion purges every table | 4 |
| [ ] S9 | **Localisation rules and checks** inside layers (no separate call) | Full (in-layer) | s09 + mvp-scope §4.2 | Replies in Hindi, Hinglish and English with valid `spoken_text` | 5 |
| [ ] S10b | **Parent journey:** catalogue, khoj, serve-and-return reflection, nudges | **Full (core)** | s10b | Khoj → voice report → serve-and-return reply; nudge at the chosen time | 5–6 |
| [ ] S13 | **Telemetry:** `/status`, curiosity signals, admin young-learner dashboard | Full (scoped) | s13 + mvp-scope §4.5 | Curiosity signals and metrics from field testing visible | 6–7 |
| [ ] S14 | **Web demo** `/demo` with the pipeline trace (polling) | Exception E2 | s14 + mvp-scope §4.6 | A stranger can use it from a link; rate limit and cost cap work | 7 |
| [ ] S15 | **Eval scorecard** (parent journey, safety, onboarding) | Full (scoped) | s15 + mvp-scope §4.7 | Scorecard committed; targets met | 8 |
| [ ] S10 | **Teacher exposure-lite** | Stretch (Day 8 checkpoint) | s10 | A spoken chapter name returns an ExposureBridge | 8 |
| [ ] S16 | **Hardening:** audit, timeouts, readiness, 10-user smoke test. **FEATURE FREEZE** | Exception E4 | s16 + mvp-scope §4.7 | p50 recorded; checklist done | 9 |
| [ ] S17 | **Field test** with parents (from Day 6) | Full | plan §7 | 3+ parents have completed a khoj and a report | 6–9 |
| [ ] S18 | **Submission:** README, architecture diagram, demo video, form | Full | plan §7, §10 | Submitted by Nov 4, 23:00 IST | 10 |
| — S11 | RAG | Phase 2 | s11 | — | — |
| — S12 | Mentor, roadmap, memory | Phase 2 | s12 | — | — |
