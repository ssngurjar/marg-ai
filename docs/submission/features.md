# Marg.ai: what's built, and how each part works

Marg.ai is a WhatsApp contact (and a web demo page) for rural Indian families. Parents of young
children get a two-minute discovery to do with their child every day; students get a mentor
that answers only from official sources; teachers get their chapter connected to real work.
Everything here was built during the hackathon (Oct 26 – Nov 4, 2026) and is in the repository.
Items marked *(off by default)* or *(pending review)* say so.

---

## 1. For every user

### Starting: consent first
1. The user sends anything ("Hi", a voice note, a question).
2. Marg replies with what it keeps and asks for consent, with **Yes / No** buttons. On the web
   the wording says it's a demo, that a cookie identifies the browser, that no name or number is
   collected, and that **Reset** deletes everything.
3. On yes, the consent is recorded with the version of the text shown (DPDP Act 2023). On no,
   nothing is kept and the user is deleted after the reply.
4. Marg asks the role: **parent**, **student** or **teacher**. A question asked before consent
   is remembered and answered once onboarding ends.

What is stored: the role, a class, a district, the language, and for a child only a nickname
(20 characters at most) and a birth year. Phone numbers are stored only as a salted hash plus an
encrypted address for replying. Never names, schools or exact birth dates.

### Talking by voice or text
1. A voice note is downloaded, converted to 16 kHz audio and transcribed by **Muse Voice
   Transcribe**. A silent, too short or too long note gets "please send it again" without a
   model call.
2. If the transcript comes back in Gujarati, Punjabi, Bengali or Oriya script (a recognition
   slip), it's put back into Devanagari letter by letter.
3. The raw audio is deleted as soon as it's transcribed.
4. The reply comes as text, and as a voice note when the user spoke, read by **Kokoro-82M**
   (open weights, Apache-2.0) in our own ML sidecar (`services/ml_sidecar`).

### The family's language, and a village voice
- Replies come in Hindi (Devanagari), Hinglish (Roman) or English. Writing in Devanagari means
  Hindi however short; a few Roman words ("ok", "bye") never switch the family's language;
  another language counts from four words up.
- Every reply is asked for examples from village life (fields, cattle, the hand pump, the haat,
  the chaupal), never a city, a car or money to spend.
- **Braj:** someone who writes or speaks in Braj, or lives in a Braj district (Mathura, Agra,
  Bharatpur, Dholpur, Karauli and others), gets light Braj back (मेरो, गयो, नाय, छोरा, लली),
  kept easy for any Hindi speaker. *(Word list pending review with Braj speakers.)*
- Spoken replies use short sentences, about 12 words each, so they're understood heard once.

### Safety on every message
1. **Crisis phrases first** (a reviewed list): "jeene ka mann nahi", a child describing abuse…
   The fixed crisis reply with the official helpline (Tele-MANAS 14416, Childline 1098) goes out
   at once, with no model call, even if every provider is down. Crisis text isn't kept.
2. **Llama Guard 4 and a Muse Spark policy check** read every message at the same time. Llama
   Guard's self-harm flag counts only when the Muse Spark check agrees (it had flagged "doctor
   banna hai, plan bana do"); the Muse Spark check also catches what Llama Guard misses.
3. Generation may start alongside, but nothing generated is used unless the message is allowed.
4. **Every reply is checked before it's sent**: Llama Guard, with Muse Spark as a second opinion
   and backup, plus our own rules: no secrecy or attachment language to a student or child (d8),
   no personal questions to a child (d1), no danger in a child's activity (d7).
5. **Fail closed:** if the checks can't run, the user gets a fixed "we'll get back to you"
   message, never unchecked text. Nothing reaches the outbox without a passing check.

### Deleting everything
1. "Mera data hatao" (or "delete my data", "data hata do"…) → Marg asks to confirm.
2. On yes, the confirmation is sent, then every row about the user is deleted, across every
   table. A later "Hi" starts fresh. On the web, **Reset** does this in one click.

---

## 2. Parents of children aged 3 to 8: Aaj ki Khoj

### Adding a child
After the parent role, Marg asks the child's nickname and age (or birth year). Up to three
children; a parent with several is asked which child today's khoj is for, with one button each.

### Today's khoj (discovery)
1. The parent taps **Aaj ki khoj** (or says it).
2. Marg picks one of **10 reviewed activities** that fits the child's age and season and wasn't
   done in the last 30 days (shadow time, leaf families, sink or float, sound hunt…).
3. Muse Spark rewords it for this family (same steps, same materials, nothing added), with two
   to four open questions to ask and what to listen for.
4. Code adds the supervision line ("an adult stays with the child"); the reply check makes sure
   no hazard the activity didn't declare slipped in.

### Telling Marg how it went (serve and return)
1. The parent reports what the child said or did, by voice or text, optionally with a photo.
2. **Muse Spark Open** (open weights) reflects on it: praise for what the child noticed and that
   they looked for a reason, one question to extend the idea, one short tip about how children
   learn. If the child's idea isn't true (the sun doesn't move; the Earth turns), it's never
   confirmed, and the question opens the door to finding out.

### A photo of what the child made
1. Only after a khoj, and only of objects. **SAM 3.1** first checks the photo for any person or
   face: if it finds one, the photo is dropped unseen and the parent is asked to send only the
   leaves or stones.
2. Otherwise SAM counts the activity's objects ("7 leaves"), and the reflection mentions the
   number. The photo is never stored, only the counts.

### A khoj card
After an engaged report, **Muse Image** draws a card of the discovery (no child, no name in the
picture prompt), with a one-line caption checked like any reply. One card per child per day.

### The child's own question (curiosity moment)
1. "Munni poochh rahi hai, chaand roz shape kyun badalta hai?"
2. Marg gives a true, simple answer to say to the child, a two-minute way to find out together
   with things at home, and one question back. If it isn't sure, it says "let's find out
   together" instead of guessing.
3. A question about something dangerous ("saanp ke kaan kahan hote hain?") is answered, with
   "only look or talk about it with a grown-up"; the activity never involves it.

### The child talks to Marg directly
1. The parent gives one-time consent per child.
2. The child taps **Main bachcha hoon 🙋** (or says "Main Munni hoon"). Every reply is spoken.
3. Short, true answers in a child's words; never asks for personal details; never secrecy;
   always "tell Mummy and Papa too".
4. A session ends after 6 exchanges or 10 minutes, with something to go and look for; then a
   30-minute break.
5. When Marg won't answer something directly (how a gun works, "I'll hit Raju"), it replies
   like a kind elder: why, gently, and something safe to wonder about or a way to calm down,
   never a flat "I can't tell you". The blocked answer itself is never used; the redirect is
   checked like any reply.
6. The parent gets a summary of the **topics** (never the child's words), also when the child
   just walks away. A child in distress gets a child-worded crisis reply with Childline 1098.

### Questions about the child
Behaviour, food, sleep: a warm, practical answer. Health or medicine: no advice, a referral to
the anganwadi worker, the ASHA didi or a doctor.

### Daily reminder *(off by default)*
At the time the parent chose, an approved WhatsApp template with a button that opens today's
khoj. Off until the template is approved by Meta.

---

## 3. Students (classes 6–12): a mentor from official sources

### Asking anything about studies and careers
1. Marg searches **50 official documents** (scholarships, sports trials, exams, public service,
   skilling…) with hybrid search (meaning and exact keywords).
2. Every fact (an exam, a scheme, an amount, a date) is a claim citing its source; the reply ends
   with the official links. A fact with no source is never said.
3. Beside the facts, general guidance: real careers a subject leads to, what a field is, a first
   free step. If nothing relevant is found, Marg says honestly it doesn't have verified details
   yet, and still helps with paths and next steps.
4. A student who may be under 18 and mentions marriage pressure gets the child-protection line
   with Childline 1098.

*(The 50 documents are pending verification of every figure from India; NEET, JEE and a few
others are missing.)*

### A step-by-step plan
1. "Mujhe doctor banna hai, plan bana do" (or tap **Plan banao**).
2. Marg drafts three to six steps, each with an action and a timeframe, at least one free this
   week; any cost or exam step cites a source. It's saved as the student's plan.

### Memory
After each mentor turn Marg updates a short memory of the student's aims and constraints, so
later answers build on earlier ones. Where each student is heading (fields, how concrete) is
recorded for the dashboards.

---

## 4. Teachers: the chapter, connected to the world

1. "Kal class 8 mein Force and Pressure padhana hai" (or a whole subject: "economics padhne
   wale kya ban sakte hain?").
2. Marg connects it to **three real fields**, at least one outside science and one reachable
   without a degree: why it connects, a plain example of the work, a five-minute activity for
   40 students with nothing to buy and no electricity, careers, and a local hook.
3. **Aur activity** gives another activity; **Naya chapter** starts over.
4. "Dashboard" sends a 15-minute signed link to the district's anonymous numbers (groups smaller
   than five are hidden).

---

## 5. The web demo (`/demo`)
- The same pipeline as WhatsApp, with a cookie session instead of a phone number.
- Text, voice notes and photos; reply audio and khoj cards play in the page.
- **A live trace** beside the chat: each step (safety, routing, the model and which one, voice)
  appears as it happens, with its time and cost.
- Rate limits per visitor and per IP, and a daily cost cap for the demo.
- **Reset** deletes the visitor and every row about them.

## 6. For the team
- **`/status`**: success rate, latency and cost from every recorded step, and readiness.
- **`/readyz`**: database, schema, the queue (is the worker alive?), the model API, safety, the
  ML sidecar (voice and search vectors) and ffmpeg.
- **Admin dashboard** (15-minute signed link from the CLI): young learners' curiosity over time
  and students' aims, anonymous.
- **`marg eval`**: plays 73 hand-written cases through the real pipeline and scores them, by code
  and by a judge model; crisis and adversarial cases are hard gates. Latest scorecard in
  `evals/results/`: 57%, both hard gates passing.

## 7. Built to run reliably
- Every inbound message is stored once, even if WhatsApp delivers it three times; every reply
  part is sent once.
- Messages from one person a second apart become one turn.
- Several workers can share the queue: a person's turn runs under their lease; if a worker dies
  mid-turn, another takes it over and answers once.
- A failed send is retried with backoff; a failed step gets a fixed fallback, recorded.
- Old text, audio and payloads are cleared on a schedule; a deleted user is purged everywhere.
- Smoke test: 10 people at once, 50 replies, nothing lost, doubled or left silent
  (`docs/load/2026-10-28-smoke-test.md`).

## Models and where they're used

| Model | Used for |
|---|---|
| Muse Spark 1.3 | planning the khoj, parent answers, the mentor and plans, teacher bridges, child talk, the policy safety check, the eval judge |
| Muse Spark Open (open weights) | the reflection on a child's report, signals and memory extraction (Spark is its fallback) |
| Muse Voice Transcribe | voice notes to text |
| Kokoro-82M (self-hosted, not Meta's) | the voice replies |
| Muse Image | khoj cards |
| SAM 3.1 | the person check and object counts on photos |
| Llama Guard 4 | the safety check on every message and reply |
| multilingual-e5-small | embeddings for the official-source search |
