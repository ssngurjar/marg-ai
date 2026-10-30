# Demo video: final script

For: Santram (voice-over) and the editor. Length: **3:00 at most**; the final judges watch it live.

The video has four voice-over parts and one part with **no voice-over at all**: the field test,
which is shown raw. Read at a calm pace (about 130 words a minute). The word counts are there so
the parts fit their time; time each part when recording and trim words, never the captions' facts.

Everything the script names is built and working as of Oct 28 (see
[features.md](features.md) for how each part works). The video may only claim what the
repository shows; one line marked **[if it happens]** goes in only if the field test shows it.

---

## 0:00 – 0:08 · Cold open: a real voice (no voice-over)

The first seconds decide whether the judges lean in: open on the problem and the product in one
breath, not on a title card.

| Time | Sound | Screen |
|---|---|---|
| 0:00–0:04 | A mother's real voice note, in her own Braj or Hindi, asking what to do with her child today (a consented sample, e.g. A1 or A5) | Black; her words as subtitles, Devanagari above, English below |
| 0:04–0:06 | Soft WhatsApp arrival sound | A phone screen: Marg's reply arrives in her language |
| 0:06–0:08 | (silence) | Title: **Marg.ai**, and under it "*Marg* means path" |

Along the bottom for all 8 seconds, small: "Everyone shown gave written consent. No child's face
or real name. Built during the Meta hackathon, Oct 26 – Nov 4, 2026." (This replaces the
5-second consent card.)

---

## 0:08 – 0:40 · My world (voice-over, ~65 words)

Every line has its own picture; pure village scenery only under the first line.

| Voice-over | Screen |
|---|---|
| "Hi, I'm Santram. I built this for my village in Rajasthan." | The village, wide (3–4 s), then a lane or courtyard |
| "I grew up there, where learning meant memorising books. It took me thirty years to learn how to think: to ask *why*, and to build." | A child reciting from a book, **from behind**; the sound of rote chanting under the voice |
| "Parents here still say: '*padho, padho*.' Read. But nobody shows them how to make a child curious." | A parent's hands holding a phone, unsure what to do |
| "In rural India, fewer than one in four Class 3 children in government schools can read a Class 2 story." | **An animated grid of 100 children; 23 light up.** Caption: "ASER 2024, rural India, government schools: 23.4%" |

---

## 0:40 – 1:12 · What Marg.ai is (voice-over, ~70 words)

A 30-second preview of the product, matched line by line, so that when the raw field test
starts the judges already know what they are watching.

| Voice-over | Screen |
|---|---|
| "Children here don't lack talent. They lack exposure: someone to ask them *why*, and anyone who's walked a path beyond the village." | Children's hands sorting leaves (no faces), then Marg's reply on the phone asking the child's question back |
| "So I built Marg.ai. *Marg* means path. It isn't a tutor, and it isn't screen time for children." | The Marg.ai chat on a parent's phone |
| "It coaches the people already around a child, by voice, on WhatsApp." | A voice note's waveform being sent; the reply arriving |
| "The world is the curriculum; the phone is the coach." | Hands with leaves, then the khoj card from Muse Image. Caption: "Aaj ki Khoj: a two-minute discovery, every day" |
| (between lines) | Three labels, one after another: **Hindi · Hinglish · Braj**, **6 Meta models, each with one job**, **about 3 US cents a family a day** |
| "Does it work? Here's a real field test, in my village." | Cut to the raw field test |

### Shot list for these 1:12 (what to record in the village)

- The village wide, and one lane or courtyard (5–10 s each, steady, morning light).
- A child reciting from a book, **from behind only**, with the sound.
- A parent's hands holding a phone (no face needed).
- Children's hands sorting leaves on the ground (hands only).
- A mother's voice note asking what to do with her child today, if she agrees in writing to its
  use in the video **and by Meta** (her earlier consent covered testing only).

Made on the computer (no recording needed): the ASER grid animation, the title and the three
labels, and phone-sized screen recordings of Marg's replies from the web demo.

### The voice-over

Santram records it in one take while watching the finished cut, so the timing is already set.
The cut is first built with a temporary voice (an Indian English voice built into macOS) timed to
these words; the real recording replaces it. The final video uses only Santram's own voice.

---

## 1:12 – 2:06 · Field test (NO voice-over, ~54 s)

Raw footage and screen recording only. **No background music over the voices**: the judges must
hear the real voice notes, and see Marg's real replies arrive with the real waiting time. Short captions on screen name each moment:

| Moment | Caption on screen |
|---|---|
| The parent says Hi and gives consent | "Consent first. Marg stores a nickname and a birth year, nothing else." |
| The morning message arrives | "Every morning, at the time the parent chose" |
| The parent asks for today's khoj by voice | "A voice note, in Hindi or Hinglish" |
| Marg's reply arrives | "Marg replies in the family's own language" |
| Parent and child do the activity (child from behind, or hands only) | "Two minutes, offline, with things at home" |
| The parent reports what the child said | "The parent tells Marg what the child said" |
| Marg's reply to that report | "Marg answers the child's idea, and asks one question back" |
| The child talks to Marg alone | "With the parent's one-time consent, the child can talk to Marg alone. Every word is checked." |
| The khoj card arrives and is forwarded | "A card of the child's discovery, made by Muse Image" |
| A photo of collected leaves is sent | "SAM 3.1 counts what the child collected, after checking there's no person in the photo" |
| **[if it happens]** The parent speaks Braj and Marg answers in Braj | "Marg answers in the family's own Braj" |

---

## 2:06 – 2:33 · How it works (voice-over, ~62 words, one line per part of the diagram)

*Visuals: the architecture diagram ([system-diagram.html](system-diagram.html): open it full screen,
press → as each part is named; C hides the captions, H the buttons), the `/demo` page with
its live trace filling in step by step, the eval scorecard, the GitHub repository.*

> *(over a title card: "How it works · System design and technical depth")* Now, the system behind it.
> From the outside, it's just a WhatsApp contact.
> Inside, a compound AI system: six Meta models, each with one job.
> Voice Transcribe hears the parent.
> Muse Spark plans and replies in the family's language.
> Muse Spark Open, an open-weights model, reflects on the child.
> SAM counts what they collected.
> Muse Image draws the card.
> Llama Guard 4 checks every message, both ways. If safety is down, nothing goes out unchecked.
> Every model here is Meta's, open weights included, at about three US cents a family a day. A
> real system doesn't need the most expensive model. It needs the right model for each job.

*Every diagram step carries a caption bar saying what it does (v2, 2026-10-31), e.g. "SAM 3.1
drops any photo with a person, then counts what the child collected". The last step's bar names
the six models and "about 3 US cents a family a day".*

*Recording it (first take, 2026-10-29, ran 52 s against 27):* no opening line ("let's move on
to…"): the diagram changes the topic. Read the lines as written, without "then" or "after
that". Say "SAM" (the diagram shows 3.1) and "Llama Guard four". Record each line as its own
take if that's easier; the editor joins them on the diagram's steps. A stumble: pause, say the
whole line again; the editor cuts the bad one. Aim for about 2.3 words a second.

*Caption over the scorecard (shown, not said): "Every change scored on 78 test cases by the
real pipeline. Every crisis case must pass."*

---

## 2:33 – 3:00 · Impact (voice-over, ~60 words)

This part answers the Impact criterion (30%): who benefits, how much it matters, and could
people really use it. It claims reach, never lives changed: nothing in the repository measures
that yet.

*Visuals: a row of village houses; a teacher's chapter turned into three fields on WhatsApp; a
student's answer with its official source links (each shown, not said); the village at dusk.
No dashboard on screen.*

> Almost nine in ten rural teenagers already have a smartphone at home. That phone is Marg's
> reach: no app, no reading, just a voice note.
>
> One parent, one child, every day. One teacher, a whole class.
>
> From a child's first *why* to their first career decision: one guide that grows with them.
> Thank you.

*Caption while the first line is spoken: "ASER 2024: almost 90% of rural 14–16-year-olds have a
smartphone at home"*

---

## Editor's checklist

- [ ] **Blur every phone number** in the WhatsApp screen recordings (the chat header, the contact
      info, any notification).
- [ ] No child's face in any frame, and no child's real name in any caption, audio or file name.
      Use a nickname such as "Munni".
- [ ] No music over the field test or over any voice note. Light music only under the first part,
      and only if it doesn't cover the voice.
- [ ] The consent card stays on screen for at least 4 seconds.
- [ ] Every caption matches what is on screen at that moment.
- [ ] The ASER figure is shown with its source on screen.
- [ ] Total length 3:00 or less, checked on the exported file.
- [ ] The "[if it happens]" Braj line is in the cut only if the field test shows it.
- [ ] The "78 test cases" caption matches the newest scorecard in `evals/results/`.
- [ ] The Braj clause in the impact part ("the way it learned Braj") stays only if the field
      test or a recorded demo shows a Braj reply; otherwise end that sentence at "language".
- [ ] Replies are text (`VOICE_REPLIES_ENABLED=false`): every model called must be a Meta model,
      and Meta's only speech model, MMS-TTS, waits on the organisers' licence ruling (C8). No
      shot plays a spoken Marg reply unless they clear MMS and voice replies are switched on.
- [ ] Nothing on screen or in a caption calls Marg a chatbot, a tutor or "AI for education",
      and the student mentor never leads a scene: the rules ban basic RAG apps and AI-for-
      education chatbots, so the parent's offline discovery is the story.
- [ ] Never call Marg "AI for education" or a tutor on screen or in captions: it closes the
      exposure gap by coaching the adults around a child.
- [ ] "Six Meta models" stays true: Muse Spark, Muse Spark Open, Muse Voice Transcribe, Muse
      Image, SAM 3.1 and Llama Guard 4 (see [features.md](features.md)). Add "MMS-TTS" only if
      voice replies are cleared and on.
- [ ] **No admin dashboard on screen** unless blurred: it shows counts from a single child, and the
      video names the village. `/status` and the `/demo` trace are safe to show.

## Sources for the facts spoken

- ASER 2024, National findings (ASER Centre), p. 47: Std III children in rural government
  schools who can read a Std II level text: 23.4% (16.3% in 2022). P. 48 (digital literacy,
  ages 14–16): "Almost 90% of both girls and boys report having a smartphone at home."
  <https://asercentre.org/wp-content/uploads/2022/12/ASER-2024-National-findings.pdf>
  Retrieved 2026-10-28. Also reported at
  <https://www.drishtiias.com/daily-updates/daily-news-analysis/aser-2024-and-elementary-education>.
