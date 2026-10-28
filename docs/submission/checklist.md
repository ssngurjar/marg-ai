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
      Llama Guard 4, Meta MMS-TTS (open weights, self-hosted; licence CC-BY-NC 4.0, stated), Muse Spark Open (C9), Muse Code.
- [ ] Safety and children's privacy: no screen for the child, consent, no photos stored, crisis path,
      medical questions referred.
- [ ] Eval scorecard and `/status` latency numbers.
- [ ] Licences of every model and library used (the rules require them to be followed).
- [ ] How to try it: the WhatsApp number / QR and the `/demo` link.

## Demo video (3 minutes; the final round watches it live)

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
- [ ] **Best Build on Meta Open Weight Models:** C9 runs the reflection and curiosity extraction on Muse Spark Open on Baseten. MMS-TTS does not count for this prize.
