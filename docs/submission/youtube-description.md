# YouTube upload: title, description, subtitles

For: Santram, uploading the final cut. Paste the title and description as they are, and upload
[video-subtitles.en.srt](video-subtitles.en.srt) as the English subtitles (YouTube Studio →
Subtitles → Add language: English → Upload file → With timing). Don't rely on auto-captions: they
mishear the accent ("don't like talent", "Lalmagard"), and anyone summarising the video, by hand
or with an AI tool, reads the transcript.

**Final cut: v28 (2:58), 3 Nov.** The subtitles and the chapters below match it. Upload
`full_v28_clean.mp4` with this subtitle file, or `full_v28.mp4`, whose subtitles are burned in.
If the cut changes again, regenerate both from the new cut.
Thumbnail: `~/marg-video/thumbnail_v2.png` (1280×720): the village path, the real khoj card
Muse Image drew from a child's question, and "Talent is everywhere. Exposure isn't."

## Title

Marg.ai: exposure for every child, through the people around them (Meta hackathon, Indie track)

## Description

```text
Talent is everywhere; exposure isn't. In my village, few children have anyone to ask them why.

Marg.ai is a voice-first guide on WhatsApp. It brings children that exposure through the people already around them (parents, teachers, and older children themselves) the way children learn best: through play, talk and the world around them (NCF Foundational Stage 2022, NCERT). Today it serves rural India, in Hindi, Hinglish, English and Braj.

• Parents of 3–8-year-olds get Aaj ki Khoj, a two-minute discovery to do offline with things at home. They tell Marg what the child said, and Marg answers the child's idea with one question back.
• Children, once a parent says yes, can send Marg their own "why" by voice, in short sessions with strict child-safety rules.
• Teachers get today's chapter connected to three real fields, with a five-minute activity for 40 students.
• Older students get a mentor that cites one of 53 official sources for every fact, and says "I don't know" when there is none.

Six Meta models, each with one job:
Muse Spark 1.3 (reads what people mean, plans and replies) · Muse Spark Open, open weights (reflects on what the child did and said) · Muse Voice Transcribe (every voice note) · SAM 3.1 (drops any photo with a person, then counts what the child collected) · Muse Image (the khoj card) · Llama Guard 4 (checks every message in and out, with Muse Spark as a second check and backup).

Shown in the video:
• A real voice note on the live demo: transcribed, checked, answered in Braj and checked again, in 12.5 s for $0.0061.
• Llama Guard switched off for one take: Muse Spark checks instead, and nothing goes out unchecked.
• Hexagonal architecture: every model behind a port, so every test runs without a live model. 3,354 tests; 101 eval cases through the real pipeline (81% of the 97 scored pass; every crisis and adversarial case passes).
• Under one US cent a reply in model calls; WhatsApp's per-message fees come on top.

Try it: https://marg-ai.fly.dev/demo
Code, design and decisions: https://github.com/ssngurjar/marg-ai

Chapters
0:00 A mother's voice note
0:11 My village
0:30 What Marg is
0:57 Field test: real families, a real voice note, a real photo and khoj card
1:32 What broke, and was fixed the same day
1:47 How it works
2:29 Impact
2:49 What's not in this video

Sources: ASER 2024 National findings (pp. 47–48); NCF Foundational Stage 2022, NCERT (pp. 38, 76); Black et al., The Lancet 2017 (250 million children under five at risk of not reaching their developmental potential).

Built during the Meta Global AI Developer Hackathon, Oct 26 – Nov 4, 2026, by Santram Gurjar. English subtitles are uploaded, not auto-generated.
```
