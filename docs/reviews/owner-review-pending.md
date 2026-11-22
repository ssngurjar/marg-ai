# Pending owner review (Santram)

Changes that wait for the owner's review: reviewed copy (fixed replies, onboarding and journey
text, the facts Marg states about itself) and decisions taken while the owner was away. Add an
item when such a change lands (CLAUDE.md §2); tick it when reviewed, and record anything changed
in that step doc's Decisions log in the same commit.

The owner reviewed every item up to 2026-11-03; that list, with every outcome, is in git history
(`git log -- docs/reviews/owner-review-pending.md`).

## Pending (2026-11-20)

- [ ] **Child talk: the goodbye when an opening says the child is going** (`CHILD_OPENING_GOODBYE`,
  `app/constants/child_talk_copy.py`, 2026-11-20). "Main Munni hoon, ab man nahi hai": the
  session opens and ends at once, so not `CHILD_GOODBYE`'s "Aaj bahut maza aaya!". A hello by
  name, "okay", a kind line for why the child is going (read with the intent: `LeavingReason`),
  and telling Mummy-Papa (a session's start and end, CLAUDE.md §11). Nothing asked, no summary.
  Hinglish:
  - not in the mood: "Namaste {name}! Theek hai, abhi man nahi hai toh koi baat nahi. Jab man
    kare, tab baat karenge. Kuch pareshaani ho, toh Mummy-Papa ko batana."
  - play: "Namaste {name}! Theek hai, jao khoob khelo! Khel mein kuch naya dikhe, toh Mummy-Papa
    ko batana."
  - sleep: "Namaste {name}! Theek hai, ab aaram se so jao. Sapne mein kya dekha, uthkar
    Mummy-Papa ko batana."
  - food: "Namaste {name}! Theek hai, jao pet bhar ke khana khao. Khane mein kya bana,
    Mummy-Papa se poochhna."
  - study: "Namaste {name}! Theek hai, jao man se padhna. Aaj kya seekha, Mummy-Papa ko batana."
  - other: "Namaste {name}! Theek hai, phir baat karenge, jab man kare. Mummy-Papa ko bhi batana
    ki tumne aaj kya kiya!"

  Hindi and English alongside. Spoken from the Hindi, the name left out, like all fixed child
  text. "Kuch pareshaani ho, toh Mummy-Papa ko batana" on a child who is only not in the mood:
  the owner keeps it (2026-11-20). With no reason, or an odd one, the "other" text is used.

## Reviewed 2026-11-13

All three approved by the owner as written (2026-11-13); nothing changed.

- [x] **Child daily limit: the child's message** (`CHILD_DAILY_LIMIT_REACHED`,
  `app/constants/child_talk_copy.py`, 2026-11-13). One text for both moments: a child whose time
  for today is used up tries to start, and the goodbye after the last answer when the time runs
  out mid-talk (the parent's topic summary follows it there). Hinglish: "Aaj ki baatein poori ho
  gayi! Kal phir baat karenge. Tab tak ghar mein kuch naya dhoondho, aur Mummy-Papa ko batao!"
  Hindi and English alongside. Spoken from the Hindi, like all fixed child text.
- [x] **Child daily limit: the parent's texts** (`app/constants/child_talk_copy.py`,
  2026-11-13). `CHILD_TALK_LIMIT_ASK` ("{child} roz kitni der Marg se baat karein: 20 minute,
  30 minute ya 1 ghanta? Abhi: {current}. Koi limit nahi chahiye toh likhiye: "limit hata do"."),
  `CHILD_TALK_LIMIT_SET` ("Theek hai! Ab {child} roz {limit} tak Marg se baat kar sakte hain.
  Kabhi bhi badal sakte hain: likhiye "limit badlo"."), `CHILD_TALK_NO_LIMIT_SET` (no daily
  limit, but each talk still 10 minutes and half an hour's break between talks),
  `CHILD_TALK_LIMIT_WHICH_CHILD` ("Kis bachche ki limit?"), and the button titles "20 minute",
  "30 minute", "1 ghanta". Hindi and English alongside.
- [x] **Child daily limit: the time line in the parent's summary** (`PARENT_TALK_TIME`,
  `PARENT_TALK_TIME_NO_LIMIT`, `PARENT_TALK_TIME_USED_UP`, `TALK_MINUTES`, `TALK_ONE_MINUTE`,
  `TALK_UNDER_A_MINUTE`; 2026-11-13). Hinglish: "⏱️ Aaj kul baat: 14 minute. Roz ki limit: 30
  minute." / "…Roz ki koi limit nahi." / "…Roz ki 30 minute ki limit poori ho gayi; kal phir baat
  kar sakte hain." Under a minute: "1 minute se kam". Hindi and English alongside. Not in crisis
  notes.

## Reviewed 2026-11-13 (second round)

Both approved by the owner as written (2026-11-13); nothing changed. **Nothing pending.**

- [x] **A fact Marg states about itself: "a child talking to Marg"** (`app/constants/marg_facts.py`,
  2026-11-13). The daily limit added, since the code changed: "All of a child's talks in a day
  add up to at most 30 minutes, unless the parent picks 20 minutes, 1 hour or no limit; the
  parent can change it any time, and the child can't", and the summary now gives "the topics
  and the child's time that day". The rest of the line is unchanged. A unit test keeps the 30
  equal to `ChildDailyLimitRules.DEFAULT`. Not checked with `marg eval` (about_marg reads these
  facts; the evals can't be run here).
- [x] **Child daily limit: the time-left answer** (`TALKED_TODAY`, `NOT_TALKED_TODAY`,
  `TIME_LEFT_TODAY`, `TIME_USED_UP_TODAY`, `NO_DAILY_LIMIT`, `CHANGE_LIMIT_HINT`;
  `app/constants/child_talk_copy.py`, 2026-11-13). When a parent asks "Munni ka kitna time bacha
  hai?": "⏱️ Aaj Munni ne Marg se 14 minute baat ki. Roz ki limit 30 minute hai, toh aaj 16
  minute aur baaki hain. Limit badalni ho toh likhiye "limit badlo"." / "⏱️ Munni ne aaj abhi tak
  Marg se baat nahi ki. …" / "…Roz ki 30 minute ki limit poori ho gayi; kal phir baat kar sakte
  hain." / "…Roz ki koi limit nahi hai." Hindi and English alongside.
