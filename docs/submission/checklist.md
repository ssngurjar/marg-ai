# Submission checklist

From the Participant Guide and Official Rules (read 2026-10-26). Submit on the Cerebral Valley
platform by **Wed Nov 4, 9:00 PM ET = Thu Nov 5, 07:30 IST**. Our target: **Nov 4, 23:00 IST**.

## Required

- [ ] **Public GitHub repository**, with full history (the `pre-kickoff` tag marks where code begins).
- [ ] **3-minute demo video**, publicly accessible link. It may show **only** what was built during
      the hackathon, and must make that clear. Failing to identify what's new can mean disqualification.
- [ ] Every contributor listed on the submission page (solo: just the owner).
- [ ] Track: **Indie Developer**. Problem statement: **Build for Your World**.

## README must state

- [ ] First line: what Marg.ai is, in one sentence that cannot be mistaken for a chatbot
      ("a voice-first WhatsApp coach that helps rural parents turn everyday moments into
      discovery for their 3–8-year-olds; the child never touches a screen").
- [ ] **Built during the hackathon (Oct 26–Nov 4):** all code, prompts, activity catalogue, the
      ML sidecar, the web demo. **Prepared before kickoff:** planning and design docs, golden eval
      cases (test data), the corpus source list. Point to the `pre-kickoff` tag.
- [ ] The Meta models used and how: Muse Spark, Muse Voice Transcribe, Muse Image, SAM 3.1,
      Llama Guard 4, Muse Spark Open (C9), Muse Code. The voice is Kokoro-82M (Apache-2.0, self-hosted; not Meta's).
- [ ] Safety and children's privacy: no screen for the child, consent, no photos stored, crisis path,
      medical questions referred.
- [ ] Eval scorecard and `/status` latency numbers.
- [ ] **Impact, with sources** (reach and cost, never "lives changed"): ASER 2024 p. 48 (almost
      90% of rural 14–16-year-olds have a smartphone at home); UDISE+ 2024-25 students, teachers
      and schools (check the Ministry of Education report itself); Meta's own WhatsApp India
      figure (find the primary statement); the Lancet 2016 series (250 million children under 5
      in low- and middle-income countries at risk of not reaching their developmental potential,
      2010 data, <https://pmc.ncbi.nlm.nih.gov/articles/PMC5884058>); model cost under one US cent
      per reply from our eval runs (state what it excludes: WhatsApp fees, hosting).
- [ ] **Not a banned category:** say plainly why Marg isn't an "AI for education" chatbot, a basic
      RAG app or medical advice (the child's discovery is offline; the parent is coached; the
      mentor is one part, with claims, citations and an honest "I don't know"; health questions
      are referred).
- [ ] Licences of every model and library used (the rules require them to be followed): the
      README's Licences section lists them, the sidecar's included, with the "Built with Muse
      Spark Open" and "Built with Llama" attributions. Muse Spark Open: Muse Model License; Llama
      Guard 4: Llama 4 Community License (from their Hugging Face model cards, 2026-10-29; the
      licence texts themselves are gated, read them once when logged in). Marg's own code: all rights
      reserved, viewing and running to evaluate the entry allowed (`LICENSE`, 2026-10-29). The sidecar's Hindi phonemiser (phonemizer-fork, espeak-ng) is GPL-3.0, installed
      as packages and not copied into the repo; check that the licence you choose is fine with
      that.
- [ ] How to try it: the WhatsApp number / QR and the `/demo` link.

## Demo video (3 minutes; the final round watches it live)

Superseded by [video-script.md](video-script.md) for the structure and timings; the points below still hold.

- [ ] 0:00–0:20 the problem, in the village, in one line. Not "an AI tutor".
- [ ] 0:20–1:50 a real parent and child doing a khoj: the voice prompt, the activity offline, the
      parent's voice report, the serve-and-return reply, the khoj card, a photo counted by SAM 3.1.
      No child's face; written consent from the parent covering Meta's use.
- [ ] 1:50–2:30 how it works: the live pipeline trace in `/demo`, safety both ways, Meta models.
- [ ] 2:30–3:00 the trajectory dashboard and the journey to age 18 (Phase 2), plus how to try it.
- [ ] Everything shown was built during the hackathon, and the video says so.

## Bonus prizes

- [ ] **Most Viral:** post the demo on X; submit the post link on the platform; engagement counts until Nov 8.
- [ ] **Community Vote:** share the gallery link with our network (one vote per verified account); winner announced Nov 16.
- [ ] **Best Creative Build:** the khoj card uses Muse Image; mention it in the submission.
- [ ] **Best Build on Meta Open Weight Models:** C9 runs the reflection and curiosity extraction on Muse Spark Open on Baseten. Kokoro (the voice) is not a Meta model and does not count for this prize.
