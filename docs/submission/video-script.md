# Demo video: final script

For: Santram (voice-over) and the editor. Length: **3:00 at most**; the final judges watch it live.

The video has four voice-over parts and one part with **no voice-over at all**: the field test,
which is shown raw. Read at a calm pace (about 130 words a minute). The word counts are there so
the parts fit their time; if a part runs long, drop the line marked *(cut first)*.

Lines marked **[after: …]** describe something still being built. Record them only once it is
built and working; if it isn't ready by Nov 3, leave the line out. The video may only claim what
the repository shows.

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

## 0:40 – 1:05 · What Marg.ai is (voice-over, ~65 words)

*Visuals: a parent's hands holding a phone; WhatsApp open on the Marg.ai chat.*

> So I built Marg.ai. *Marg* means path. It is not a chatbot for children: the child never
> touches a screen. Marg coaches the parent, by voice, on the WhatsApp they already use, to do a
> two-minute discovery with their child every day. We call it *Aaj ki Khoj*, today's discovery.
>
> Big words. Does it actually work? This is a real field test, in my village. No narration. Just
> what happened.

---

## 1:05 – 2:05 · Field test (NO voice-over, ~60 s)

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
| **[after: photos]** A photo of collected leaves is sent | "SAM 3.1 counts what the child collected, after checking there's no person in the photo" |

---

## 2:05 – 2:45 · How it works (voice-over, ~90 words)

*Visuals: the architecture diagram (built up part by part as each is named), the `/demo` page with
its live trace of every step, the GitHub repository.*

> From the outside, it's just a WhatsApp contact, the way Instagram is just a photo app. Inside,
> it's a production system.
>
> Muse Voice Transcribe hears the parent. Muse Spark plans the khoj and replies in the family's
> language. Muse Spark Open, an open-weights model, reflects on what the child did.
> Meta's MMS model, self-hosted, speaks the reply. Muse Image draws the card.
>
> Every message, in and out, passes Llama Guard 4 and our own child-safety rules. If safety is
> down, nothing is sent.
>
> *(cut first)* The core is a hexagon: pure rules in the middle, and WhatsApp, the web and every
> model plugged in at the edges.

---

## 2:45 – 3:00 · Where it goes (voice-over, ~40 words)

*Visuals: the curiosity dashboard, then the village at dusk.*

> Every khoj adds to the child's curiosity record. **[after: Aspirational engine]** As the child
> grows, it carries on into Marg's mentor for students, where every fact comes from an official
> source.
>
> A path from a curious three-year-old to a confident first choice, for every family that has a
> phone. Thank you.

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
- [ ] Each "[after: …]" line is in the cut only if that feature is built and working.

## Sources for the facts spoken

- ASER 2024, National findings (ASER Centre), Std III children in rural government schools who
  can read a Std II level text: 23.4% (16.3% in 2022).
  <https://asercentre.org/wp-content/uploads/2022/12/ASER-2024-National-findings.pdf>
  Retrieved 2026-10-28. Also reported at
  <https://www.drishtiias.com/daily-updates/daily-news-analysis/aser-2024-and-elementary-education>.
