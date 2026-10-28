# Demo video: final script

For: Santram (voice-over) and the editor. Length: **3:00 at most**; the final judges watch it live.

The video has four voice-over parts and one part with **no voice-over at all**: the field test,
which is shown raw. Read at a calm pace (about 130 words a minute). The word counts are there so
the parts fit their time; if a part runs long, drop the line marked *(cut first)*.

Everything the script names is built and working as of Oct 28 (see
[features.md](features.md) for how each part works). The video may only claim what the
repository shows; one line marked **[if it happens]** goes in only if the field test shows it.

---

## 0:00 – 0:05 · Consent card (text on screen, no voice)

> Everyone shown in this video gave written consent.
> Children's faces and real names are not shown.
> Everything in this demo was built during the Meta hackathon, Oct 26 – Nov 4, 2026.

---

## 0:05 – 0:40 · My world (voice-over, ~75 words)

*Visuals: the village, a courtyard, a lane, parents at work. No faces of children.*

> Hi, I'm Santram. This track asks us to build for our world, so I built for mine: a village in
> Rajasthan.
>
> I grew up there, where learning meant memorising books. It took me thirty years to learn how to
> think: how to ask *why*, and how to build. Parents here still say what mine said: "padho,
> padho." Read. But nobody shows them how to make a child curious.

*On screen while speaking the next line, with the source:*

> In rural India, fewer than one in four Class 3 children in government schools can read a
> Class 2 story.

*Caption: "ASER 2024, rural India, government schools: 23.4%"*

---

## 0:40 – 1:12 · What Marg.ai is (voice-over, ~70 words)

*Visuals: children's hands sorting leaves in a courtyard (no faces), then a parent's hands
holding a phone, WhatsApp open on the Marg.ai chat.*

> Children here don't lack talent. They lack exposure: someone to ask them *why*, and anyone
> who's walked a path beyond the village.
>
> So I built Marg.ai. *Marg* means path. It isn't a tutor, and it isn't screen time for children.
> It coaches the people already around a child, by voice, on WhatsApp. The world is the
> curriculum; the phone is the coach.
>
> Does it work? Here's a real field test, in my village.

*Caption while "the world is the curriculum" is spoken: "Aaj ki Khoj: a two-minute discovery,
every day"*

---

## 1:12 – 2:06 · Field test (NO voice-over, ~54 s)

Raw footage and screen recording only. **No background music over the voices**: the judges must
hear the real voice notes and the real Marg voice replies (Meta MMS-TTS), with the real waiting
time. Short captions on screen name each moment:

| Moment | Caption on screen |
|---|---|
| The parent says Hi and gives consent | "Consent first. Marg stores a nickname and a birth year, nothing else." |
| The morning message arrives | "Every morning, at the time the parent chose" |
| The parent asks for today's khoj by voice | "A voice note, in Hindi or Hinglish" |
| Marg's voice reply plays | "Marg replies by voice and text" |
| Parent and child do the activity (child from behind, or hands only) | "Two minutes, offline, with things at home" |
| The parent reports what the child said | "The parent tells Marg what the child said" |
| Marg's reply to that report | "Marg answers the child's idea, and asks one question back" |
| The child talks to Marg alone | "With the parent's one-time consent, the child can talk to Marg alone. Every word is checked." |
| The khoj card arrives and is forwarded | "A card of the child's discovery, made by Muse Image" |
| A photo of collected leaves is sent | "SAM 3.1 counts what the child collected, after checking there's no person in the photo" |
| **[if it happens]** The parent speaks Braj and Marg answers in Braj | "Marg answers in the family's own Braj" |

---

## 2:06 – 2:42 · How it works (voice-over, ~80 words after the cuts)

*Visuals: the architecture diagram (built up part by part as each is named), the `/demo` page with
its live trace filling in step by step, the eval scorecard, the GitHub repository.*

> From the outside, it's just a WhatsApp contact. Under the hood, it's a compound AI system:
> eight models, each with one job, and safety around every message.
>
> Muse Voice Transcribe hears the parent. Muse Spark plans the khoj and replies in the family's
> language. Muse Spark Open, an open-weights model, reflects on what the child did.
> Meta's MMS model, self-hosted, speaks the reply. Muse Image draws the card.
>
> Every message, in and out, passes Llama Guard 4, a second Muse Spark check and our own
> child-safety rules. If safety is down, nothing unchecked is sent.
>
> *(cut first)* Every change is scored on seventy-three test cases; every crisis case must pass.
>
> *(cut second)* The core is a hexagon: pure rules in the middle, and WhatsApp, the web and every
> model plugged in at the edges.

---

## 2:42 – 3:00 · Where it goes (voice-over, ~40 words)

*Visuals: a student's WhatsApp question answered with its official source links, a teacher's
chapter turned into three fields (shown, not said, to keep the part short), then the village at
dusk. No dashboard on screen.*

> Every khoj adds to the child's record, and as the child grows, it carries on into Marg's
> mentor for students, built on official sources.
>
> From a child's first *why* to their first career decision: one guide that grows with them.
> Thank you.

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
- [ ] The "seventy-three test cases" line matches the newest scorecard in `evals/results/`
      (78 golden cases as of Oct 28 evening: update after the next full run).
- [ ] Never call Marg "AI for education" or a tutor on screen or in captions: it closes the
      exposure gap by coaching the adults around a child.
- [ ] "Eight models" stays true: Muse Spark, Muse Spark Open, Muse Voice Transcribe, Muse Image,
      SAM 3.1, Llama Guard 4, MMS-TTS and the multilingual-e5 embedding model (see
      [features.md](features.md)).
- [ ] **No admin dashboard on screen** unless blurred: it shows counts from a single child, and the
      video names the village. `/status` and the `/demo` trace are safe to show.

## Sources for the facts spoken

- ASER 2024, National findings (ASER Centre), Std III children in rural government schools who
  can read a Std II level text: 23.4% (16.3% in 2022).
  <https://asercentre.org/wp-content/uploads/2022/12/ASER-2024-National-findings.pdf>
  Retrieved 2026-10-28. Also reported at
  <https://www.drishtiias.com/daily-updates/daily-news-analysis/aser-2024-and-elementary-education>.
