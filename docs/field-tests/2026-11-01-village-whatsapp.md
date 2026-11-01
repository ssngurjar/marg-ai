# Field test: a village participant on WhatsApp, 1 November 2026

For: judges and reviewers who want to know what happened when someone from the village used
Marg unscripted, and what changed because of it.

No message is quoted word for word, and no name, nickname or place from the session appears here
(CLAUDE.md §1). What people wrote is described in our own words; the cases added to tests and
banks are synthetic ones that check the same thing.

## Setup

- **Who:** one adult from the owner's village, on their own phone. No script: they were told only
  that Marg is a WhatsApp guide and could ask anything.
- **How:** WhatsApp through Meta's test number, to the API running on the owner's laptop, reached
  through a Cloudflare tunnel. The same code and the same models as the deployed app.
- **When:** two sessions on the evening of 1 November (about 21:39 to 22:15 IST). Between them, the
  participant used "delete my data", and the first session's record was deleted by design.

## What happened, in numbers (second session)

| | |
|---|---|
| Turns | 21 (12 onboarding, 8 career questions, 1 refused) |
| Failed turns | 0 |
| Reply time, onboarding | 4.7 s average, 10.3 s slowest |
| Reply time, career answers | 10.9 s average, 14.9 s slowest (the slow home connection added about 2–3 s per turn: the quick safety and reading calls took twice as long as on a good connection, the answer itself the same 6 s) |
| Messages delivered and read | 24 of 24 |
| Sources cited | the official UPSC examination notice, on the first career answer |

The first session (at least 15 turns) covered onboarding as a parent, the child-talk consent, a
khoj, questions about who built Marg and what it can do, and a complete deletion.

## What people did that the banks never had

- Gave a child's **home name without the age**, three times in different words, before the age.
- Typed the words Marg's own message told them to say to start child talk.
- Asked whether Marg **speaks Braj**.
- Said they were a **graduate** preparing for the civil services exam, when Marg asked for a
  class from 1 to 12.
- Showed frustration with an **emoji and a short complaint** after the same reply came back three
  times.
- Replied with **emoji** (a heart-eyes face, a laughing face), "ok" several times, and **good
  night** to close.
- After deleting everything, asked why the **messages were still on their phone**.
- Asked who made Marg, and pressed for the maker's name.

## What broke, and what was fixed that night

| What happened | Fix (commit) |
|---|---|
| A home name without the age got "didn't understand" three times, then the age added a child with no name | the name is kept and the age asked by name; the age's turn takes the name back (`8ba519e`) |
| Typing the child-talk phrase Marg had just suggested got "who is writing?" | the typed phrase starts child talk for the child the parent said yes for (`8ba519e`) |
| After a deletion, "why are the messages still on my phone?" had no answer | a fact: deleting clears what Marg keeps, not the phone's own chat (`8ba519e`) |
| A graduate was asked for a class from 1 to 12, three times, with no way in | a graduate level (grade 13, migration `s08_graduate_level`); the mentor treats them as a graduate and searches every source (`05634f5`) |
| "ok", emoji and good night took about 10 s each, and one repeated facts already given | small talk gets a short fixed reply at once, no model call (`671ad89`) |
| A blocked message got "let's talk about the child's khoj", a parent's wording, sent to a student | the general refusal reads right for everyone (`671ad89`) |
| The mentor answered an emoji with affection, which invited a message that was then refused, and listed the same village paths in reply after reply | warm, never affectionate; varied examples; no repeated facts (`dccde91`) |
| "Can you talk in Braj?" got the general paragraph about Marg | a true answer: Braj understood, replies in Hindi or Hinglish with light Braj (`a4a0ccf`) |
| A khoj had a word half in Roman, half in Devanagari letters | the shared script check names it, and the repair retry rewrites it (`a5deef1`) |
| A first "ok" after the deletion was kept as "your question" | a short acknowledgement starts onboarding like a greeting (`ae76d53`) |
| "What do you know about me?" told a parent Marg keeps their class and district | what Marg keeps is said per role (`ae76d53`) |

Every fix ships with tests, including an integration test that replays the name-then-age-then-
child-talk sequence on the database, and new cases in the onboarding and student banks.

## Still open

- **Career answers take about 8 s on a good connection** (11 s here). WhatsApp's "typing…" shows
  the whole time, so the wait is visible, not silent.
- **The welcome repeats in full** when someone keeps writing without tapping consent; the
  participant wrote three messages before tapping it.
- **Answering the child-talk question in words** ("by voice") repeats the question; the buttons
  work.
- **One person, one evening.** The next step is three to five families with the number for a few
  days, unscripted, and the off-topic and small-talk counts read from `turn_steps`.
