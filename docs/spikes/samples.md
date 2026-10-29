# Village samples: voices, photos and video

What we collect from the village, why, and how. **The list itself (every voice note, text and
photo, who gives it, what they say and in which language) is in
[sample-collection-hi.md](sample-collection-hi.md), in Hindi and English, for helpers.** This
file keeps the purpose, the rules, the video consent form and the manifest.

Rewritten 2026-10-28: the MVP is now the parent journey (children 3–8, including child talk), the
Aspirational engine brings students back, SAM 3.1 needs real photos, and the demo video needs
consent forms.

## What each set is for

| Set | Used for | Can code be built without it? |
|---|---|---|
| A. Voice notes and texts | Spike A (speech-to-text accuracy, word error rate), Braj detection, the filler, silence and too-long paths, golden eval cases (spike C, the voice replies, waits until a Meta voice is cleared) | Yes. Synthetic cases stand in; these replace them and measure the real accuracy. |
| B. Photos | SAM 3.1 person check (must reject any person) and counting accuracy | Yes. The call format is verified with generated test pictures; real photos measure accuracy. |
| C. Video | The 3-minute demo video ([docs/submission/video-script.md](../submission/video-script.md)) | — |

## Ground rules

1. **Consent before every recording or photo**: read the script below; go ahead only after a
   clear yes. For anyone under 18, the parent agrees too.
2. **No names and no phone numbers**, whether spoken, written in a note, or visible in a photo.
3. **No child in any photo** in set B: no face, no hand, not in the background.
4. Voice notes are recorded **inside WhatsApp** (the mic button), so they arrive in the exact
   format the app receives (ogg/opus).
5. Everything is sent **straight to Santram, one to one**, never to a group. The helper then deletes
   their copy.
6. With every item, one line: its number, who it was (parent, child, student, teacher), the rough
   age, and for a voice note **exactly what was said, word for word**, in the script it was spoken
   in. Also note whether the person agreed to it being kept as a test file.
7. Files are stored **outside git** (`~/marg-samples/`). A sample is committed to
   `tests/fixtures/audio/` only with that person's explicit agreement and the owner's go, one by
   one (CLAUDE.md §1).

## Consent script (voice notes and photos)

> **Hindi:** "Hum Marg.ai naam ki ek WhatsApp seva bana rahe hain, jo gaon ke mata-pita ko roz
> apne bachche ke saath sikhne ke chhote khel batati hai, aur bade bachchon ko padhai aur aage ke
> raaste ke baare mein. Kya aap apni awaaz ka ek chhota message (ya ek photo) dene denge? Yeh
> sirf seva ko jaanchne ke liye istemaal hoga, kisi ko dikhaya ya share nahi kiya jaayega, aur aap
> jab kahenge hum ise delete kar denge. Aapka naam aur number kahin save nahi hoga."
>
> **English:** "We're building Marg.ai, a WhatsApp service that gives village parents short daily
> games to learn with their child, and helps older children with studies and what comes next. May
> we record a short voice message (or take a photo)? It will only be used to test the service, it
> won't be shown or shared, and we'll delete it whenever you ask. Your name and number won't be
> stored."

For a child's voice: say this to the parent first, and get their yes before the child records.

## A and B. Voice notes, texts and photos

Rewritten 2026-10-29 as one table per part in [sample-collection-hi.md](sample-collection-hi.md):
22 voice notes (A1–A22) and 4 texts (T1–T4) in Hindi and Hinglish, with Braj speakers among
parents, children and students, and teachers now that teacher bridges are built; 20 photos
(B1–B20) and the two eval photos (E1, E2).

## C. Demo video

1. **Written consent** from every adult who appears or is heard, and from the parent of every
   child who is heard or seen (form below). The Official Rules give Meta a perpetual licence to
   use and show the video.
2. **No child's face, ever.** A child may appear from behind, or as hands only. A child's voice
   only with the parent's written consent.
3. **No real names of children** anywhere: captions, audio, file names. Use a nickname.
4. Shots: see [video-script.md](../submission/video-script.md). The field test is shot raw and gets
   no voice-over.
5. B-roll: the village, a courtyard, leaves and stones, a phone in a hand. No house numbers, name
   boards or vehicle number plates.
6. Screen recordings: the editor blurs every phone number.

### Video consent form (one per adult; one per child, signed by the parent)

> **सहमति पत्र / Consent form: Marg.ai demo video**
>
> मैं सहमति देता/देती हूँ कि Marg.ai के डेमो वीडियो में मेरी (या मेरे बच्चे की) आवाज़ और
> तस्वीर (बच्चे का चेहरा नहीं) इस्तेमाल हो सकती है। मैं समझता/समझती हूँ कि:
> - यह वीडियो इंटरनेट पर सबके लिए दिखाया जाएगा (YouTube, X, हैकाथॉन की वेबसाइट)।
> - Meta और हैकाथॉन के आयोजक इस वीडियो को हमेशा के लिए, अपने प्रचार में भी, दिखा सकते हैं।
> - मेरे बच्चे का चेहरा और असली नाम नहीं दिखाया जाएगा।
> - इसके लिए मुझे कोई भुगतान नहीं मिलेगा।
>
> I agree that my voice and image (or my child's voice, and my child seen only from behind or as
> hands, never the face) may be used in the Marg.ai demo video. I understand that the video will be
> public on the internet (YouTube, X, the hackathon website); that Meta and the hackathon
> organisers may show it forever, including in their marketing; that my child's face and real name
> will not be shown; and that I receive no payment.
>
> नाम / Name: ______________  हस्ताक्षर या अंगूठा / Signature or thumbprint: ______________
>
> बच्चे के लिए (अभिभावक भरें) / For a child (filled by the parent): बच्चे की उम्र / Child's age: ____
> अभिभावक का संबंध / Relation: ______________
>
> तारीख / Date: ____________  गवाह / Witness: ______________

Keep the signed forms on paper or as photos **outside git**; they contain names.

## Manifest (fill as samples arrive; no names, no numbers)

| File | # | Who (age) | Activity | Language (dialect) | Background noise | Exact words or true count | Fixture consent |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
