# Feedback on Meta's models

For: the Meta Model API and Llama teams, and judges who want to see where Meta's models fell
short for a product in Hindi, Hinglish and Braj. The hackathon's form had no field for this, so
it lives here. Marg calls only Meta models at runtime (Muse Spark 1.3, Muse Spark Open, Muse Voice
Transcribe, SAM 3.1, Muse Image and Llama Guard 4); how each is used is in the README's
[The models](../../README.md#the-models).

What we'd ask Meta to change, most important for our users first. Each point was measured in
this build; for each, what it did to a family, what we did, and the change that would help.

1. **Llama Guard 4 misreads ordinary Hindi and Hinglish.** On a user's message it flagged a
   child's "Chaand raat ko hi kyun dikhta hai?" ("why is the moon seen only at night?") as S3,
   sex crimes, 4 times out of 4; a parent's "kal wali khoj phir se bhejo, Munni ko yaad nahi"
   as S10, hate, 3 of 3; and "doctor banna hai, plan bana do" as S11, self-harm. The child got
   a refusal for a question about the moon. We now count S1, S2, S3, S4, S7, S10 and S12 on a
   user's message only when our Muse Spark check agrees (S7 since it called "I can't read, how do
   I use it?" a privacy breach; S12 since a parent's "like in the photo above", after a frog-jump
   khoj, was flagged 4 times out of 4). **Ask:** Indic-language calibration, and a per-category
   score or threshold, so one model can be trusted alone.
2. **No Meta embedding model.** Every runtime model must be Meta's, so our multilingual
   embeddings had to go, and the student mentor now searches 53 official documents by keyword
   only. A student who asks in their own words, naming no exam, finds less. **Ask:** a
   multilingual (Indic) embedding model in the Model API.
3. **No commercially licensed Meta text-to-speech.** Many of our parents can't read long
   messages, and MMS-TTS, the only Meta voice for Hindi, is CC-BY-NC, so Marg replies in text
   and the web demo uses the browser's voice. **Ask:** a Meta speech model under a permissive
   licence, or speech output in the Model API.
4. **Llama Guard 4 isn't on the Model API or a listed partner.** We run it on DeepInfra: in
   one 22-case eval run 28 calls timed out at our 1.5 s limit or were refused, in another none
   did, and on day one it answered `429 engine_overloaded`. Muse Spark decides whenever it's
   down, so nothing goes out unchecked, but a reply then waits for the backup. **Ask:** Llama
   Guard on the Model API.
5. **One combined category list hides intent.** A class-8 student asking to make a rocket from
   firecracker powder came back S9 (weapons) and S2 (crime) every time, so the safe-curiosity
   redirect we wrote for S9 lost to a flat refusal until we special-cased the pair. **Ask:** a
   signal for "asks how to make" versus "asks about".
6. **Reasoning tokens share `max_output_tokens`.** Our query rewriter and intent reader
   returned cut-off JSON until we raised their limits to 1,200, and the eval judge needed
   6,000. **Ask:** a separate reasoning budget, or a clear error when reasoning used the limit.
7. **Muse Voice Transcribe** sometimes returns Hindi speech in Gujarati or Gurmukhi script; we
   convert it back. **Ask:** a language or script hint per request.
8. **Smaller things:** Muse Image returns a ~5 MB PNG (a size or format option would save a
   re-encode for WhatsApp); the WhatsApp Cloud API messaging token can't read its own
   phone-number object, so there is no lightweight health check for the channel.

What worked best: **Muse Spark structured output.** Strict JSON schemas plus one repair retry
with the validation error made every generative step typed, and its intent reading (389 of 392
in the saved bank run) is what lets Marg follow a family that takes the conversation anywhere.

*(Each point is from this build: the s07, s09, s10b, s11 and S15 decision logs and the live checks
behind them.)*
