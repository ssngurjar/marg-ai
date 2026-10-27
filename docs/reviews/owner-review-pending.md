# Pending owner review (Santram)

Everything built or decided so far that waits for the owner's review. Tick an item when it's
reviewed; anything changed goes into that step doc's Decisions log in the same commit.

Last updated: 2026-10-27 (after S5 was built).

## 1. Decision needed now: the safety host

- [ ] **Llama Guard 4 is gone from Groq.** A live check on 2026-10-27 returned
  `400: The model meta-llama/llama-guard-4-12b has been decommissioned`. The Groq key now lists
  only `meta-llama/llama-prompt-guard-2-22m`/`-86m` (prompt-injection detectors, not content
  safety) and `openai/gpt-oss-safeguard-20b`. Until this is decided, every live turn gets the
  HOLDING reply (fail closed), so the S5 phone exit check is blocked. Options:
  - **A (recommended):** another OpenAI-compatible host that serves Llama Guard 4 (Together,
    Fireworks, DeepInfra; spike B §4.3 measures them). Config change only: `SAFETY_BASE_URL`,
    `SAFETY_MODEL`, `SAFETY_API_KEY` and its price in `app/constants/model_prices.py`. Keeps a
    Meta safety model.
  - **B:** Groq `openai/gpt-oss-safeguard-20b`. It follows a written policy instead of the
    S1–S14 codes: a new adapter, a policy prompt, a new parser and a s07 design change. Not a Meta
    model.
  - **C:** Llama Guard 4 on Modal + vLLM (spike B's documented fallback). Cold starts, a GPU
    bill, and it must be kept warm during judging.

## 2. S5 copy (users read these words)

- [ ] Crisis replies, `app/constants/crisis_replies.py`: SELF_HARM (Tele-MANAS 14416, source
  pib.gov.in) and ABUSE (Child Helpline 1098, source wcd.gov.in), each in Hinglish, Hindi and
  English. 112 is left out until it's copied from an official page that states it (S7).
- [ ] Fixed replies, `app/constants/fixed_replies.py`: TRY_AGAIN_LATER, HOLDING, REPEAT_PLEASE,
  UNSUPPORTED_MEDIA, REFUSE (HARMFUL, PRIVACY, MEDICAL, GENERAL, GENERIC). Wording avoids
  gendered verbs, since a parent may be a mother or a father.
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
