# Submission form: drafted answers

For: Santram, pasting into the Cerebral Valley submission form. Track: **Indie Developer**.
Every fact here is in the repository or in a cited source; recheck the marked numbers before
submitting.

Two rules shape every answer:

- **Banned categories** include "AI for education" chatbots, basic RAG apps, AI medical or health
  advice and simple image analyzers. Marg is none of these, and the wording must make that
  obvious: it coaches the adults around a child, the child's discovery happens offline, the
  student mentor is one part of a larger system, and medical questions are referred, never
  answered.
- **Identify your contributions.** Everything in the code was built Oct 26 – Nov 4. Before
  kickoff there were only planning docs, design docs, golden test cases and a source list: the
  git tag `pre-kickoff` marks where code begins.

---

## Which problem statement did you build towards?

**Build for Your World.**

---

## Project Description

> Marg closes the exposure gap for rural Indian children: they don't lack talent, they lack
> someone who asks them *why*, and anyone who has walked a path beyond the village. I grew up in
> such a village in Rajasthan, and I built Marg for it.
>
> Marg isn't a tutor or a chatbot for children. It is a voice-first guide on WhatsApp that
> coaches the people already around a child, in Hindi, Hinglish, English or Braj:
>
> - **Parents of 3–8-year-olds** get *Aaj ki Khoj*, a two-minute discovery to do offline with
>   things at home (shadows, leaves, sounds). The parent reports what the child said, by voice,
>   and Marg answers the child's idea and asks one question back. A photo of what the child
>   collected is counted by SAM 3.1 after a check that no person is in it; Muse Image turns the
>   discovery into a card the family can share.
> - **Children**, with the parent's consent, can ask Marg their own questions by voice, in short
>   sessions with strict child-safety rules.
> - **Teachers** get today's chapter connected to three real fields, with a five-minute activity
>   for 40 students and no materials to buy.
> - **Students** get a mentor that states facts only from 50 official sources and cites them,
>   and a step-by-step plan.
>
> Every turn adds to one record that grows with the child, from their first *why* to their first
> career decision. Safety runs on every message in and out (Llama Guard 4 plus a second Muse
> Spark check plus our own child rules), and fails closed.
>
> All of it was built during the hackathon: about 2,300 tests, an eval harness that plays 78
> hand-written cases through the real pipeline, and a field test in my village.

*(Recheck before submitting: the test count from `pytest`, the case count from the newest
scorecard, and that the field test happened.)*

---

## Describe your use of Meta products to build the submitted project

> Marg is a compound AI system: eight models, each with one job, behind a deterministic router
> and a safety gate on both sides.
>
> - **Muse Spark 1.3 (Model API):** plans and personalises each discovery, answers parents,
>   writes teachers' chapter bridges, the student mentor and plans, talks with children, and
>   runs our second safety check. Every call uses structured output into a typed model, with
>   one repair retry on a failed check.
> - **Muse Spark Open, open weights (on Baseten):** reflects on what the child said and extracts
>   curiosity and aspiration signals and the student's memory. Spark 1.3 takes over if it is
>   slow.
> - **Muse Voice Transcribe:** every voice note. We normalise Gujarati, Gurmukhi, Bengali and
>   Oriya script slips back to Devanagari, and detect Braj from the words.
> - **Muse Image:** the khoj card, with no child or name in the image prompt.
> - **SAM 3.1:** checks a child's photo for any person first (then it's dropped unseen), and only
>   then counts the leaves or stones the child collected. Photos are never stored.
> - **Llama Guard 4:** every message and every reply, text and spoken text, with Muse Spark as a
>   second opinion and as the backup when it is down.
> - **Muse Code:** wrote parts of the code under our review.
>
> The other two models aren't Meta's: Kokoro-82M (Apache-2.0, self-hosted) speaks the replies,
> and multilingual-e5-small finds passages in our official sources.
>
> An LLM judge (Muse Spark) scores 78 golden cases through the real pipeline on every change;
> crisis and adversarial cases are hard gates.

*(Before submitting: Muse Code: keep only if it really wrote committed code.)*

---

## Why are Meta's models important to your solution?

> Because the families I build for speak, they don't type. Muse Voice Transcribe hears a
> parent's Hindi voice note on a cheap phone, and the reply comes back as a voice note, so a parent who can't
> read a long message still gets the whole discovery.
>
> Because children are involved, safety can't be one model's guess. Llama Guard 4 and a Muse
> Spark policy check read every message in parallel, and each covers the other's blind spots: on
> real tests Llama Guard flagged "I want to become a doctor, make me a plan" as self-harm, which
> Muse Spark cleared, while Muse Spark caught a quiet "mujhe jeena nahi hai" that needs a
> helpline. SAM 3.1 lets us accept a child's photo at all: it proves no person is in it before
> anything else looks.
>
> Because cost decides whether this reaches a village. Muse Spark Open, an open-weights model,
> runs the high-volume reflection and signal work, and the whole pipeline costs under one US
> cent per reply in model calls, measured in our eval runs.
>
> And because one family of models covers voice in, text, images, segmentation, safety and voice
> out, the whole system speaks one structured-output contract end to end.

---

## Provide feedback from your experience using Meta products

> - **Muse Spark structured output** was the most reliable part: strict JSON schemas plus one
>   repair retry with the validation error made every generative step typed.
> - **Llama Guard 4 over-flags career and teaching questions.** "Doctor banna hai, plan bana do"
>   came back S11 (self-harm), and a harmless answer on teaching colours came back S2, S4 or S8
>   on different runs. A second opinion from Muse Spark fixed both; a calibrated threshold or a
>   per-category confidence would help.
> - **Muse Voice Transcribe** sometimes returns Hindi speech in Gujarati or Gurmukhi script. A
>   language hint (or a script hint) per request would remove our normaliser.
> - **The eval judge** needed a much larger `max_output_tokens` (6,000) at high reasoning to
>   finish its JSON; the limit being shared between reasoning and output wasn't obvious.
> - **WhatsApp Cloud API:** the messaging token can't read its own phone-number object, so there
>   is no cheap health check for the channel.
> - **Muse Image** returns a ~5 MB PNG; a size or format option would save a re-encode before
>   sending on WhatsApp.

*(Each point is from this build: s07, s09 and S15 decision logs, the readiness probe notes.)*

---

## Provide feedback from your experience using partner technologies

> **Baseten** hosts Muse Spark Open for us through an OpenAI-compatible endpoint, which dropped
> straight into our adapter. Cold or slow responses happen, so we gave it a 7-second limit with
> Muse Spark 1.3 as the fallback. A visible warm/cold status would let us choose up front.
> (Llama Guard 4 runs on DeepInfra, not a listed partner: timeouts and `429 engine_overloaded`
> on day one are why we built the Muse Spark backup.)

---

## Most Viral Track (X post link)

To fill after posting the demo video on X (engagement counts until Nov 8).

---

## Public GitHub repository / 3-minute demo video

The repository (public, with the `pre-kickoff` tag) and the YouTube link.
