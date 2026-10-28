# Village samples: voices, photos and video

What we collect from the village, why, and how. The Hindi version for helpers is
[sample-collection-hi.md](sample-collection-hi.md); keep the two in sync.

Rewritten 2026-10-28: the MVP is now the parent journey (children 3–8, including child talk), the
Aspirational engine brings students back, SAM 3.1 needs real photos, and the demo video needs
consent forms.

## What each set is for

| Set | Used for | Can code be built without it? |
|---|---|---|
| A. Voice notes | Spike A (speech-to-text accuracy, word error rate), spike C (listening to the voice replies), the filler, silence and too-long paths, golden eval cases | Yes. Synthetic cases stand in; these replace them and measure the real accuracy. |
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

## A. Voice notes (20)

Each 5–30 seconds unless the row says otherwise. At least 6 different speakers in all.

**Parents of children aged 3–8 (the MVP; most important)**

| # | Speaker | Language | What they say |
|---|---|---|---|
| A1 | Mother | Hindi | Asks for today's activity ("aaj bachche ke saath kya karein?") |
| A2 | Father | Hinglish | Reports a khoj: what the child did and said ("Munni ne patte… aur poocha ki…") |
| A3 | Parent | Hindi | A report where the child refused or got bored |
| A4 | Parent | Hinglish | Passes on the child's question ("yeh poochh rahi hai, chaand shape kyun badalta hai?") |
| A5 | Parent | Their own dialect (Rajasthani, Bhojpuri, Haryanvi…) | Any question about the child's day |
| A6 | Parent | Hindi | A parenting worry ("bachcha khana nahi khata…") |
| A7 | Parent | Hindi or Hinglish | "Mera data hatao" or "roz ka message band karo" |

**Children aged 3–8 talking on their own** (child talk; parent's consent first)

| # | Speaker | What they say |
|---|---|---|
| A8 | Child, 4–5 | A "why" question in their own words ("paani neeche kyun girta hai?") |
| A9 | Child, 6–8 | A question about an animal or a plant |
| A10 | Child | Just "haan", "nahi" or "bye" |

**Students, classes 6–12** (the Aspirational engine)

| # | Speaker | Language | What they say |
|---|---|---|---|
| A11–A12 | Student | Hindi | "10vi ke baad kya karun?" in their own words |
| A13–A14 | Student | Hinglish | Their dream job, or a subject they like |
| A15 | Student | Dialect | Anything about school |
| A16 | Student | Any | A question naming an exam or scheme (NEET, NMMS, Navodaya, a scholarship) |

**Edge cases** (any speaker)

| # | What |
|---|---|
| A17 | A noisy place: outdoors, a fan, animals, a TV |
| A18 | Very short (under 3 seconds), or almost silent |
| A19 | Only filler sounds: "umm… hmm…" |
| A20 | One long note, **over 3 minutes** (tests the "too long" reply) |

Teacher samples are optional, only if the teacher stretch (S10) is built: "Kal main class … mein
… paath padha raha/rahi hoon…".

## B. Photos (20)

Phone camera, decent light.

**B1. Things children make or collect** (no person at all)

1. Leaves sorted into groups
2. A tower of stones
3. Shapes made of roti dough on a steel plate
4. A stick in the ground with stones marking its shadow
5. A bowl of water with some things floating and some sunk
6. A child's drawing on paper (no name written on it)
7. Folded clothes in piles

**B2. Counting** (items spread out, not touching; write the true count)

8. Exactly 7 leaves
9. Exactly 5 stones
10. Exactly 4 flowers or seeds
11. Exactly 6 small things (buttons, marbles, bottle caps)
12. About 12 leaves, some overlapping (write the true count)

**B3. Adults only (18+), with their consent.** These test that the photo is **rejected**.

13. A face, from the front
14. Only one hand, holding a leaf or a stone
15. A face cut off at the edge of the photo
16. A person far in the background, with leaves or stones in front
17. A person sitting and making something; only hands and shoulders visible
18. A printed photo or poster of a person, in the frame

**B4. Hard cases**

19. A corner of a courtyard or field with no one in it and nothing made
20. A very dark or blurry photo

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

| File | Set and number | Speaker type | Age group | Register | Accent / region | Background noise | Exact transcript or true count | Fixture consent |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
