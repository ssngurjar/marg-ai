# S10b — Parent journey: "Aaj ki Khoj" for ages 3–8

> **Hackathon build level: Full (core). Launch content per exception E3.** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

> Draft v1, 2026-10-25. Reviewed and approved at the start of S10b, before any code.

## 1. Purpose

No four-year-old messages WhatsApp asking what to become. The gap Marg.ai exists to close starts
years before that question, in the everyday conversations a child does or doesn't have with the
adults around them. Rural parents want their children to learn, but often don't know what to
ask or do beyond "go and read".

S10b makes Marg.ai a coach for the **parent**, so the **child** gets the world:
- Once a day, at a time the parent chooses, Marg.ai offers a two-minute **khoj** (discovery): a
  free activity using what's around them (the field, the kitchen, the market, the sky), plus the
  questions to ask the child and what to listen for.
- The parent sends back a voice note of what the child said or did. Marg.ai replies in the
  **serve-and-return** pattern: it praises the child's specific thinking, gives one question that
  extends it, and offers one short idea about how children learn.
- Every report adds to the child's **curiosity profile**, which is the start of the trajectory of
  intent. The aim is that by the time the child is old enough for the mentor, Marg.ai already
  knows what they have noticed and loved for years.

This step builds that for the NEP **foundational stage, ages 3–8**, the MVP scope the owner chose.

## 2. Read first

- [00-overview.md](00-overview.md), [contracts.md](contracts.md) (§1 `Role.PARENT`, `Route.JOURNEY`,
  `Route.NUDGE`, `CuriosityDomain`, `ActivityStatus`, `LearnerRelation`, `PartKind.TEMPLATE`; §2.2
  `Learner`, `TurnContext.active_learner`, `open_activity`; §2.4 `TurnWrite`; §3 `ActivitySource`),
  [data-model.md](data-model.md) (`learners`, `learner_activities`, `nudge_subscriptions`, `curiosity_signals`)
- [s08-onboarding.md](s08-onboarding.md): the parent onboarding path (consent → role → child)
- [s09-translation.md](s09-translation.md): canonical English → the parent's register and spoken text
- [s07-safety.md](s07-safety.md): the gate, fixed replies, `d7` added here
- [s13-telemetry.md](s13-telemetry.md): `CuriositySignals` extraction and the young-learner metrics
- [s04-queue-worker.md](s04-queue-worker.md): the worker hosts the nudge loop; `NUDGE` turns use the normal outbox
- plan.md §1 and §4.10; CLAUDE.md §1 (no invented facts), §11 (safety, children's data)

## 3. Scope

**In**
- Stage logic: `app/domain/stages.py` (age band and NEP stage from birth year)
- The activity catalogue: `content/activities/*.yaml`, its model and validator
  (`app/domain/activities.py`), loaded and checked at startup
- `ActivitySource` with the MVP implementation `CatalogueActivitySource`
- `JourneyLayer` (`app/layers/journey.py`): today's activity, another activity, the
  serve-and-return reflection, parent learning questions, nudge preferences
- Prompts: `activity_personalise.md.j2`, `parent_reflection.md.j2`, `parent_answer.md.j2`
- Output safety rule `d7 CHILD_PHYSICAL_HAZARD`, and the always-appended supervision line
- Nudges: subscription, the `NudgeLoop` in the worker, `NUDGE` turns that send a Meta-approved template
- Migration `s10b_journey`: `learner_activities`, `nudge_subscriptions`, `turns.learner_id`
- Golden eval file `evals/golden/parent_journey.yaml`
- Khoj cards with Muse Image (§4.13) and activity photos with SAM 3.1 (§4.14): decisions C6, C7

**Out**
| Item | Owner / when |
|---|---|
| Parent onboarding (role choice, child's age and nickname, `LearnerUpsert`) | s08 |
| Curiosity-signal extraction and young-learner dashboard metrics | s13 |
| Ages 0–2 (serve-and-return talk prompts) and 9–11 (preparatory mini-projects) | post-MVP; the stage table in §4.2 already has their rows |
| Fully generated activities | post-MVP, through the same port (§4.5) |
| (khoj card moved into scope: §4.13) | — |
| Linking a child's own phone number later in life | post-MVP (a learner link table) |

## 4. Design

### 4.1 Principles (these are acceptance criteria, not slogans)

1. **The world is the curriculum; the phone is the coach.** Marg.ai talks to the parent. Every
   activity happens offline, with things already in the home or village. No activity asks the
   child to look at a screen.
2. **Free and local.** No activity needs anything bought. Materials come from a closed list
   (§4.3) of things a rural household has: leaves, stones, water in a bowl, rotis, a broom, the
   sky, animals seen from a distance.
3. **Serve and return.** Each activity gives questions to *ask*, and what to *listen for*. Each
   reflection builds on what the child actually said.
4. **Interests emerge; they're never assigned.** No careers, exams or "what will you become" for
   children under 11. Signals record what the child engages with; they never label the child.
   **Gentle exposure is allowed (C12):** a reply may mention who explores this in the real world
   ("jo log chaand-taaron ko samajhte hain unhe khagol-vaigyanik kehte hain, aur woh bhi tumhari
   tarah sawaal poochte hain"), without suggesting the child become one, and with no exams, money or careers advice.
7. **The child is a person with their own questions (C11, C13).** Marg.ai mentors the child's own
   curiosity: through the parent when the parent relays it, and directly when the child talks to
   Marg.ai themselves, with the parent's one-time consent and strict safeguards (§4.16).
5. **The parent learns too.** Each reply carries one short idea about how children learn
   ("asking 'why do you think so?' matters more than the right answer").
6. **Safety is structural.** An adult is always present (a fixed supervision line, appended by
   code). Physical hazards are caught by a deterministic rule on every reply (§4.10).

### 4.2 Learners and stages — `app/domain/stages.py`

```python
class AgeBand(StrEnum): UNDER_3; FOUNDATIONAL_3_8; PREPARATORY_8_11; MIDDLE_11_14; SECONDARY_14_18; ADULT
def age_on(birth_year: int, today: date) -> int: ...         # today.year − birth_year (birth year only, no month)
def age_band(birth_year: int, today: date) -> AgeBand: ...
```

| Band (NEP 5+3+3+4) | Age | What Marg.ai does | MVP |
|---|---|---|---|
| `UNDER_3` | 0–2 | serve-and-return talk prompts for the parent | no: a fixed "coming soon" reply plus one general tip |
| `FOUNDATIONAL_3_8` | 3–8 | **daily khoj** (this step) | **yes** |
| `PREPARATORY_8_11` | 8–11 | weekly mini-projects, "who does this work in our village" | no: foundational activities for ages 7–8 are offered with a note |
| `MIDDLE_11_14` | 11–14 | Exposure layer (via a teacher), first look at fields | existing s10/s12 |
| `SECONDARY_14_18` | 14–18 | mentor and roadmap | existing s12 |

Birth year only, never a full date, so age is approximate (±1). That's enough to pick
activities, and it collects less data. Ages 8 belong to both bands, and the MVP treats 8 as foundational.

**Choosing the active learner** (parents with up to 3 children):
1. A button id carrying a learner (`jrn:today:<learner_id>`) wins.
2. Otherwise, a nickname in the message ("Munni ne kaha…") matched against the parent's learners.
3. Otherwise, the learner of the latest `OFFERED` activity in the last 48 h.
4. Otherwise, the only learner. With several and no signal, the reply asks which child, using one button per nickname (or "Pehla bachcha (5 saal)" when there's no nickname).

### 4.3 The activity catalogue — `content/activities/*.yaml`

One file per activity, written by us and **reviewed by a human** before it's enabled:

```yaml
id: shadow-time                 # slug, unique, never reused
version: 1                      # bump on any change; recorded on learner_activities
status: enabled                 # draft | enabled | retired
age_min: 4
age_max: 8
domains: [earth_sky, numbers_patterns]   # CuriosityDomain, 1–3
setting: outdoors               # home | kitchen | outdoors | field | market | courtyard
season: any                     # any | summer | monsoon | winter
duration_minutes: 5
materials: [stick, stones]      # from the closed materials list (content/activities/_materials.yaml)
title: "Parchhai ka khel"       # short, any language
steps:                          # for the parent, imperative, ≤ 6, each ≤ 160 chars (English)
  - "In the morning, push a stick into the ground in an open sunny spot with your child."
  - "Ask your child to mark the tip of the stick's shadow with a stone."
  - "Come back at lunchtime and mark it again."
questions_to_ask:               # open-ended, 2–4
  - "Where did the shadow go? Why do you think it moved?"
  - "When was the shadow longest?"
listen_for: "Any idea that connects the shadow to where the sun is, even if it isn't exactly right."
parent_tips:                    # 1–3; one is used per reply
  - "Ask 'why do you think so?' and wait. The thinking matters more than the right answer."
hazards: []                     # declared hazards from the hazard list; each needs a safety note
safety_notes: []                # required when hazards is non-empty
reviewed_by_role: "parent and anganwadi worker"   # role, never a name
reviewed_on: 2026-10-30
```

**Validation** (`validate_activity`, at startup; any failure is a `CorpusValidationError` naming
the file and field, and the app refuses to start):
- every field present and typed; unknown keys rejected
- `age_min ≥ 3`, `age_max ≤ 8`, `age_min ≤ age_max`
- `materials ⊆ _materials.yaml` (the closed list of free household and natural things)
- `hazards ⊆ _hazards.yaml`, and `len(safety_notes) ≥ len(hazards)`
- the hazard lexicon (§4.10) finds nothing in `steps` that isn't declared in `hazards`
- no purchase words ("buy", "kharid", "dukaan se lao", "₹") in any text field
- `status: enabled` requires `reviewed_by_role` and `reviewed_on`

**MVP catalogue: 10 enabled activities at launch, minimum 7** (decision C4). Polished beats many:
that's a week and a half of daily khoj without repeats, enough for the demo and field testing.
They cover at least 6 of the 9 domains, ages 3–8, and at least 3 work indoors (monsoon days).
The catalogue grows to 30+ in Phase 2. Authoring workflow:
1. Claude drafts activities in batches of 10 (they contain no factual claims, only instructions and questions).
2. The owner reviews each one, ideally with one parent and one anganwadi worker or teacher, then
   sets `status: enabled` and the review fields.
3. Drafting can start in S0, since it's content and not code. Enabling happens in S10b.

NCF Foundational Stage (2022) curricular goals are a good reference for coverage. If we map
activities to them later, the codes are copied from the NCERT document with its `source_url`,
never from memory. The MVP uses our own `CuriosityDomain` tags.

### 4.4 Flows

```
A. TODAY'S KHOJ         trigger: nudge button "jrn:today", text like "aaj ki khoj", or right after onboarding
   select (deterministic, §4.6) → personalise (LLM, §4.7) → CanonicalReply(English)
   → translate → safety_out (+ d7) → reply with buttons [Ho gaya ✓ jrn:done] [Doosri khoj jrn:other]
   writes: ActivityOffered

B. REPORT BACK          trigger: an open activity exists and the parent sends text/voice, or taps jrn:done
   reflect (LLM, §4.8) → CanonicalReply(English) → translate → safety_out → reply
   buttons: [Doosra bachcha onb:add-child] while the parent has fewer than 3 learners (s08 handles it)
   writes: ActivityReported(status=DONE, summary ≤ 200 chars)
   post-turn: ExtractSignals → curiosity_signals (s13)

C. ANOTHER KHOJ         trigger: jrn:other  → mark the open one SKIPPED, then flow A excluding it

D. PARENT QUESTION      trigger: a question about the child's learning or behaviour ("bachcha padhai mein mann nahi lagata")
   parent_answer (LLM, §4.9): warm, practical, play-based, no labels, no diagnosis
   health or medical questions are refused by safety (d4 MEDICAL, parent variant: "anganwadi
   worker ya doctor se baat kijiye"); abuse disclosures go to the crisis path (s07)

E. NUDGE SETTINGS       trigger: nudge:* buttons, or "roz ka message band karo" / "time badlo"
   writes: NudgePreference; reply is fixed text confirming the change

F. DAILY NUDGE          trigger: NudgeLoop (no inbound message), §4.11
   a NUDGE turn with one TEMPLATE part; the parent's tap on its button starts flow A
```

### 4.5 `ActivitySource`: catalogue now, guarded generation later

```python
class ActivitySource(Protocol):
    async def candidates(self, learner: Learner, today: date, recent_ids: Sequence[str]) -> list[Activity]: ...
```

- **MVP: `CatalogueActivitySource`** returns enabled catalogue entries that fit the learner's age,
  the season (by month: Mar–Jun summer, Jul–Sep monsoon, Oct–Feb winter) and the repeat window.
- **The owner's direction is to move to fully generated activities, with guardrails, for a more
  human touch.** The port is how that happens without touching the layer:
  1. **Phase 1 (MVP):** a curated catalogue, with LLM personalisation of wording, context and questions.
  2. **Phase 2:** `VariantActivitySource`. The model writes a *variant* of a catalogue activity
     (new setting, new questions) as a full `Activity`. It goes through the **same**
     `validate_activity` as a hand-written file, plus Llama Guard and the `d7` rule. Rejected
     variants fall back to the original.
  3. **Phase 3:** `GenerativeActivitySource`. Fully new activities from the stage goals and the
     child's curiosity profile, same validator and safety, plus sampled human review recorded in
     a review log. It's switched on per cohort.
- Because every source returns the same validated `Activity` type, the safety guarantees don't
  depend on where an activity came from.

### 4.6 Selection (deterministic) — `app/domain/activities.py`

```python
def choose_activity(candidates: Sequence[Activity], history: Sequence[PastActivity],
                    signals: Sequence[CuriosityPoint], today: date) -> Activity | None: ...
```

1. Drop anything offered to this learner in the last `ACTIVITY_REPEAT_DAYS` (30). If nothing is
   left, allow the oldest-offered.
2. Score each candidate:
   - **+3** for each domain the child hasn't had in their last 5 activities (rotation, which keeps breadth growing)
   - **+2** if one of its domains had engagement ≥ 2 recently (follow what lights the child up), applied to at most 1 in 3 picks so the child doesn't narrow too early
   - **+1** for a season match more specific than `any`
3. The highest score wins. Ties break by `id`, so the result is reproducible and testable.

Selection is deterministic on purpose: it's cheap, explainable to judges, and property-testable.
The model's job is to make the chosen activity feel personal, not to choose it.

### 4.7 Personalisation — prompt `activity_personalise.md.j2`

```python
class ActivityPersonalisation(BaseModel):
    intro: str = Field(max_length=200)                      # warm, uses the nickname if given
    steps: list[str] = Field(min_length=1, max_length=6)    # the catalogue steps, reworded for this family
    questions_to_ask: list[str] = Field(min_length=2, max_length=4)
    listen_for: str = Field(max_length=160)
    parent_tip: str = Field(max_length=160)                 # chosen from the activity's parent_tips, may be reworded
```

Inputs: the `Activity` (as system data, since it's curated), the learner's age and nickname, the
month, and the child's last report summary (user data, in a slot). Rules in the prompt: keep the
same steps, in the same order (rewording only); use only the listed materials; add no new
actions; questions stay open-ended; no careers, exams or grades; English output.

`semantic_check` (s05 hook, one repair retry):
- `len(steps) == len(activity.steps)`
- the hazard lexicon finds nothing that isn't declared on the activity
- no purchase words, no career or exam words (`ENGINEER`, `DOCTOR`, `NEET`, "ban jaayega"…), and
  no labels for the child ("genius", "slow", "weak", "kamzor", "tez")

If it still fails, the reply uses the **catalogue text unmodified** (outcome `DEGRADED`). The
activity is still safe, because the catalogue entry was reviewed.

**Body assembly (code):** intro · numbered steps · "Poochiye:" questions · "Dhyan dijiye:" listen-for
· tip · the fixed supervision line. Translated by s09 like any canonical reply (adult reading
level, the parent's register, spoken text in Devanagari for Hindi and Hinglish).

### 4.8 Serve-and-return reflection — prompt `parent_reflection.md.j2`

```python
class ParentReflection(BaseModel):
    praise_specific: str = Field(max_length=220)    # names what the child actually said or did
    next_question: str = Field(max_length=160)      # one question that extends the child's idea
    parent_tip: str = Field(max_length=160)
    summary_for_record: str = Field(max_length=200) # neutral, third person; nickname only; no labels
```

Inputs: the open activity, the parent's report (user data, in a slot), and the learner's age.
Rules: be specific, not generic ("Munni noticed the shadow moved, which means she's watching
closely"); one question only; never correct the child harshly; no labels; no careers;
acknowledge "she didn't want to" warmly ("kal phir koshish kijiye, khel ki tarah"). The same
`semantic_check` lexicons apply.

Writes `ActivityReported(learner_activity_id, status=DONE, summary=summary_for_record)`.
A report with no open activity is handled as a parent question (flow D).

**Model (C9):** the reflection prompt runs on **Muse Spark Open** via Baseten
(`OPEN_MODEL`), through a second instance of the s05 `LanguageModel` adapter (same Chat
Completions surface, different base URL and key), chosen per prompt id by `OPEN_MODEL_ROUTES`.
On any `ProviderError` it falls back to Muse Spark on the Model API in the same step, and
`turn_steps.model` records which one answered. The strict-schema and `semantic_check` rules are
identical. Verify in S2 spike E that Muse Spark Open supports `json_schema` structured output;
if it doesn't, ask the owner before changing approach.

### 4.9 Parent questions — prompt `parent_answer.md.j2`

Output `CanonicalReply` fields via a small schema (`answer ≤ 500 chars`, `try_this ≤ 200 chars`,
a play-based thing to try today). Rules: practical and warm; play-based; no diagnosis or labels;
no medical advice (safety catches it as well); no "compare with other children"; suggest the
anganwadi worker or teacher for anything persistent. There's no retrieval, and the answer states
no facts or figures (the same "no figures" validator as the s12 mentor's `guidance`).
A career question about a young child ("mera 5 saal ka beta doctor kaise banega?") gets a gentle
reframe: it's too early to choose, so nurture curiosity now. Then it offers today's khoj.

### 4.10 Safety additions

- **`d7 CHILD_PHYSICAL_HAZARD`** (output rule in `app/safety/rules.py`, lexicon section
  `[child_hazards]` in `lexicon.toml`): water bodies (pond, well, river, *talab*, *kuan*, *nadi*),
  fire (*maachis*, flame, stove), sharp tools (*chaku*, blade, sickle), electricity (wire, socket),
  roads and traffic, climbing heights, snakes and scorpions, eating unknown plants or berries,
  medicines. On a journey reply, a match **not covered by the activity's declared hazards** →
  BLOCK → REFUSE/GENERIC, and the step falls back to the unmodified catalogue text, which passes
  because its hazards are declared and reviewed. `d7` is in both decision tables: ALLOW on input
  (a parent mentioning the pond isn't a risk), BLOCK on output.
- **Supervision line:** every activity reply ends with a fixed, translated line: "Yeh khoj bachche
  ke saath, aapki nazar mein hi karein." It's added by code after translation, so a model can't drop it.
- **Medical, input side:** d4 on a parent's question → REFUSE with the `MEDICAL` variant's parent
  wording (pointing to the anganwadi worker, doctor or ASHA). That's a fixed text in s07's table,
  keyed by role.
- **Abuse disclosure** about a child (d5) → the s07 crisis path with the child-protection helpline,
  exactly as for students.
- Llama Guard runs on input and output as for every turn.

### 4.11 Nudges

**Opt-in.** The first activity reply after onboarding carries three buttons: `nudge:08` "Subah 8
baje", `nudge:18` "Shaam 6 baje", `nudge:off` "Main khud poochunga". A tap writes `NudgePreference`
and replies with fixed text. The time can be changed later ("time badlo") and turned off ("roz ka
message band karo"). **"stop" alone is not a deletion keyword** (s08 removes it), so turning off
nudges can't be confused with deleting data.

**The template.** One template, `NUDGE_TEMPLATE_NAME`, created and approved in WhatsApp Manager in
Hindi, Hinglish and English. Its body has no variables: "Aaj ki khoj taiyaar hai! 2 minute,
bachche ke saath." It has one quick-reply button whose payload is `jrn:today`. Meta decides the
category (likely Marketing). Pricing per template message in India is checked in S10b and
recorded in `docs/decisions/`. A tap arrives as an `INTERACTIVE` message with
`interactive_reply_id = "jrn:today"` (s03 maps template quick replies), which opens a normal
24-hour window. The activity itself is sent then, in the free-form reply, never inside the template.

**`NudgeLoop`** (in the worker, s04 hosts it, every 60 s):

```sql
SELECT n.user_hash FROM nudge_subscriptions n JOIN users u USING (user_hash)
WHERE n.enabled AND n.next_due_at <= now() AND u.state = 'active' AND u.role = 'parent'
  AND u.channel = 'whatsapp' AND u.lease_owner IS NULL
ORDER BY n.next_due_at LIMIT 50 FOR UPDATE OF n SKIP LOCKED;
```

For each one, in one transaction:
1. **Skip and reschedule** if:
   - the time falls in quiet hours (20:00–07:00 IST)
   - the parent already had a `JOURNEY` turn today (IST)
   - today's nudge count has reached `NUDGE_DAILY_LIMIT`
2. Otherwise, create a `turns` row (`route = 'nudge'`, `status = 'completed'`, no inbox rows). The
   template part is built through the normal fixed path: `FixedReplyService.localise(NUDGE)` →
   `gate.clear_fixed` → `ReplyPartsBuilder.build` → `ReplyDelivery`. A `TEMPLATE` part is inserted by
   `OutboxRepository.enqueue`, with `NOTIFY outbox_new`.
3. Set `last_sent_at = now()` and `next_due_at` to the next day at `local_time` (IST).

So a nudge goes through the same sealed outbox path as every other message. The 24-hour window
check in the outbox loop **doesn't apply to `TEMPLATE` parts**; that's the one place templates differ.

### 4.12 Router rules for parents (implemented in s05)

| Rule | Route |
|---|---|
| `jrn:*` button ids | `JOURNEY` (no LLM) |
| `nudge:*` button ids | `JOURNEY` (settings, no LLM) |
| `role == PARENT`, `ACTIVE`, and an `open_activity` exists | `JOURNEY` by default; the LLM router may choose `OFF_TOPIC` |
| `role == PARENT`, `ACTIVE`, otherwise | LLM router over `{JOURNEY, OFF_TOPIC}`; `MENTOR`, `EXPOSURE` or `ROADMAP` from the LLM map to `JOURNEY` (documented policy, recorded in `reason`) |

### 4.13 Khoj card — Muse Image (decision C6)

After a parent reports back (flow B), Marg.ai sends an illustrated card of the child's discovery,
which parents forward to family groups. It shows what Meta's image model can do in a warm,
non-screen way, and every forwarded card carries Marg.ai to a new family.

```
post-turn task MakeKhojCard (after the reflection reply is delivered; never delays it)
  1. card text (deterministic + one small Muse Spark call → KhojCardText, strict schema):
       headline ≤ 60 chars  "Munni ne parchhai ka raaz khoja!"   (nickname only if the parent gave one)
       line ≤ 90 chars      what the child noticed, from the stored summary; no labels, no careers
  2. image (Muse Image, `MODEL_IMAGE`, POST /v1/images/generations, 1024×1024):
       prompt = fixed style template (warm Indian folk-art illustration, village setting, no text,
       no realistic faces, no identifiable child) + the activity's domain and setting. The child's
       name and the parent's words are NOT in the image prompt.
  3. safety_out on the image (Llama Guard 4 with `SafetyRequest.image`) and on the card text
       (the normal gate). Any failure → no card, recorded, nothing sent.
  4. the card text goes in the WhatsApp **caption** (forwarded together with the image), not
       inside the image: the model never draws text, so there's no misspelt Hindi and no new
       image-library dependency. Drawing text onto the image is a Phase 2 option
  5. a KHOJ_CARD system turn (like NUDGE): one IMAGE part with a caption, through the sealed
       path (gate.clear_fixed is NOT used: the image passed safety_out in step 3, so a SafeReply
       is built from that verdict)
  writes: media_blobs (khoj_card, 7 days), learner_activities.card_blob_id
```

- At most one card per learner per day, and only for reports with engagement ≥ 2, so cards stay special.
- Cost: about $0.01 per image plus one small text call.
- The card is sent only inside the open 24-hour window (the parent just wrote to us), so no template is needed.
- **Web demo:** the card appears in the chat, with a download button.
- Failure never affects the parent's reply. It's recorded as a `MAKE_CARD` `turn_steps` row.

### 4.14 Activity photos — SAM 3.1 (decision C7)

A parent may send a photo of what the child **made or collected** (leaves sorted by shape, stones
by size, a drawing). Marg.ai uses SAM 3.1 to count what's there, so the serve-and-return reply can
be specific ("Munni ne 7 alag patte dhoondhe! Sabse bada kaunsa hai?").

```
inbound IMAGE (WhatsApp "image" message, or a web upload)
  1. fetch_image (WhatsApp media download, size cap MAX_INBOUND_IMAGE_BYTES); kept in memory only
  2. PERSON CHECK FIRST: ImageSegmenter.count(image, ["person", "face"])
       any person or face → drop the image at once, fixed reply PHOTO_HAS_PERSON, no further
       processing. A hand counts: SAM's "person" finds a hand on its own (spike F), and a child's
       hand is still a child (owner, 2026-10-28; this replaces "a hand alone is allowed")
  3. safety_in on the image (Llama Guard 4 multimodal) → BLOCK → REFUSE, image dropped
  4. analyze_image: count the activity's reviewed `photo_count_phrases` (e.g. ["leaf"]; owner,
       2026-10-28: a reviewed list per activity, not the materials) → PhotoFindings(counts) →
       ActivityReported.photo_counts → learner_activities.photo_findings
       (3 and 4 run together; the counts are used only if Llama Guard allows the image)
  5. the reflection prompt receives the counts (as data), never the image
  the image bytes are discarded at the end of the turn; WhatsApp photos are never stored, and a
  web photo waits in media_blobs only until its turn has looked at it (owner, 2026-10-28)
```

- Photos are only accepted when there's an **open activity** for the learner. Otherwise the reply
  is the fixed `PHOTO_NOT_NEEDED`, which explains when photos help.
- Muse Spark is **not** sent the photo. Only counts reach the language model. This keeps the
  child's surroundings out of any generated text beyond what the parent wrote.
- Onboarding copy says photos of children aren't accepted, and the person check enforces it.
- `PHOTO_INPUT_ENABLED` turns the feature off at once if anything looks wrong in field testing.

### 4.15 Curiosity moment — mentoring the child's own question (C11)

Trigger: a parent relays the child's question or spark ("Munni poochh rahi hai, chaand roz shape
kyun badalta hai?"), detected deterministically by the journey dispatch (a question mark or
question words with a child reference: the nickname, "beta", "beti", "bachcha", "poochh rahi/raha")
and confirmed by the `curiosity_moment` prompt's `is_child_question` field. Otherwise → flow D.

Output (`CuriosityMoment`, strict schema, written in the parent's register, C3c):
- `say_to_child` ≤ 300 chars: a **true, simple answer** at the child's age. Only well-established
  everyday science, nature and how-things-work knowledge. When the model isn't confident,
  `confident = false` and the answer becomes "Chalo saath mein pata lagate hain" plus the mini-activity.
- `find_out_together`: a 2-minute mini-activity with household things (steps ≤ 4, materials from
  the closed materials list, hazard rule `d7`, the supervision line appended by code).
- `ask_back` ≤ 160 chars: one question that keeps the child wondering.
- `who_explores_this` ≤ 160 chars, optional: gentle exposure (C12), never "you should become".
- writes: none. Post-turn: `ExtractSignals(curiosity)` with `child_asked_question = true`.

Health, body or medicine questions are refused by safety and referred (d4), as everywhere.
Golden cases: moon phases, why it rains, why plants need sun, a fever question (referred), a
question the model can't answer confidently ("let's find out" path).

### 4.16 Child talk — the child asks Marg.ai directly (C13)

Children don't always say everything they wonder to a parent. With the parent's **one-time
consent**, the child can talk to Marg.ai themselves on the parent's phone, by voice.

**Why the parent is still involved at all:** 3–8-year-olds use the parent's phone and WhatsApp
account (WhatsApp's minimum age is 13 in most countries); India's DPDP Act requires verifiable
parental consent for a child's data and restricts behavioural monitoring of children (a legal
review is required before any public launch, see plan.md §8); and an adult must be able to act if
a child says something worrying. So the parent consents once and receives a summary; they are
**not** in the middle of the conversation.

```
consent (once, s08): after the child's details, "Kya Munni khud bhi Marg se baat kar sakti hai?"
   yes → learners.child_talk_consented_at, consent_events CHILD_TALK_CONSENT
start (by the child): the "Main bachcha hoon 🙋" button (kid:start[:<learner_id>]) shown on journey
   replies, or a voice note "Main Munni hoon" / "Munni bol rahi hoon" (nickname match)
   → ChildSessionStart write → child_sessions row (open)
during: speaker = LEARNER; every turn → child_talk prompt → ChildReply; voice reply always
end: after CHILD_SESSION_MAX_TURNS (6) or CHILD_SESSION_MAX_MINUTES (10), or "bye"/"bas":
   a kind fixed goodbye + one "go find out" activity + "Mummy-Papa ko bhi batao!"
   → ChildSessionEnd write; then a summary for the parent (post-turn): "Aaj Munni ne poochha: …"
```

**`ChildReply`** (strict schema, child register: very short sentences, ≤ 8 words each for ages 3–5,
≤ 12 for 6–8; spoken first, text second): `answer` (true and simple, or "let's find out"),
`find_out` (an optional 1-minute thing to try, same materials and hazard rules), `ask_back` (one
question), `who_explores_this` (optional, C12).

**Safeguards (hard lines; deterministic checks plus the normal safety gate):**
- **Never asks the child for personal information** (name beyond the nickname, school, address,
  phone, family details, photos). An output rule blocks question patterns for these (`d1` on output).
- **Never secrecy or attachment:** no "keep this secret", "don't tell", "I'm your best friend",
  "only I understand you". A lexicon rule blocks them (new category `d8 CHILD_MANIPULATION` on output;
  lexicon sections `[child_manipulation]` and `[child_personal_questions]` in `app/safety/lexicon.toml`, owned by s07).
  Replies regularly say "Mummy-Papa ko bhi batana".
- **Crisis in a child's words:** self-harm or abuse signals → the fixed `CRISIS` reply in the
  **child variant** (simple words: "Yeh tumhari galti nahi hai. Abhi Mummy, Papa ya teacher ko
  batao.", plus the official child helpline, copied from the official source), and the session ends.
  The parent summary then says only that Marg.ai shared a helpline, never the child's words.
- **Medical and body questions** → refused and referred to a grown-up (d4, child wording).
- **Time limits** as above; no new session for 30 minutes after one ends (`CHILD_SESSION_COOLDOWN_MINUTES`).
- **Voice-first:** replies are voice notes plus very short text; no links, no images other than the khoj card.
- **Nothing stored beyond the normal turn data;** the child's voice is never stored. `turns.user_text`
  retention is the same as for parents, and crisis turns store none.

**Crisis endings (C15):** after an **abuse disclosure** (d5), **no summary is sent to the parent at
all**. The child gets the fixed child-worded reply with the official child helpline, and the session
ends quietly, because the adult reading the parent's phone may be the one causing harm. After a
**self-harm or deep-sadness** signal (s11), the parent gets a fixed, gentle summary ("Munni aaj udaas
lag rahi thi, pyaar se baat kijiye") plus the official helpline for adults, never the child's words.

**Account actions from a child (C16):** inside a child session, nothing changes the account:
deletion phrases, nudge settings, add-child, consent and any non-`kid:` button are ignored, and
the child hears a fixed "Yeh Mummy-Papa se karwana". The parent can do it after the session ends.

**Parent summary** (post-turn task `SendChildSessionSummary`, fixed wording plus the topics in
≤ 2 lines, sent inside the open 24 h window): what the child asked about (topics, not transcripts),
and one suggestion to continue together. Never quotes a disclosure.

## 5. Interfaces

```python
# app/domain/stages.py
def age_on(birth_year: int, today: date) -> int: ...
def age_band(birth_year: int, today: date) -> AgeBand: ...

# app/domain/learners.py  (called by s04's load_turn_context; rules 1–3 of §4.2)
def choose_active_learner(learners: Sequence[Learner], messages: Sequence[InboundMessage],
                          recent_offered: Sequence[OfferedActivity]) -> Learner | None: ...
    # None with ≥ 2 learners and no signal → the journey layer asks "which child?" (rule 4)

# app/domain/activities.py
class Activity(BaseModel): ...            # §4.3 fields, frozen, extra="forbid"
class PastActivity(BaseModel): activity_id: str; domains: list[CuriosityDomain]; offered_at: datetime; status: ActivityStatus
class OfferedActivity(BaseModel): learner_activity_id: UUID; learner_id: LearnerId; activity: Activity; offered_at: datetime
def validate_activity(raw: Mapping[str, JsonValue], materials: frozenset[str], hazards: frozenset[str],
                      lexicon: Lexicon) -> Activity: ...   # raises CorpusValidationError
def choose_activity(candidates: Sequence[Activity], history: Sequence[PastActivity],
                    signals: Sequence[CuriosityPoint], today: date) -> Activity | None: ...
def season_of(today: date) -> Literal["summer", "monsoon", "winter"]: ...

# app/layers/activity_catalogue.py
class CatalogueActivitySource:            # satisfies ActivitySource
    def __init__(self, catalogue: Sequence[Activity]) -> None: ...
def load_catalogue(root: Path, lexicon: Lexicon) -> list[Activity]: ...   # startup; raises CorpusValidationError

# app/layers/journey.py
class JourneyLayer:
    def __init__(self, llm: LanguageModel, prompts: PromptRegistry, source: ActivitySource,
                 settings: Settings, clock: Clock) -> None: ...
    async def handle(self, ctx: TurnContext, user_text: str) -> LayerResult: ...   # dispatches flows A–E

# TurnWrite variants (app/domain/writes.py)
class LearnerUpsert(BaseModel):      kind: Literal["learner_upsert"]; learner_id: LearnerId; relation: LearnerRelation
                                     # learner_id is generated by the layer (uuid4) for a new learner, so a
                                     # same-turn handoff (first khoj) can already refer to it
                                     nickname: str | None; birth_year: int
class ActivityOffered(BaseModel):    kind: Literal["activity_offered"]; learner_id: LearnerId; activity_id: str; activity_version: str
class ActivityReported(BaseModel):   kind: Literal["activity_reported"]; learner_activity_id: UUID; status: ActivityStatus
                                     summary: str | None
class NudgePreference(BaseModel):    kind: Literal["nudge_preference"]; enabled: bool; local_time: time | None

# app/worker/nudges.py
class NudgeLoop: async def run(self, stop: asyncio.Event) -> None: ...

# app/store/repositories/journey.py
async def recent_activities(session, learner_id: LearnerId, limit: int) -> list[PastActivity]: ...
async def open_activity(session, learner_id: LearnerId, since: datetime) -> OfferedActivity | None: ...
async def claim_due_nudges(session, limit: int) -> list[UserHash]: ...
```

`LayerResult` is s12's shared generate-handler result (`reply`, `writes`, `usages`, `prompt_versions`, `outcome`).

## 6. Data

- **Migration `s10b_journey`:** creates `learner_activities` and `nudge_subscriptions`; adds
  `turns.learner_id`. (`learners` is created by s08's migration, so onboarding can store the child.)
- **Writes** (all through `TurnWrite`s in the finalize transaction): `learner_activities`,
  `nudge_subscriptions`, `learners` (via s08). `NudgeLoop` writes `turns`, `outbox_messages` and
  `nudge_subscriptions` in its own transaction.
- **Reads:** `learners`, `learner_activities`, `curiosity_signals` (for selection), `nudge_subscriptions`.
- **Files:** `content/activities/*.yaml`, `_materials.yaml`, `_hazards.yaml`, loaded at startup.

## 7. Configuration

`MODEL_TEXT`, `TIMEOUT_GENERATE_S`, `NUDGE_TEMPLATE_NAME`, `NUDGE_QUIET_START` / `NUDGE_QUIET_END`,
`NUDGE_DAILY_LIMIT` (200), `ACTIVITY_REPEAT_DAYS` (30). Prompt settings live in frontmatter:
`activity_personalise` and `parent_reflection` at `reasoning_effort="low"`, 600 tokens;
`parent_answer` at `"low"`, 700 tokens.

## 8. Failure modes

| Failure | Parent sees | Recorded |
|---|---|---|
| Personalisation fails or fails its checks twice | the reviewed catalogue text, unmodified | `GENERATE` `DEGRADED`, `catalogue_fallback` |
| Reflection fails | a fixed warm acknowledgement plus the activity's first question again | `GENERATE` `DEGRADED` |
| No candidate activity (catalogue exhausted for this age) | the oldest-offered activity again | `detail="repeat_allowed"` |
| Child's age outside 3–8 | the fixed "coming soon for this age" reply plus one general tip | `detail="stage_not_supported"` |
| `d7` hazard in a personalised reply | the catalogue text instead | `safety_out` `decision=block;categories=d7`, then fallback |
| Catalogue file invalid | — (deploy fails) | `CorpusValidationError` at startup |
| Template send fails (not approved, 131xxx) | no nudge today; the parent can still ask | outbox `failed`, log `error` with code |
| Nudge daily limit reached | the nudge moves to tomorrow | `detail="nudge_limit"` |
| Several children, none identifiable | a "which child?" question with buttons | `detail="ask_learner"` |

## 9. Tests

**Unit**
- `age_band` boundaries: ages 2, 3, 8, 9, 11, 14, 18, and a future birth year → `InvalidProfileValue`
- `validate_activity`: each rule in §4.3 rejects a crafted file with a message naming the field (unknown material, undeclared hazard word in steps, a purchase word, age_max 9, enabled without review fields)
- the shipped catalogue loads, every enabled activity validates, ≥ 7 are enabled, ≥ 6 domains are covered, and ≥ 3 are indoors
- `choose_activity`: excludes recent repeats; rotation prefers unseen domains; the engagement boost applies at most once in 3; deterministic tie-break
- `season_of` for each month
- personalisation `semantic_check`: step count mismatch, a new hazard word, "doctor ban jaayega", "genius" → each rejected; catalogue fallback used after the second failure
- the supervision line is present in every flow A reply, after translation (fake translator)
- active-learner choice: the 4 rules in §4.2, in order
- router rules in §4.12, including `MENTOR` from the LLM for a parent → `JOURNEY` with the reason recorded
- nudge preference parsing: `nudge:08`, `nudge:18`, `nudge:off`, "roz ka message band karo", "time badlo"

**Property (hypothesis)**
- `choose_activity` never returns an activity outside the learner's age range, never returns one
  offered within the repeat window when another candidate exists, and is deterministic.
- Over any simulated history as long as the catalogue (one activity a day), every domain the
  catalogue covers appears at least once (breadth by construction).
- `NudgeLoop` scheduling (pure function `next_due(local_time, now)`): never in quiet hours, at
  most one per IST day, and `next_due > now`.
- The `d7` rule: a hazard word found in `t` is found in `prefix + t + suffix` (detection survives context).

**Negative**
- A parent asks for medicine for a fever → REFUSE `MEDICAL` (parent wording), no generation.
- A parent writes about the child being hurt by an adult → crisis `ABUSE` reply.
- A personalisation that adds "go to the pond" → blocked, catalogue text sent.
- A parent sends a nickname longer than 20 characters or a full name pattern (two capitalised words) → s08 asks for a short nickname; nothing is stored.
- `jrn:done` with no open activity → handled as a parent question, no write.

**Integration**
- The `s10b_journey` migration upgrades, downgrades and upgrades again.
- `ActivityOffered` and the outbox rows commit atomically (an injected outbox failure leaves no `learner_activities` row).
- `NudgeLoop` with two worker processes sends exactly one template per due subscription.
- User deletion removes learners, learner_activities, nudge_subscriptions and curiosity_signals.

**Khoj card and photos (§4.13–4.14)**
- Unit: the card prompt never contains the nickname or the parent's words; the person check runs before any other image step (call order in the fake); a person count > 0 → `PHOTO_HAS_PERSON` with no `analyze_image` call and no write; photos without an open activity → `PHOTO_NOT_NEEDED`; at most one card per learner per day; engagement < 2 → no card.
- Property: for any fake segmenter output containing a person, no image byte is retained after the turn and no `photo_findings` is written.
- Integration: no `media_blobs` row or column ever holds an inbound photo (scan after a photo turn).

**Evals:** `evals/golden/parent_journey.yaml` (age fit, free materials, no hazards, serve-and-return
specificity, no careers for a 5-year-old, medical refusal, register).

## 10. Exit check

1. From a new number: consent → "Main parent hoon" → "beti, 5 saal, Munni" → within the same turn,
   the first khoj arrives as voice plus text, using "Munni", with the supervision line and the three nudge buttons.
2. Tap "Subah 8 baje". Then set `next_due_at` to now on the test database: within a minute the
   template arrives; tapping its button brings today's khoj (a different activity).
3. Send a voice note: "Munni ne kaha parchhai suraj ki wajah se ghoomti hai". The reply praises that
   specific idea and asks one extending question. `learner_activities` shows `done` with a short
   summary, and `curiosity_signals` has a row with `earth_sky`.
4. Ask "Munni ko bukhar hai, kaunsi dawai doon?" → the fixed medical referral, no advice.
5. "Doosri khoj" → a different activity in a different domain.
6. Send a photo of 7 leaves → the reflection mentions the number; send a selfie → `PHOTO_HAS_PERSON`, nothing stored.
7. After a good report, a khoj card arrives as an image with a caption; forwarding it works.
8. `marg eval --file parent_journey.yaml` passes. The verification loop is green.

## 11. Open questions

| # | Question | Recommendation |
|---|---|---|
| Q1 | Who reviews the activities? | The owner, plus one parent and one anganwadi worker or teacher during S0–S10b. Record the role and date on each file. |
| Q2 | Template category and price per message in India | Create it in S10b and record Meta's category and current per-message price in `docs/decisions/`. Keep the daily limit at 200 until verification raises the cap. |
| Q3 | Should a parent's child also get a `self` link when they later get their own phone? | Post-MVP: a learner link table with a verification step. The data model already keys trajectories by learner, so nothing needs migrating. |
| Q4 | Should the web demo show the journey? | Yes: the demo has a "Parent" onboarding option, and the reply includes a "Aaj ki khoj" button instead of a nudge (no proactive messages on web). |

## 12. Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-28 | **d7: talk about it, never do it.** In the curiosity moment and child talk, a hazard the child's own question names (snake, scorpion, fire, river, road…) may be talked about in the answer, with "only look or talk about it with a grown-up"; the find-out activity may never involve any hazard; medicine is never discussed (`NEVER_TALK_ABOUT`, referral instead). `ChildHazardMatcher.asked_about` sets the layer's `hazard_rule`, so the d7 reply check allows exactly those kinds. curiosity_moment 1.0.2, child_talk 1.0.2 | Pending decision since 2026-10-27 ("saanp ke kaan kahan hote hain?" couldn't be answered). Owner: "yes they can reply about these" (option b) | owner |
| 2026-10-28 | **Summary for a session the child left (§4.16).** Maintenance now sends the parent's summary for every session closed as EXPIRED (`ChildSessionSummarySender`, `app/worker/child_session_summary_sender.py`; `ChildSessionRepository.due_summaries` / `queue_summary`): the same reviewed wording and topic labels as at a goodbye (`ChildTalkLayer.parent_summary`), never the child's words, **text only**, sealed through `SafetyGate.clear_fixed` as `CHILD_SESSION_END` (no model wrote any of it; the nickname is the parent's own ≤ 20-character entry), queued as a `child_talk` turn in the parent's own channel. `summary_sent_at` is claimed in the same transaction, so two workers send it once. Only inside WhatsApp's 24-hour window (the web has none); older ones are never sent. A crisis-ended session never gets one | Replaces "waits for a turn-less sender" from 2026-10-27; owner's build order, step 6 | pending owner review |
| 2026-10-27 | **S10b core built** (owner: all of s10b in one step, S6 voice inside it; this is the first part). Names under the code-organisation rule: `StageRules`, `ActivityValidator`, `ActivityChooser`, `LearnerChooser`, `ChildHazardMatcher` (domain rules), `ActivityCatalogue` + `CatalogueActivitySource`, `JourneyLayer`, `JourneyRepository`, d7 words in `app/constants/child_hazards.py`. Replies written in the parent's register (C3c, no translate step); routing deterministic (C3b): `jrn:` buttons → JOURNEY, other parent text → JOURNEY, where the layer picks A–D. The context carries `OfferRecord`s (`open_activity`, `activity_history`) and the layer resolves them through the catalogue, since the store can't import it. Personalisation falls back to the reviewed catalogue text (English) on any failure; a blocked journey reply falls back to it too. `jrn:done` with nothing open offers today's khoj (not a parent question). The d7 rule runs on every journey reply, flow D included, before any provider call. Reflection on Muse Spark Open with a 7 s limit, then Spark 1.3 (`FallbackLanguageModel`). YAML via PyYAML 6.0.3 (owner). `photo_findings`, `card_blob_id` and `turns.learner_id` wait for their features. 10 activities drafted by Claude, enabled as reviewed by the owner pending a village review; `dough-shapes` v2 ("snake" of dough → "rope", the d7 word list caught it) | Owner decisions at the S10b review | owner (scope, Open 7 s, review, YAML, template); copy, prompts and word lists pending review |
| 2026-10-26 | C15: no parent summary after an abuse disclosure; gentle summary after self-harm signals. C16: no account actions from a child session | Owner decisions on the fork's safety questions | owner |
| 2026-10-26 | Curiosity moment (§4.15), gentle exposure (principle 4), direct child talk with one-time parent consent and safeguards (§4.16) | Owner decisions C11, C12, C13: Marg.ai mentors the child's own curiosity; children don't always say everything to a parent | owner |
| 2026-10-26 | Reflection on Muse Spark Open via Baseten with fallback | Decision C9 | owner |
| 2026-10-26 | Khoj card with Muse Image (§4.13) and activity photos with SAM 3.1 (§4.14) | Owner decisions C6, C7: Use of Meta AI Tooling is 25% of the score (Official Rules) | owner |
| 2026-10-25 | Launch catalogue 10 activities (minimum 7); deterministic flow dispatch for the MVP | Decisions C4 and C3b (mvp-scope.md) | owner |
| 2026-10-25 | v1: parent journey for ages 3–8, daily opt-in template nudges, nickname + birth year only, curated catalogue with LLM personalisation, designed to move to guarded full generation | Owner decision (build a person from inception) | owner |
| 2026-10-27 | **Curiosity moment built (§4.15).** The trigger is stricter than written: a question (a question mark or a question word) AND a sign it's the child's question (an asking word such as "poochh rahi", "asked", "पूछ", or the child's nickname); "beta"/"bachcha" alone with a question stays a parent question (flow D), so most parent questions don't pay for two model calls. While a khoj is open, the child's words are a report first (flow B). `CuriosityMoment` adds `materials_used` (checked against the closed materials list) and every field is required (empty when not a child's question); the unsure path's opening line is fixed copy (`LETS_FIND_OUT`). An answer that fails its checks twice gets a fixed serve-and-return reply (`CURIOSITY_FALLBACK`, DEGRADED): live, a question about a snake's ears fails because d7 blocks the word | Build choices; the d7-on-topic question is for the owner (review list) | pending owner review |
| 2026-10-27 | **Child talk built (§4.16).** Writes `ChildSessionStart`, `ChildTalkTurn` (new: counts a turn and records its topic as a `CuriosityDomain`) and `ChildSessionEnd`. At most one open session per **account** (the design said per learner): one phone, one child talking. The parent's summary goes in the same message as the child's goodbye, written only (never spoken), instead of a post-turn task; a session the child leaves without "bye" is closed as EXPIRED by maintenance and its summary waits for a turn-less sender (nudges). A start message that also asks something is answered as turn 1. Child turns use the family's onboarding language rather than re-detecting each short message. With `CHILD_TALK_ENABLED=false` a `kid:` button gets REPEAT_PLEASE and journey replies don't offer it. Fixed child copy (`child_talk_copy.py`) is spoken from Hindi for Hinglish, without the nickname (Roman letters can't be spoken by the Hindi voice) | Build choices | pending owner review |
| 2026-10-27 | **Nudges built (§4.11).** The opt-in question comes as its own message after the first khoj (a message holds at most 3 buttons, and the khoj already uses up to 3). Sending runs in the worker's maintenance pass (`NudgeSender`, every 30 s) rather than a separate 60 s loop, with `now` from the worker's clock. Three templates: `marg_daily_khoj` in hi and en, `marg_daily_khoj_hinglish` submitted as en (Meta has no Hinglish code). `NUDGES_ENABLED` (default false) keeps sending off until Meta approves them; opt-ins are recorded either way. The "Main khud poochunga" button is "Khud poochhenge" (gender-neutral, like all copy) | Build choices | pending owner review |
| 2026-10-27 | **Khoj card built (§4.13).** The card is a post-turn task after the signals (the same turn's engagement decides, ≥ 2), at most one per child per India day. The image style and per-activity scenes are reviewed constants (`app/constants/khoj_card_style.py`, from spike F), not a prompt file: they're a fixed string, never rendered. Muse Image's PNG (about 5 MB live) is re-encoded by ffmpeg to an 800-pixel JPEG (about 210 KB): over the 2 MB `media_blobs` cap otherwise, and no new dependency. Safety on the card: the caption gets d8 and d7, then Llama Guard sees caption and image together in one user turn (spike B); there is no backup for images, so Llama Guard down or any flag means no card. Live 2026-10-27: card made in 18 s (caption + image), safety 2.6-4.9 s, allowed; the image was a textless folk-art triptych of the shadow through the day | Build choices | pending owner review |
| 2026-10-28 | **Photos: three owner decisions after spike F (SAM 3.1).** (1) Any person refuses a photo, a hand included: SAM's `person` finds a hand alone (0.93), so "a hand alone is allowed" couldn't hold. (2) Web photos are held in `media_blobs` (purpose `inbound_photo`) only until their turn has looked at them, deleted in finalize, at most 10 minutes; the rule becomes "never kept beyond its turn". (3) What to count is a reviewed `photo_count_phrases` list per activity (leaf-families, stone-tower, shadow-time: stone/leaf; sink-or-float: stone, leaf, bottle cap; the rest count nothing), not the materials | Spike F findings, docs/spikes/images.md | owner |
| 2026-10-28 | **Photos built (§4.14).** A photo is looked at only on the journey route with a khoj open; otherwise PHOTO_NOT_NEEDED (photo alone) or the words are answered and the photo ignored (with a caption). A parent's photo with no words routes to the journey (`TurnFacts.has_photo`), and counts as the report ("Ho gaya"). The caption is the parent's words (safety_in like any text). Only the latest photo of a burst is looked at. Any failure (fetch, the person check, Llama Guard down, counting) drops the photo and the report goes on: the reflection thanks the parent without a number (`photo_counts == []`). A Llama Guard flag on the image → the generic REFUSE. Counts reach `parent_reflection` (v1.1.0) as system data, never the image. Step rows: FETCH_IMAGE, ANALYZE_IMAGE (`person_check=pass/reject`, then `stone=5`), SAFETY_IN (`photo decision=…`) | S10b photo build | pending owner review |
