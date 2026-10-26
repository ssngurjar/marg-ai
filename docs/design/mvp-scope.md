# Hackathon build scope — enterprise grade by default, exceptions only for the clock

> Decided by the owner on 2026-10-25 (decisions C1–C5 below).
> **For the hackathon build, this doc wins** wherever it differs from a step doc. The step docs
> are the full enterprise-grade design, and nothing in them is deleted.

## 0. The principle (C5)

**We build the full, enterprise-grade design by default.** A step is built "lite" only where the
full version would put the 10-day timeline at risk, and every such exception is listed in §4
with three things: the reason (the time it would cost), what the lite version keeps, and the
**upgrade trigger** (when we build the full version anyway because time allows).

- At each step's design-first review (plan.md §11.1), Claude proposes **full or lite with a time
  estimate**, and the owner approves. A new exception, or dropping one, is always the owner's call.
- When the full version turns out to fit, it's built: lite is a fallback, not a target.
- Lite never touches the hard lines in §2.

## 1. The product for the hackathon

**Marg.ai is the "Aaj ki Khoj" engine:** a voice-first WhatsApp coach that helps rural parents
turn everyday moments into discovery for their 3–8-year-olds, and remembers what each child
notices. The child gets the world; the phone talks only to the parent.

The pitch still tells the whole story, one learner's journey from age 3 to their first career
choice. The MVP proves the part nobody else is building: the beginning.

| Built in the MVP | Stretch (only after the Day 8 checkpoint) | Phase 2 (after the hackathon) |
|---|---|---|
| Parent journey (S10b) on WhatsApp and the web demo | Teacher exposure-lite (S10): one prompt, no RAG, reusing the pipeline | Student mentor, RAG corpus, roadmaps, memory (S11, S12) |
| Voice in and out, safety, onboarding, deletion | | Separate translation layer (S9 as its own step) |
| Curiosity signals and the young-learner view | | Full queue: leases, outbox loop, takeover, multi-instance (S4 full) |
| `/demo` with the live pipeline trace (polling) | | SSE hub, teacher dashboard links, aspiration signals |
| Eval scorecard on the parent journey and safety | | Staging load tests, nightly evals |
| 10 polished activities (minimum 7) | | 30+ activities; then variant and fully generated activities |

## 2. Hard lines

### Never cut, even for the hackathon
These are about children's safety, trust, and not breaking in front of judges:
1. **Safety on input and output.** The sealed `SafeReply`, so nothing unchecked can be sent. The
   crisis path with fixed, sourced helplines. Fail closed. The `d7` hazard rule and the
   supervision line on every activity.
2. **Consent and delete-my-data**, and the children's data rules: an optional nickname and a
   birth year only; inbound audio never stored; crisis text never stored; **photos checked for
   people before anything else and never stored** (C7).
2b. **Direct child talk only with the parent's one-time consent**, voice-only, time-limited; never
   asks a child for personal details; never secrecy or attachment language; child-worded crisis
   reply with the official helpline; the parent gets a topic summary, never a disclosure quote (C13).
3. **No double replies:** the unique inbox insert (`channel, external_id`). Meta re-sends webhooks.
4. **No lost messages on restart:** pending work is picked up again at startup.
5. **CLAUDE.md engineering rules:** typed (no `Any`), no swallowed exceptions, no stubs or
   placeholders, the full verification loop green, property tests for core logic.
6. **No secrets or real user data in git.** No Contributor-mode models on user content.
7. **No invented facts** in activities, fixed texts or helplines.

### Deliberately not in the MVP (written down, so nobody "quickly adds" them)
- Running more than **one** app instance while exception E1 holds (§4.1). Fly.io is set to one
  machine with no autoscaling until E1's upgrade (multi-worker leases) is built.
- Any RAG, corpus ingestion, or career facts.
- Teacher dashboards, classroom codes, student roadmaps and memory.
- A separate translation model call.

### The enterprise commitment
After the hackathon, Marg.ai moves to the Phase 2 design already written in the step docs: the
durable multi-worker queue (s04), the separate translation layer (s09), RAG and the mentor (s11,
s12), full telemetry (s13), SSE (s14), staging load tests (s16), and guarded generated activities
(s10b §4.5). The MVP code is built so that move is an addition, not a rewrite: the same
contracts, ports, `TurnWrite`s, sealed safety types and tables.

## 3. Owner decisions

| # | Decision | Replaces |
|---|---|---|
| C1 | MVP = parent journey. Teacher exposure-lite is a stretch after the Day 8 checkpoint. Student mentor, RAG and roadmaps go to Phase 2. | the three-audience MVP |
| C2 | Simplified durable processing: inbox dedupe, an in-process dispatcher with one lock per user, direct sending, recovery at startup; the web demo polls. The full s04 design is Phase 2. | full s04 / s14 SSE for the MVP |
| C3 | Latency: (a) generation may run concurrently with `safety_in`, its output used only on ALLOW; (b) parents are routed without a model call; (c) layers write directly in the user's register, with `spoken_text`, in one call. | B11 (separate translate step) and the "no generation before safety_in" ordering |
| C4 | 10 polished, reviewed activities at launch (minimum 7). | 30 activities |
| C6 | Khoj card with Muse Image after a good report: a textless illustration with the discovery in the caption, safety-checked by Llama Guard 4 (multimodal), shareable. | Meta tooling is 25% of the score (Official Rules); also aims at the "most viral" bonus |
| C7 | Activity photos with SAM 3.1: a person check first (reject and drop), then object counts feed the reflection; photos never stored. | Same: "surfacing unexpected capabilities" |
| C8 | TTS licence: ask the organisers on Day 1 whether MMS-TTS (CC-BY-NC) is fine; spike MMS and Indic Parler-TTS (Apache 2.0) in S2; use MMS only if confirmed. | The rules require every open-source licence to be followed |
| C9 | Muse Spark Open on Baseten (`meta-models/muse-spark-open-1026`) runs the parent reflection and curiosity extraction, behind the same `LanguageModel` port, with Muse Spark on the Model API as the fallback. | Best Build on Meta Open Weight Models ($10k) and the Meta tooling criterion |
| C10 | Code starts Oct 27 00:00 ET (09:30 IST), the official building period; 9 build days. | Participant Guide: building period Oct 27 – Nov 4, new work only |
| C11 | Curiosity moment: when a parent relays the child's own question, Marg.ai gives a true, simple answer to share, a 2-minute "let's find out" activity, and one question back. | Marg.ai mentors the child, not only coaches the parent |
| C12 | Gentle exposure for ages 3–8: "who explores this in the real world", never careers, exams or "you should become". | Close the exposure gap without assigning interests |
| C13 | Direct child talk: one-time parent consent, then the child starts by button or "Main Munni hoon"; voice-only; 6 exchanges / 10 minutes; child safeguards; topic summary to the parent. | Children don't always say everything they wonder to a parent |
| C15 | Child-talk crisis endings: abuse disclosure → no parent summary at all; self-harm or sadness → gentle fixed summary with the adult helpline, never the child's words. | The adult reading the phone may be the abuser |
| C16 | Inside a child session, account actions (delete, nudges, add child, consent) never work; the child is told to ask a grown-up. | A child must not change the family's account by accident |
| C14 | Nothing is dropped for C11–C13; build order Day 5–7: curiosity moment → child talk → khoj card → web demo; SAM photos on Day 8. If a day slips, the owner decides what moves. | Owner: drop nothing |
| C5 | Enterprise grade by default; a lite version only where the full one would stretch the 10 days, each with a reason and an upgrade trigger (§0, §4). C3's latency changes are part of the full design, not shortcuts. | "MVP-lite" as the default framing |

## 4. Exceptions and scoped designs

| # | Exception | Reason (timeline) | Upgrade trigger |
|---|---|---|---|
| E1 | Single-process dispatcher instead of the multi-worker queue (§4.1) | Leases, takeover, the outbox loop and `LISTEN/NOTIFY` are about 1.5–2 days plus the hardest bugs to debug late at night | S1–S5 are done by end of Day 2 with the verification loop green → build s04's leases and outbox loop on Day 3–4 |
| E2 | Polling web demo instead of the SSE hub (§4.6) | The hub (per-process listener, routing, replay) is about half a day, and polling looks the same to a judge | S14 done with half a day to spare → build the SSE hub |
| E3 | 10 activities instead of 30 (§4.8) | Writing and reviewing activities is human time, not code | Reviewers keep pace → enable more as they're approved |
| E4 | 10-user smoke test instead of a staging load test and chaos suite (§4.7) | A staging app and load driver are about a day | Feature freeze reached early → build the staging load test |
| — | Scope, not quality: student mentor, RAG, roadmaps (C1); teacher exposure as a stretch | Content and build time for a crowded idea | Phase 2 (exposure: Day 8 checkpoint) |

Everything not listed here is built to the full design in its step doc. §4.2–4.5 describe
designs that apply to the full product too (C3) or that follow from the scope (C1).

### 4.1 Processing: one process, durable enough (exception E1)

```
POST /webhooks/whatsapp ─▶ verify ─▶ INSERT inbox ON CONFLICT DO NOTHING ─▶ commit ─▶ dispatcher.wake(user_hash) ─▶ 200
                                                                                        │
TurnDispatcher (asyncio, started in the app lifespan) ◀─────────────────────────────────┘
  per user: asyncio.Lock (one turn at a time in this single process)
  wait TURN_DEBOUNCE_MS (1 s) so a burst becomes one turn
  tx 1: claim this user's pending rows (UPDATE … SET status='processing', turn_id) + INSERT turns
  load TurnContext → run_turn(ctx, recorder, observer)
  tx 2 (finalize): apply TurnWrites in order, INSERT outbox rows (sealed ReplyDelivery),
                   turn completed (crisis → user_text NULL), inbox done
  send the parts in order, directly, with the shared RetryPolicy; mark each outbox row sent/failed
  purge the user now if this turn was a confirmed deletion
  run post-turn tasks (curiosity signals) in their own short transactions
  if more pending rows arrived meanwhile → loop for this user
```

- **Startup recovery** (in the lifespan, before serving): `processing` rows → `pending` (with
  `attempts + 1`), and outbox rows still `pending`/`sending` are sent. Then the dispatcher is woken
  for every user with pending rows. This is the whole crash story for one process.
- **Poison messages:** `attempts ≥ MAX_TURN_ATTEMPTS` → the fixed `TRY_AGAIN_LATER` reply through
  the sealed path, rows `failed`.
- **Hourly housekeeping task** (same process): expired `media_blobs`, the purge sweep for
  deletions whose send failed, raw-payload and turn-text retention.
- **NudgeLoop** (s10b §4.11) runs as another task in the same process.
- **Kept from s04:** the tables (`turns`, `turn_steps`, `outbox_messages`), `StepRecorder`,
  `TurnWrite` appliers, finalize ordering, crisis NULL, `process_user_turn` (used by evals).
- **Phase 2 only:** `users.lease_owner`/`lease_expires_at`, heartbeat, maintenance takeover, the
  separate worker process, `OutboxLoop` with `sending_since`, `LISTEN/NOTIFY`. The columns may
  exist in the migration unused; the code paths aren't built.
- Graceful shutdown: stop accepting turns, wait up to `SHUTDOWN_GRACE_S` for running turns; anything
  unfinished is recovered at the next startup.

### 4.2 Pipeline and latency (C3, part of the full design)

```
A. user text      fetch_media → transcribe (voice only)
B. safety_in ‖ route ‖ generate      all three start together
     generate's result is used ONLY if safety_in returns ALLOW; otherwise it is discarded unread
     parents: route is deterministic (no model call), §4.3
C. safety_out ‖ synthesize           synthesize is speculative, as before
D. finalize + send
```

- **Safety ordering, restated (C3a):** no generated output is used, stored or delivered before
  `safety_in` has returned ALLOW. Generation may run concurrently and is discarded on BLOCK,
  CRISIS or failure. Writes from a discarded generation are dropped too. Tests assert that a
  BLOCK/CRISIS turn's reply never contains generated text (s05 §9 properties).
- **Direct localisation (C3c):** each layer's structured output includes `text` and
  `spoken_text` **in the user's register** (`CanonicalReply.spoken_text`, contracts §2.6). The
  orchestrator builds the `LocalisedReply` directly, and `TRANSLATE` is recorded `SKIPPED`. s09's
  rules still apply, as **shared prompt rules plus deterministic checks**: register choice
  (`choose_register`), parent reading level, spoken-text rules (Devanagari for Hindi and
  Hinglish), `sanitize_spoken`, the script-share check and the citation-marker check. A failed
  check triggers the one `semantic_check` repair retry. The separate translation call is Phase 2.
- **Budget:** fetch 0.5 s · transcode 0.15 s · STT 1.0 s · safety ‖ generate 2.5 s · safety_out ‖
  TTS 1.2 s · upload and send 0.9 s → **about 6.3 s** for a voice turn (target p50 < 8 s).

### 4.3 Routing for the MVP (s05 router table, reduced)

Deterministic rules only for parents: blank → `REPEAT_PLEASE`; deletion phrases → `DATA_DELETION`;
deletion-confirm state → `DATA_DELETION`; not `ACTIVE` → `ONBOARDING`; language name →
`ONBOARDING`; `onb:*` → `ONBOARDING`; `jrn:*`, `nudge:*` and everything else from an active
parent → `JOURNEY`. Inside `JourneyLayer.handle`, a deterministic dispatch picks the flow: a khoj
request (button or keyword "aaj ki khoj", "khoj", "activity") → A; an open activity → B (report);
`jrn:other` → C; `nudge:*` or settings phrases → E; otherwise → D (parent question, which also
handles off-topic gently). The LLM router is only used for teachers, if the stretch is built.

### 4.4 Onboarding for the MVP (s08)

- Role buttons: **parent** and **teacher**. "Student" isn't offered. A user who says they're a
  student gets the fixed `STUDENT_COMING_SOON` copy (friendly, suggests sharing Marg with a parent
  or teacher), and stays in `AWAITING_ROLE`.
- **Teacher in the MVP is a distribution role**, before any exposure layer exists: on reaching
  `ACTIVE`, a teacher gets a fixed message with a ready-to-forward invite for their class's parent
  WhatsApp group (a `wa.me` link with prefilled text). If the stretch is built, teachers then get
  exposure bridges.
- The parent path (consent → role → child → first khoj) and deletion are exactly as in s08.
  The student guardian path stays designed and unused until Phase 2.

### 4.5 Telemetry for the MVP (s13)

- `turn_steps` and `/status` (latency, success rate, cost) as designed.
- **Curiosity signals** and the young-learner metrics (done rate, breadth, engagement slope,
  child-question rate) as designed. This is the trajectory the demo shows.
- `/dashboard` is admin-only for the MVP (link from the CLI), showing the parent and young-learner
  section with k-anonymity. Teacher links, aspiration signals and district scopes are Phase 2.

### 4.6 Web demo (exception E2)

- Same cookie session (the `SignedTokenCodec` API), same inbox, same pipeline.
- `POST /demo/messages` → `202 {message_id}`; the page **polls** `GET /demo/messages/{id}` every
  1 s. The response carries the turn status, the `turn_steps` so far (for the trace panel), and
  the reply when it's done. No SSE hub and no `LISTEN/NOTIFY`.
- The parent role and an "Aaj ki khoj" button (no nudges on the web). Rate limits and the IST
  daily cost cap as designed.

### 4.7 Evals (scoped by C1) and hardening (exception E4)

- Golden files in the targets: `parent_journey`, `adversarial`, `crisis`, `onboarding` (parent
  and deletion cases), plus `translation` cases rewritten for direct localisation. Mentor, roadmap
  and exposure files are Phase 2 (exposure comes back if the stretch is built). Targets: ≥ 85%
  overall, 100% on crisis and adversarial.
- Hardening: the degradation audit, timeouts, `/readyz`, a 10-concurrent-user smoke test against
  the deployed app through `/demo`, a restart-mid-turn check, and the pre-demo checklist. Staging
  load tests and chaos suites are Phase 2.

### 4.8 Content (exception E3)

10 enabled activities at launch (minimum 7): at least 6 different domains, at least 3 that work
indoors, ages 3–8 covered. Drafted by Claude from Day 1 (after kickoff), reviewed by the owner and one parent by Day 5. Selection
logic is unchanged; with 10 activities, the repeat window is effectively 10 days.

### 4.9 Spikes (s02)

Keep A (speech-to-text), B (Llama Guard, now including **image** input), C (**MMS-TTS and Indic
Parler-TTS side by side**, C8) and E (structured output). Add **F: Muse Image and SAM 3.1** (request
formats, latency, cost, SAM's person/face detection on 10 test photos of objects and of people).
Drop D (embeddings): there's no RAG in the MVP.

## 5. Build level per step

**Full** = the step doc's design, built completely. **Full (scoped)** = the full design for the
parts in hackathon scope (C1). **Exception** = §4's lite version until its upgrade trigger fires.

| Step | Build level | Notes |
|---|---|---|
| S1 scaffold | Full | one process while E1 holds (no `worker` compose service); the worker service returns with E1's upgrade |
| S2 spikes | Full (scoped) | A, B, C, E; D (embeddings) belongs to Phase 2 RAG |
| S3 WhatsApp | Full | text, buttons, audio, template |
| S4 processing | **Exception E1** | §4.1; upgrade trigger in §4 |
| S5 orchestrator | Full | with C3 (§4.2–4.3); the S5 exit layer is a minimal parent-question layer |
| S6 voice | Full | |
| S7 safety | Full | with the C3a ordering rule |
| S8 onboarding | Full (scoped) | parent and teacher paths (§4.4); the student path stays designed for Phase 2 |
| S9 localisation | Full | rules and checks run inside each layer (C3c); a separate translation call is optional later |
| S10 exposure | Stretch | Day 8 checkpoint |
| S10b parent journey | **Full (core)** | with §4.3 dispatch; content per E3; khoj card (C6) and activity photos (C7) |
| S11 RAG | Phase 2 | |
| S12 mentor/roadmap/memory | Phase 2 | `LayerResult` is still defined there and used by every layer |
| S13 telemetry | Full (scoped) | §4.5: no student or teacher parts until those audiences exist |
| S14 web demo | **Exception E2** | §4.6 |
| S15 evals | Full (scoped) | parent journey, safety and onboarding files (§4.7) |
| S16 hardening | **Exception E4** | §4.7 |
| S17 field test | Full | parents from Day 6 |
| S18 submission | Full | Day 10 |

## 6. Schedule (IST)

Code starts at the official building period: **Tue Oct 27, 00:00 ET = 09:30 IST** (decision C10).
Monday Oct 26 is for the kickoff livestream (21:30 IST), accounts and credit requests only.
That gives 9 build days, so the old Day 1 evening is folded in.

| Day | Date | Work | Exit |
|---|---|---|---|
| 0 | Mon Oct 26 | Kickoff 21:30 IST; accounts, credits (Model API, Baseten, Modal), Discord, nudge template submitted. **No code.** | rules confirmed; credits requested |
| 1 | Tue Oct 27 (from 09:30) | S1, S2 spikes, S3; ask the MMS licence question in #office-hours (19:30 IST) | a reply sent to a real phone |
| 2 | Wed Oct 28 | S4 (E1), S5 with the safety core; start drafting the 10 activities | text in → checked Muse Spark reply out; restart mid-turn loses nothing |
| 3 | Thu Oct 29 | S6 voice | voice note in → voice note out |
| 4 | Fri Oct 30 | S7, S8 | crisis and adversarial cases pass; parent onboarding on the phone |
| 5 | Sat Oct 31 | S10b core, **curiosity moment (C11)**; activities reviewed in the village | khoj → report → serve-and-return reply; a child's question answered through the parent |
| 6 | Sun Nov 1 | **Child talk (C13)**, S10b nudges, S13 signals; **field testing with parents and children starts** | a child talks directly for a session; the parent gets a summary; nudge at the chosen time |
| 7 | Mon Nov 2 | Khoj card (C6), S14 (E2) web demo, Muse Spark Open on Baseten (C9), `/status` and admin dashboard | a card after a good report; a stranger can use `/demo` |
| 8 | Tue Nov 3 | SAM 3.1 photos (C7), S15 scorecard, S16 (E4). **Feature freeze at end of day** (also the last day for submission troubleshooting on Discord) | scorecard committed; checklist done |
| 9 | Wed Nov 4 | S18: video, README, X post, submission | **submitted by 23:00 IST** (deadline 07:30 IST Nov 5) |

**Owner's reminder (2026-10-26): the Aspirational engine.** At every checkpoint where time is ahead
of plan (end of Day 5, Day 7, and the Day 8 checkpoint), **remind the owner** that the Aspirational
engine (s11 RAG + s12 mentor, roadmaps, memory) is wanted if time allows, and propose the smallest
honest slice that fits the time left, with an estimate. It is never started without the owner's go,
and it comes after everything in the schedule above. Note for the proposal: "basic RAG apps" are a
Guide anti-project, so any slice must build on the child's curiosity record, not be a standalone
career chatbot.

If a day slips, the owner decides what gives way. The suggested order to cut is: the teacher
stretch (S10) first, then SAM photos (C7), then the khoj card (C6). The hard lines (§2) never move.

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-26 | C11 curiosity moment, C12 gentle exposure, C13 direct child talk, C14 nothing dropped | Owner: Marg.ai mentors the child too | owner |
| 2026-10-26 | C9 Muse Spark Open, C10 code start and 9-day schedule | Participant Guide (bonus prizes, building period) | owner |
| 2026-10-26 | C6 khoj card, C7 activity photos, C8 TTS licence check | Official Rules: Meta tooling 25%, licences must be followed | owner |
| 2026-10-25 | C5: enterprise by default; lite only as listed exceptions E1–E4 with upgrade triggers | Owner: aim for full enterprise grade, take lite steps only where they'd stretch the 10 days | owner |
| 2026-10-25 | v1: C1–C4 | External review: focus on the unique parent journey, cut invisible infrastructure, hit the latency target | owner |
