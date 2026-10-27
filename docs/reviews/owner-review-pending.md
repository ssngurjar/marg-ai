# Pending owner review (Santram)

Everything built or decided so far that waits for the owner's review. Tick an item when it's
reviewed; anything changed goes into that step doc's Decisions log in the same commit.

Last updated: 2026-10-27 (after S5 was built).

## 1. Safety host (decided 2026-10-27)

- [x] Groq retired Llama Guard 4 (2026-03-05); the owner chose **DeepInfra**
  (`meta-llama/Llama-Guard-4-12B`, $0.18/1M). NVIDIA's free endpoint was ruled out for real users
  (trial terms: no production use, content may be used to improve NVIDIA products).
- [x] DeepInfra balance added; spike B run (`docs/spikes/safety-guard.md`).
- [x] Spike B follow-up decided: crisis phrase rules + Muse Spark policy check on every user
  message; Llama Guard S1/S2/S4 need confirmation, S11 always counts; token cap 800. The full
  check got 36/36 right on two runs.
- [ ] S5 phone exit check.
- [ ] Note: DeepInfra is the only production host for Llama Guard 4 found, so it is a single
  point of failure; an outage means every turn gets HOLDING. Revisit in S16 hardening.

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
- [ ] **Safety policy prompt**, `app/prompts/minor_policy.md.j2` (v1.0.1): what counts as a
  self-harm signal, an abuse disclosure, a medical request, and a harmful request.
- [ ] Known false positive you accepted: "pakka IAS ban jaunga na?" gets the crisis reply when
  Llama Guard tags it S11.
- [ ] The parent-answer prompt, `app/prompts/parent_answer.md.j2` (v1.0.0): warm and play-based,
  one thing to try today, no medical advice, no facts or figures, no labelling a child, and the
  parent's message treated as data.
- [ ] Optional: show these texts to two or three parents in the village and note what reads oddly.

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

- [ ] Muse commits its uncommitted spike files: `docs/spikes/structured-output.md`,
  `scripts/spikes/structured_output_eval.py`, `scripts/spikes/image_eval.py`.
- [ ] Push `main` after this review (the S5 commit is local until then).
- [ ] S5 exit check on the phone, once item 1 is decided; then tick S5 in `plan.md`.
- [ ] If hackathon time allows: the Aspirational engine slice (s11/s12).
