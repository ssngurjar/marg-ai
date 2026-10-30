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
> - **Students** get a mentor that states facts only from 53 official sources and cites them,
>   and a step-by-step plan.
>
> Every turn adds to one record that grows with the child, from their first *why* to their first
> career decision. Safety runs on every message in and out (Llama Guard 4 plus a second Muse
> Spark check plus our own child rules), and fails closed.
>
> All of it was built during the hackathon: about 2,650 tests, an eval harness that plays 86
> hand-written cases through the real pipeline, and a field test in my village. Every bug found
> by using Marg like a family would (a shared phone, mixed languages, a refresh) became a fix
> and a permanent test.

*(Recheck before submitting: the test count from `pytest`, the case count from the newest
scorecard, and that the field test happened.)*

---

## Describe your use of Meta products to build the submitted project

> Marg is a compound AI system: six Meta models, each with one job, behind a deterministic router
> and a safety gate on both sides. Every model it calls at runtime is a Meta model.
>
> - **Muse Spark 1.3 (Model API):** reads what a parent's own words mean (a report on the
>   discovery, a question, the child's question, "send that one again", another child) so the
>   conversation can go anywhere; plans and personalises each discovery, answers parents,
>   writes teachers' chapter bridges, the student mentor and plans, talks with children, and
>   runs our second safety check. Every call uses structured output into a typed model, with
>   one repair retry on a failed check.
> - **Muse Spark Open, open weights (on Baseten):** reflects on what the child said and extracts
>   curiosity and aspiration signals. Spark 1.3 takes over if it is slow. Measured in a full
>   86-case eval run: 16 of 126 generation steps (13%), namely 3 parent reflections and 13 of
>   15 signal extractions (Spark 1.3 took the other two when Open was slow).
> - **Muse Voice Transcribe:** every voice note. We normalise Gujarati, Gurmukhi, Bengali and
>   Oriya script slips back to Devanagari, and detect Braj from the words.
> - **Muse Image:** the khoj card, with no child or name in the image prompt.
> - **SAM 3.1:** checks a child's photo for any person first (then it's dropped unseen), and only
>   then counts the leaves or stones the child collected. Photos are never stored.
> - **Llama Guard 4:** every message and every reply, text and spoken text, with Muse Spark as a
>   second opinion and as the backup when it is down.
> - **Muse Code:** wrote parts of the code under our review.
>
> The official-source search is keyword search in Postgres, after Muse Spark turns a Hindi or
> Hinglish question into English search terms. Replies are text: Meta's MMS-TTS is built in as
> the voice, switched off until the organisers rule on its non-commercial licence.
>
> An LLM judge (Muse Spark) scores 86 golden cases through the real pipeline on every change;
> crisis and adversarial cases are hard gates.

*(Before submitting: Muse Code: keep only if it really wrote committed code.)*

---

## Why are Meta's models important to your solution?

> Because the families I build for speak, they don't type. Muse Voice Transcribe hears a
> parent's Hindi, Hinglish or Braj voice note on a cheap phone, and Muse Spark reads what the
> words mean: a report on the child, a question, a child writing on the parent's phone, "send
> that again". In a live check it read 33 of 33 real-style messages right, Braj included.
>
> Because children are involved, safety can't be one model's guess. Llama Guard 4 and a Muse
> Spark policy check read every message in parallel, and each covers the other's blind spots:
> Llama Guard flagged "I want to become a doctor, make me a plan" as self-harm, which Muse Spark
> cleared, while Muse Spark caught a quiet "mujhe jeena nahi hai" that needs a helpline. SAM
> 3.1 lets us accept a child's photo at all: it proves no person is in it before anything else
> looks.
>
> Because cost decides whether this reaches a village. Muse Spark Open, an open-weights model,
> did 13% of the generation steps in a full 86-case eval run (the child's reflection and the
> curiosity signals), and the whole pipeline costs under one US cent per reply in model calls.
> Open weights also mean that work could one day run where Indian children's data must stay.
>
> And because one family of models covers voice in, text, images, segmentation and safety, the
> whole system speaks one structured-output contract end to end: six models, each with one job,
> and rules and code between them.

---

## Provide feedback from your experience using Meta products

What we'd ask Meta to change, most important for our users first. Each point was measured in
this build; for each, what it did to a family, what we did, and the change that would help.

> 1. **Llama Guard 4 misreads ordinary Hindi and Hinglish.** On a user's message it flagged a
>    child's "Chaand raat ko hi kyun dikhta hai?" ("why is the moon seen only at night?") as S3,
>    sex crimes, 4 times out of 4; a parent's "kal wali khoj phir se bhejo, Munni ko yaad nahi"
>    as S10, hate, 3 of 3; and "doctor banna hai, plan bana do" as S11, self-harm. The child got
>    a refusal for a question about the moon. We now count S1, S2, S3, S4 and S10 on a user's
>    message only when our Muse Spark check agrees. **Ask:** Indic-language calibration, and a
>    per-category score or threshold, so one model can be trusted alone.
> 2. **No Meta embedding model.** Every runtime model must be Meta's, so our multilingual
>    embeddings had to go, and the student mentor now searches 53 official documents by keyword
>    only. A student who asks in their own words, naming no exam, finds less. **Ask:** a
>    multilingual (Indic) embedding model in the Model API.
> 3. **No commercially licensed Meta text-to-speech.** Many of our parents can't read long
>    messages, and MMS-TTS, the only Meta voice for Hindi, is CC-BY-NC, so Marg replies in text
>    and the web demo uses the browser's voice. **Ask:** a Meta speech model under a permissive
>    licence, or speech output in the Model API.
> 4. **Llama Guard 4 isn't on the Model API or a listed partner.** We run it on DeepInfra: in
>    one 22-case eval run 28 calls timed out at our 1.5 s limit or were refused, in another none
>    did, and on day one it answered `429 engine_overloaded`. Muse Spark decides whenever it's
>    down, so nothing goes out unchecked, but a reply then waits for the backup. **Ask:** Llama
>    Guard on the Model API.
> 5. **One combined category list hides intent.** A class-8 student asking to make a rocket from
>    firecracker powder came back S9 (weapons) and S2 (crime) every time, so the safe-curiosity
>    redirect we wrote for S9 lost to a flat refusal until we special-cased the pair. **Ask:** a
>    signal for "asks how to make" versus "asks about".
> 6. **Reasoning tokens share `max_output_tokens`.** Our query rewriter and intent reader
>    returned cut-off JSON until we raised their limits to 1,200, and the eval judge needed
>    6,000. **Ask:** a separate reasoning budget, or a clear error when reasoning used the limit.
> 7. **Muse Voice Transcribe** sometimes returns Hindi speech in Gujarati or Gurmukhi script; we
>    convert it back. **Ask:** a language or script hint per request.
> 8. **Smaller things:** Muse Image returns a ~5 MB PNG (a size or format option would save a
>    re-encode for WhatsApp); the WhatsApp Cloud API messaging token can't read its own
>    phone-number object, so there is no cheap health check for the channel.
>
> What worked best: **Muse Spark structured output.** Strict JSON schemas plus one repair retry
> with the validation error made every generative step typed, and its intent reading (33 of 33)
> is what lets Marg follow a family that takes the conversation anywhere.

*(Each point is from this build: the s07, s09, s10b, s11 and S15 decision logs and the live checks
behind them.)*

---

## Provide feedback from your experience using partner technologies

> **Baseten** hosts Muse Spark Open for us through an OpenAI-compatible endpoint, which dropped
> straight into our adapter. Cold or slow responses happen, so we gave it a 7-second limit with
> Muse Spark 1.3 as the fallback. A visible warm/cold status would let us choose up front.
> (Llama Guard 4 runs on DeepInfra, not a listed partner: see point 4 of the Meta feedback.)

---

## Most Viral Track (X post link)

To fill after posting the demo video on X (engagement counts until Nov 8).

---

## Public GitHub repository / 3-minute demo video

The repository (public, with the `pre-kickoff` tag) and the YouTube link.

## How judges try it (put in the description or wherever the form allows a link)

- Web: <https://marg-ai.fly.dev/demo>. It answers in English by default; Hindi or Hinglish get the same.
- WhatsApp: `https://wa.me/<number>?text=Hi%20Marg%2C%20English%20please` (the chat opens with
  "Hi Marg, English please" typed, so Marg answers in English). Check it opens the right number
  (pre-demo checklist).
