# Pending owner review (Santram)

Everything built or decided so far that waits for the owner's review. Tick an item when it's
reviewed; anything changed goes into that step doc's Decisions log in the same commit.

Last updated: 2026-10-27 (after the S5 and S8 phone checks; both ticked in plan.md, pending this review).

## 1. Safety host (decided 2026-10-27)

- [x] Groq retired Llama Guard 4 (2026-03-05); the owner chose **DeepInfra**
  (`meta-llama/Llama-Guard-4-12B`, $0.18/1M). NVIDIA's free endpoint was ruled out for real users
  (trial terms: no production use, content may be used to improve NVIDIA products).
- [x] DeepInfra balance added; spike B run (`docs/spikes/safety-guard.md`).
- [x] Spike B follow-up decided: crisis phrase rules + Muse Spark policy check on every user
  message; Llama Guard S1/S2/S4 need confirmation, S11 always counts; token cap 800. The full
  check got 36/36 right on two runs.
- [x] WhatsApp token replaced with a permanent System User token (2026-10-27).
- [x] **S5 phone check passed** (2026-10-27): Hinglish, Hindi and English questions answered with
  every reply checked; voice note → "can't read this yet". It surfaced two Llama Guard problems,
  both now covered (below and s07 log): DeepInfra timeouts and overload, and a harmless answer on
  teaching colours flagged with a different code each time (S2, S4, S8).
- [x] DeepInfra is the only production host for Llama Guard 4, and it failed on day one (timeouts,
  then `429 engine_overloaded`). Decided: Muse Spark backs it up (s07 log, CLAUDE.md §11).
- [x] A Llama Guard flag on our reply gets a Muse Spark second opinion before blocking (s07 log).
- [ ] **Review the safety behaviour you approved today** in `app/safety/safety_gate.py`'s
  docstring and the s07 decisions log: Llama Guard's 1.5 s limit, the Muse Spark backup on both
  sides, the second opinion on reply flags, and `TIMEOUT_SAFETY_OUT_S` 6 s.

## 2. S5 copy (users read these words)

- [ ] Crisis replies, `app/constants/crisis_replies.py`: SELF_HARM (Tele-MANAS 14416, source
  pib.gov.in) and ABUSE (Child Helpline 1098, source wcd.gov.in), each in Hinglish, Hindi and
  English. 112 is left out until it's copied from an official page that states it (S7).
- [ ] Fixed replies, `app/constants/fixed_replies.py`: TRY_AGAIN_LATER, HOLDING, REPEAT_PLEASE,
  UNSUPPORTED_MEDIA, REFUSE (HARMFUL, PRIVACY, MEDICAL, GENERAL, GENERIC). Wording avoids
  gendered verbs, since a parent may be a mother or a father.
- [ ] **Crisis phrase list**, `app/constants/crisis_lexicon.py` (v1): self-harm phrases and
  the abuse people/harm lists in Hindi, Hinglish and English. Recall first; brothers and
  cousins left out so sibling fights stay parenting questions. Ideally also checked by a
  counsellor or teacher (s07 Q2).
- [ ] **Backup reply check prompt**, `app/prompts/reply_policy.md.j2` (v1.0.0): used only when
  Llama Guard is down; what counts as harmful, self-harm, medical instructions, or endangering a
  child.
- [ ] **Safety policy prompt**, `app/prompts/minor_policy.md.j2` (v1.0.1): what counts as a
  self-harm signal, an abuse disclosure, a medical request, and a harmful request.
- [ ] Known false positive you accepted: "pakka IAS ban jaunga na?" gets the crisis reply when
  Llama Guard tags it S11.
- [ ] The parent-answer prompt, `app/prompts/parent_answer.md.j2` (v1.0.0): warm and play-based,
  one thing to try today, no medical advice, no facts or figures, no labelling a child, and the
  parent's message treated as data.
- [ ] Optional: show these texts to two or three parents in the village and note what reads oddly.

## 2b. S8 onboarding (built 2026-10-27)

- [x] `WHATSAPP_DISPLAY_NUMBER` set in `.env` from the account's own number (read from Meta with
  the new token, 2026-10-27).
- [x] **S8 phone check passed for parents** (2026-10-27): consent → parent → child (nickname and
  birth year only) → child-talk consent; "mera data hatao" → confirm → every table empty for that
  user, purged right after the reply was delivered.
- [ ] **Teacher path on the phone** (covered by tests only): after `Hi` and consent, tap **Main
  teacher hoon**, answer subject, class and district, and check the invite link opens a chat
  with Marg with "Namaste Marg" typed in.
- [ ] **Onboarding copy**, `app/constants/onboarding_copy.py` (`onb-2026-10-27.1`): the consent
  intro (the legally important text), the role question (parent / teacher), student "coming
  soon", the child question, child-talk consent, the teacher invite and waiting messages, the
  deletion confirmation, in Hinglish, Hindi and English. Hinglish comes from s08; Hindi and
  English are translations, and the MVP-only entries are new.
- [ ] **Profile extraction prompt**, `app/prompts/profile_extraction.md.j2` (v1.1.0).
- [ ] Known limit: if a user taps two onboarding buttons faster than one turn, only the last
  counts (the first is asked again).

## 2c. S10b parent journey (from 2026-10-27)

- [ ] **The 10 launch activities**, `content/activities/*.yaml`: enabled on 2026-10-27 as
  "reviewed by: owner" so building could start. Still to do: a real read by the owner, then a
  village review by a parent and an anganwadi worker or teacher; any change bumps `version`.
- [ ] **Journey copy**, `app/constants/journey_copy.py`: the supervision line, the "Poochiye /
  Dhyan dijiye" labels, the khoj buttons, "which child?", "coming soon for this age", the
  reflection fallback. Three languages.
- [ ] **Prompts**: `activity_personalise.md.j2` (v1.0.2) and `parent_reflection.md.j2` (v1.0.0).
  Live check 2026-10-27: personalisation fine in all three languages (3.5-4.1 s); reflections on
  Muse Spark Open were specific and warm, including for a child who refused (4-6 s).
- [ ] **Word lists**: child hazards (`app/constants/child_hazards.py`, the d7 rule) and words a
  khoj or reflection may not use (`journey_words.py`: careers, exams, labels for a child).
- [ ] Known behaviour to accept or change: the d7 rule also runs on parent answers, so an answer
  that warns about a road or fire ("keep her away from the road") is blocked and replaced with
  the generic redirect.
- [ ] **Submit the nudge templates** in WhatsApp Manager (`marg_daily_khoj` in hi + en,
  `marg_daily_khoj_hinglish` in en; text in the chat of 2026-10-27) and note the category Meta
  gives them.

## 3. Decisions log entries marked "pending owner review"

- [ ] `docs/design/s05-llm-orchestrator.md`, 2026-10-27 (S5 build choices).
- [ ] `docs/design/s07-safety.md`, 2026-10-27 (crisis copy pulled forward; safety host).
- [ ] `docs/design/contracts.md`, 2026-10-27 (S5 ports, `SaveResult`, `MODEL_REASONING_EFFORT`).
- [ ] `docs/design/contracts.md`, 2026-10-25 (`TurnObserver.on_step` result, `GoldenLearner`,
  `SignedTokenCodec`, the `ExtractSignals`/`UpdateMemory` fields).

## 4. Spike decisions still open

- [ ] Spike F images: GO at `low` effort (0.2 s over the latency bar). Recommended GO.
- [ ] Khoj cards: GO (`KHOJ_CARD_ENABLED=true`).
- [ ] Muse Spark Open: a cap of about 7 s per attempt.
- [ ] Spike F SAM 3.1 (person check and counting): waiting for photos (see
  `docs/spikes/sample-collection-hi.md`).
- [ ] Spikes A (speech-to-text) and C (text-to-speech): waiting for voice samples.
- [ ] **Voice sample spec:** `docs/spikes/samples.md` was written for students and teachers
  (grades 6–12), before the MVP became the parent journey (children 3–8). Should some of the
  10 samples be parents asking about young children instead?

## 5. Housekeeping

- [x] Pushed `main` on 2026-10-27 (S5, S8, the safety backup, Muse's spike E/F); CI green.
- [x] Muse committed its spike E/F files (`5ec4490`).
- [ ] If hackathon time allows: the Aspirational engine slice (s11/s12).
