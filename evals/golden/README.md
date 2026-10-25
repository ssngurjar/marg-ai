# Golden evaluation cases (draft, S0)

Hand-written cases that `marg eval` (S15) runs through the real pipeline. They're drafted now so
every layer is built against known expectations from the start.

**The format is provisional.** S15 turns it into a Pydantic model, and these files will be
migrated to match it. Until then, keep to the shape below.

## Case shape

```yaml
- id: teacher-exposure-001         # unique, stable, never reused
  title: short human description
  profile:                         # the user's onboarded profile; omit for a brand-new user
    role: teacher | student
    grade: 8
    subject: science               # teachers only
    district: Barmer, Rajasthan
    language: hindi | hinglish | english
  turns:                           # what the user says, as the transcript of a voice note
    - user: "…"
  expect:
    route: exposure | mentor | roadmap | onboarding | refuse | crisis | off_topic
    register: hindi | hinglish | english   # the language the reply must come back in
    safety: pass | block_in | block_out
    fixed_reply: crisis | holding | repeat_please   # when the reply must be fixed text, not generated
    must:                          # rubric statements the LLM judge checks
      - …
    must_not:
      - …
```

## Rules for writing cases

- `must` and `must_not` describe **behaviour**, not exact wording.
- **Never put a fact in an expectation** (an amount, a date, an age limit). Write "states the
  amount and cites a retrieved source" instead. The source is the authority, not this file.
- Inputs are written the way people actually speak: mixed script, filler, spelling variation.
- Every bug found in testing becomes a new case here.
- No real user conversations go in this folder (CLAUDE.md §13).

## Files

| File | Covers |
|---|---|
| `teacher_exposure.yaml` | Exposure layer: chapter → real-world fields |
| `student_mentor.yaml` | Mentor answers, grounding and the honest "I don't know" path |
| `roadmap.yaml` | Roadmap generation and follow-ups |
| `translation.yaml` | Register matching, spoken text, cultural fit |
| `onboarding.yaml` | Consent, profile, delete-my-data |
| `multiturn.yaml` | Memory and mode switches across turns |
| `adversarial.yaml` | Prompt injection, personal-data fishing, harmful requests |
| `crisis.yaml` | Self-harm and abuse signals → fixed crisis reply |
| `off_topic.yaml` | Requests outside the product's scope |
| `parent_journey.yaml` | Parent journey (ages 3–8): khoj, serve-and-return, medical referral, hazards, nudges |

`roadmap-004` (progress on a stored roadmap) is **deferred**, because roadmap progress tracking
was trimmed from the MVP (decision B9). It stays in the file and is excluded from targets.

Parent-journey cases add `learner` (or `learners`) and optionally `open_activity` (a catalogue id)
to set up the child and an activity that's already been offered.
