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
| "It equips the people already around a child to teach the way India's national curriculum asks: through play, talk, and the world around them." | A voice note's waveform being sent; the reply arriving |
| "The world is the curriculum; Marg is the guide." | Hands with leaves, then the khoj card from Muse Image. Caption: "Aaj ki Khoj: a two-minute discovery, every day" |
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

## 1:10 – 1:40 · Field test (NO voice-over, ~30 s)

Raw footage and screen recording only. **No background music over the voices**: the judges must
hear the real voice notes, and see Marg's real replies arrive with the real waiting time. Short captions on screen name each moment:

*About 30 seconds: since cut v3 gives part 3 its real recordings, pick the five or six strongest
moments below (consent, the voice note and reply, the activity, the report, the card).*

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

## 1:40 – 2:35 · How it works (voice-over, ~130 words: the shape, then real evidence)

*Cut v3 (2026-10-31) puts the field test at 1:10–1:40 and impact at 2:35–2:59; with the real
field-test footage, take the time from the field test first, never from this part.*

*Visuals, in order: a title card; the pipeline diagram ([system-diagram.html](system-diagram.html),
step 2); **two real screen recordings of the `/demo` page** with the pipeline trace filling in;
the Muse Spark Open step of the diagram; a numbers card; the whole diagram with the models bar.*

> *(title card: "How it works · System design and technical depth")* Now, the system behind it.
> *(diagram, step 2)* Inside, a compound AI system: six Meta models, each with one job.
> *(recording 1: a parent's voice note)* A real voice note on the live demo. Muse Voice
> Transcribe hears it, Llama Guard and Muse Spark check it, Muse Spark answers in Braj, and it's
> checked again. Under one cent.
> *(recording 2: Llama Guard switched off)* Here, Llama Guard is switched off. Muse Spark checks
> instead, the family still gets an answer, and nothing goes out unchecked.
> *(diagram, Muse Spark Open step)* Muse Spark Open, an open-weights model, reflects on the child.
> *(numbers card)* Underneath is a hexagonal architecture: every model sits behind a port, so
> every test runs without a live model.
> *(whole diagram, models bar)* Every model here is Meta's, open weights included, at about three
> US cents a family a day. A real system doesn't need the most expensive model. It needs the
> right model for each job.

*The recordings are real takes (2026-10-31), not mock-ups:*
- *Recording 1: Hinglish setup, "Main parent hoon", "Lala, 10 saal", then a voice note. The
  trace shows fetch_media, transcribe (muse-voice-transcribe-1.0, hindi, 4.4 s), safety_in
  (Llama Guard 4 + Muse Spark, 1.9 s), generate (Muse Spark 1.3, 5.5 s), safety_out (0.5 s):
  12.5 s and $0.0061 for the turn. Bar: "Live demo, real trace: transcribe · Llama Guard + Muse
  Spark check · Muse Spark replies in Braj · check again · 12.5 s, $0.0061".*
- *Recording 2: the same setup with Llama Guard's address pointed at a closed port for this take
  only. Trace: safety_in and safety_out by muse-spark-1.3 with `guard=down`, a real reply,
  $0.0070. The bar says so plainly: "Same demo, Llama Guard switched off for this take…".*

*Numbers card ("Built to be checked"), each line checked on 2026-10-31:*
- *Hexagonal architecture: every model behind a port; tests never call a live model*
- *2,487 unit · 205 integration tests (`pytest --collect-only`)*
- *86 graded eval cases; crisis and adversarial hard gates pass*
- *Every message checked twice, in and out; Muse Spark backs up Llama Guard*
- *Under 1 US cent a reply: $0.0061 measured on the live demo*

*Recording the voice:* this part is denser than the rest: about 2.4 words a second. Say "Llama
Guard four" and "hexagonal". Record each line as its own take; the editor lays each one on its
shot. A stumble: pause, say the whole line again; the editor cuts the bad one.

---

## 2:35 – 3:00 · Impact (voice-over, ~60 words)

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
- [ ] The numbers card matches `pytest --collect-only` and the newest scorecard in `evals/results/`.
- [ ] The Braj clause in the impact part ("the way it learned Braj") stays only if the field
      test or a recorded demo shows a Braj reply; otherwise end that sentence at "language".
- [ ] Replies are text (`VOICE_REPLIES_ENABLED=false`): every model called must be a Meta model,
      and Meta's only speech model, MMS-TTS, waits on the organisers' licence ruling (C8). No
      shot plays a spoken Marg reply unless they clear MMS and voice replies are switched on.
- [ ] Nothing on screen or in a caption calls Marg a chatbot, a tutor or "AI for education",
      and the student mentor never leads a scene: the rules ban basic RAG apps and AI-for-
      education chatbots, so the parent's offline discovery is the story.
- [ ] Never call Marg "AI for education" or a tutor on screen or in captions: it closes the
      exposure gap by equipping the adults around a child.
- [ ] "Six Meta models" stays true: Muse Spark, Muse Spark Open, Muse Voice Transcribe, Muse
      Image, SAM 3.1 and Llama Guard 4 (see [features.md](features.md)). Add "MMS-TTS" only if
      voice replies are cleared and on.
- [ ] **No admin dashboard on screen** unless blurred: it shows counts from a single child, and the
      video names the village. `/status` and the `/demo` trace are safe to show.

## Sources for the facts spoken

- National Curriculum Framework for Foundational Stage 2022 (NCERT), ages 3–8 (p. 11):
  "Children learn best through play - through activity and doing" (p. 38); "Play is thus
  central to children's learning and development" (p. 39); "Learning through Play - Using the
  Immediate Environment" (p. 43); "For the age group of 3-8 years, most learning occurs through
  play, listening, and talking. This should necessarily be conducted in the children's L1"
  (p. 76); "Parents and family are co-partners with the school in the child's learning and
  development" (p. 219). <https://ncert.nic.in/pdf/NCF_for_Foundational_Stage_20_October_2022.pdf> Retrieved 2026-10-31.
- Serve and return (Harvard Center on the Developing Child): "Serve and return
  interactions—responsive, back-and-forth exchanges between a young child and a caring
  adult—play a key role in shaping brain architecture." <https://developingchild.harvard.edu/science/key-concepts/serve-and-return/> Retrieved 2026-10-31.

- ASER 2024, National findings (ASER Centre), p. 47: Std III children in rural government
  schools who can read a Std II level text: 23.4% (16.3% in 2022). P. 48 (digital literacy,
  ages 14–16): "Almost 90% of both girls and boys report having a smartphone at home."
  <https://asercentre.org/wp-content/uploads/2022/12/ASER-2024-National-findings.pdf>
  Retrieved 2026-10-28. Also reported at
  <https://www.drishtiias.com/daily-updates/daily-news-analysis/aser-2024-and-elementary-education>.
