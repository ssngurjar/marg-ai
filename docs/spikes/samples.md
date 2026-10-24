# S0 — Voice sample collection

S2 tests speech-to-text (Muse Voice Transcribe) and text-to-speech (MMS-TTS) against **real**
voice notes before the pipeline is built on top of them. These samples are that test set.

## What to collect

**10 WhatsApp voice notes**, each 5–30 seconds, from at least **4 different speakers**:

| # | Speaker | Language / register | Content |
|---|---|---|---|
| 1–2 | Student (any grade 6–12) | Hindi | "What should I do after 10th?" in their own words |
| 3–4 | Student | Hinglish (mixed) | A dream job or a subject they like |
| 5 | Student | Hindi with a regional accent (Rajasthani, Bhojpuri, Haryanvi …) | Anything about school |
| 6–7 | Teacher | Hindi or Hinglish | "I'm teaching <chapter> in class <n> tomorrow…" |
| 8 | Any | Noisy background (outdoors, a classroom, a fan) | Any question |
| 9 | Any | Contains exam or scheme names (NEET, NMMS, Navodaya, Khelo India) | A question about one |
| 10 | Any | Very short (under 3 s) or mostly silence | Tests the "say it again" path |

Recording in WhatsApp itself matters: it produces the exact `ogg/opus` format the webhook will receive.

## Consent (required before recording)

Read this to the speaker. For anyone under 18, read it to the parent or teacher too, and get
their agreement as well.

> **Hindi:** "Hum ek app bana rahe hain jo gaon ke bacchon ko career ke baare mein awaaz se
> jaankari degi. Kya aap apni awaaz ka ek chhota message record karne denge? Yeh sirf app ko test
> karne ke liye istemaal hoga, kisi ko share nahi hoga, aur aap kabhi bhi kahenge toh hum ise
> delete kar denge. Aapka naam aur number kahin save nahi hoga."
>
> **English:** "We're building an app that gives village students career guidance by voice. May we
> record a short voice message from you? It will only be used to test the app, it won't be shared,
> and we'll delete it whenever you ask. Your name and number won't be stored."

Only record after a clear yes.

## Where samples go

- Save them locally as `sample-01.ogg` … `sample-10.ogg` **outside git** for now
  (`~/marg-samples/`). They are personal data.
- 2–3 samples where the speaker explicitly agreed to their use as **test fixtures** may later go in
  `tests/fixtures/audio/`. Ask before committing any (CLAUDE.md §1).
- Fill the manifest below with **no names and no phone numbers**.

## Manifest

| File | Speaker type | Age group | Register | Accent / region | Background noise | Ground-truth transcript (typed by you) | Fixture consent |
|---|---|---|---|---|---|---|---|
| sample-01.ogg | | | | | | | |
| sample-02.ogg | | | | | | | |
| sample-03.ogg | | | | | | | |
| sample-04.ogg | | | | | | | |
| sample-05.ogg | | | | | | | |
| sample-06.ogg | | | | | | | |
| sample-07.ogg | | | | | | | |
| sample-08.ogg | | | | | | | |
| sample-09.ogg | | | | | | | |
| sample-10.ogg | | | | | | | |

The typed ground-truth transcript is what S2 measures speech-to-text accuracy against
(word error rate), so write exactly what was said, mixed scripts included.
