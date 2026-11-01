# YouTube upload: title, description, subtitles

For: Santram, uploading the final cut. Paste the title and description as they are, and upload
[video-subtitles.en.srt](video-subtitles.en.srt) as the English subtitles (YouTube Studio →
Subtitles → Add language: English → Upload file → With timing). Don't rely on auto-captions: they
mishear the accent ("don't like talent", "Lalmagard"), and anyone summarising the video, by hand
or with an AI tool, reads the transcript.

**Before uploading the final cut:** the subtitle times and the chapters below are for cut v16
(2:43). When the field-test footage replaces part 2, everything after 0:57 moves; regenerate the
subtitles from the final cut (`gen_srt.py` in the video build) and update the chapter times.

## Title

Marg.ai: a voice guide on WhatsApp for the people around a rural child (Meta hackathon, Indie track)

## Description

```text
Children in my village don't lack talent. They lack exposure: someone to ask them why.

Marg.ai is a voice-first guide on WhatsApp. It equips the people already around a child, in Hindi, Hinglish, English or Braj, to help children learn the way children learn best: through play, talk and the world around them (NCF Foundational Stage 2022, NCERT).

• Parents of 3–8-year-olds get Aaj ki Khoj, a two-minute discovery to do offline with things at home. They tell Marg what the child said, and Marg answers the child's idea with one question back.
• Children, once a parent says yes, can send Marg their own "why" by voice, in short sessions with strict child-safety rules.
• Teachers get today's chapter connected to three real fields, with a five-minute activity for 40 students.
• Older students get a mentor that cites one of 53 official sources for every fact, and says "I don't know" when there is none.

Six Meta models, each with one job:
Muse Spark 1.3 (reads what people mean, plans and replies) · Muse Spark Open, open weights (reflects on what the child did and said) · Muse Voice Transcribe (every voice note) · SAM 3.1 (drops any photo with a person, then counts what the child collected) · Muse Image (the khoj card) · Llama Guard 4 (checks every message in and out, with Muse Spark as a second check and backup).

Shown in the video:
• A real voice note on the live demo: transcribed, checked, answered in Braj and checked again, in 12.5 s for $0.0061.
• Llama Guard switched off for one take: Muse Spark checks instead, and nothing goes out unchecked.
• Hexagonal architecture: every model behind a port, so every test runs without a live model. 3,044 tests; 94 eval cases through the real pipeline (76% of the 82 scored pass; every crisis and adversarial case passes).
• Under one US cent a reply in model calls; WhatsApp's per-message fees come on top.

Try it: https://marg-ai.fly.dev/demo
Code, design and decisions: https://github.com/ssngurjar/marg-ai

Chapters
0:00 A mother's voice note
0:11 My village
0:30 What Marg is
0:57 Field test
1:31 How it works
2:13 Impact, and what's not in this video

Sources: ASER 2024 National findings (pp. 47–48); NCF Foundational Stage 2022, NCERT (pp. 38, 76); Black et al., The Lancet 2017 (250 million children under five at risk of not reaching their developmental potential).

Built during the Meta Global AI Developer Hackathon, Oct 26 – Nov 4, 2026, by Santram Gurjar. English subtitles are uploaded, not auto-generated.
```
