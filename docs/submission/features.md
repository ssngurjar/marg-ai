# Marg.ai: each person's journey, what it offers, and how it ends

Marg.ai is a WhatsApp contact (and a web demo page) for rural Indian families. Parents of young
children get a two-minute discovery to do with their child every day; a child, with the parent's
yes, can ask their own questions; students get a mentor that answers only from official sources;
teachers get their chapter connected to real work. Everything here was built during the hackathon
(Oct 26 – Nov 4, 2026) and is in the repository. Items marked *(off by default)* or *(pending
review)* say so. Updated 2026-11-01.

The four journeys at a glance:

| Who | How it starts | What they get | How a conversation ends |
|---|---|---|---|
| **Parent** of a 3–8-year-old | consent → "parent" → the child's age (and a home name) → may the child talk to Marg? → today's khoj, or a question | today's khoj, a reply to how it went, answers to the child's questions and their own, a khoj card, a progress summary | each khoj ends with one question back to the child; the next one comes when asked |
| **Child** (3–8), with the parent's yes | "Main bachcha hoon" button, or "Main Munni hoon" | short true answers by voice, and something to go and find | after 6 exchanges or 10 minutes, with something to look for; the parent gets a summary |
| **Student** (classes 6–12) | consent → "student" → a parent or teacher knows → class → district | answers that cite official sources, and a step-by-step plan | each answer ends with its sources and, where it fits, a "Make a plan" button |
| **Teacher** | consent → "teacher" → subject → class → district | tomorrow's chapter connected to three real kinds of work, each with a classroom activity | "Another activity" or "New chapter" buttons |

---

## 1. For everyone

### Starting: consent first
1. The user sends anything: "Hi", a voice note, a question.
2. Marg says what it keeps and asks for consent, with **Yes / No** buttons. On the web it says
   it's a demo, a cookie identifies the browser, no name or number is collected, and **Reset**
   deletes everything. "Hi Marg, English please" starts in English.
3. On yes, the consent is recorded with the version of the text shown (DPDP Act 2023). On no,
   nothing is kept and the user is deleted after the reply.
4. Marg asks the role: **parent**, **student** or **teacher**, in buttons or in the person's own
   words ("main ek maa hoon", "sarkari school mein padhata hoon").
5. **A question asked during onboarding is kept**, whether it's about the child ("bachcha khana
   nahi khata") or about Marg ("aap kya data rakhte ho?", "naam kyun chahiye?"). Marg says it will
   answer once the profile is complete, asks its question again, and answers right after.

What is stored: the role, a class, a district, the language, and for a child only a home name (20
characters at most, never a full name) and a birth year. Phone numbers are stored only as a salted
hash plus an encrypted address for replying.

**How onboarding answers are read.** Word rules read the plain answers ("haan", "Munni, 5 saal",
"class 10") at once; when they aren't sure, **Muse Spark** reads the answer. A baby's age in
months ("6 mahine") is under two, and Marg asks for an age from 2 to 19. The ways parents spell
"child" ("baccha", "bacchi") are never taken as the child's name.

### Talking by voice or text
1. A voice note is downloaded, converted to 16 kHz audio and transcribed by **Muse Voice
   Transcribe**. A silent, too short or too long note gets "please send it again" without a model
   call. A transcript in another Indian script is put back into Devanagari.
2. The raw audio is deleted as soon as it's transcribed.
3. **Replies are text.** Meta's MMS-TTS, the only Meta speech model, is CC-BY-NC, and the
   organisers are still ruling on it (it is built in `services/ml_sidecar`, behind
   `VOICE_REPLIES_ENABLED`). The web demo reads replies aloud with the browser's own voice, which
   isn't a model call. While voice replies are off, the models don't write a separate voice
   version at all, which makes every reply faster.

### The family's language, and a village voice
- Replies come in Hindi (Devanagari), Hinglish (Roman) or English, in the language the person
  writes in. A message that only names a language ("Hindi please") switches it for good; "send it
  in Hindi" inside another request changes just that reply.
- Every reply uses examples from village life (fields, cattle, the hand pump, the haat), never a
  city or money to spend.
- **Braj:** someone who writes in Braj, or lives in a Braj district (Mathura, Agra, Bharatpur,
  Dholpur, Karauli and others), gets light Braj back (मेरो, गयो, नाय). *(Word list pending review
  with Braj speakers.)*

### Safety on every message
1. **Crisis phrases first** (a reviewed list). The fixed crisis reply with the official helpline
   (Tele-MANAS 14416, Childline 1098) goes out at once, with no model call, even if every
   provider is down.
2. **Llama Guard 4 and a Muse Spark policy check** read every message at the same time. Llama
   Guard reads the message with the turn before it, so a follow-up ("can she talk directly?") is
   understood in its conversation.
3. Generation may start alongside, but nothing generated is used unless the message is allowed.
4. **Every reply is checked before it's sent**: Llama Guard, with Muse Spark as a second opinion
   and backup, plus our own rules: no secrecy or attachment language to a child (d8), no personal
   questions to a child (d1), no danger in a child's activity (d7).
5. **Fail closed:** if the checks can't run, the user gets a fixed "we'll get back to you", never
   unchecked text.
6. **When Llama Guard keeps failing** (two timeouts within a minute), Marg skips it for up to five
   minutes and Muse Spark checks alone, instead of waiting on every message; a probe every 30
   seconds brings Llama Guard back as soon as it answers. The same breaker sits in front of Muse
   Spark Open.

### How it ends: deleting everything
1. "Mera data hatao" or "delete my data" → Marg asks to confirm. A longer message that asks for
   the same ("mera sab data mita do, ab nahi chahiye") gets a **Delete my data** button that leads
   to the same confirmation. "Phone ka data delete ho gaya" is not a deletion request.
2. On yes, the confirmation is sent, then every row about the user is deleted, across every table.
   A later "Hi" starts fresh. On the web, **Reset** does this in one click.

---

## 2. Parents of children aged 3 to 8: Aaj ki Khoj

### How it starts
After choosing "parent", the parent gives the child's age and, if they like, a home name ("Munni,
5 saal"). Marg confirms the child and asks whether they may talk to Marg directly (**Yes / Not
now**), then: **today's khoj, or a question?** Nothing is sent unasked. A question about Marg
itself during onboarding ("what can you do?", "why do you need this?") is answered at once.

### Marg understands what the parent means
Muse Spark reads every free message into one of a fixed set of intents, and code acts on it: a
report on the khoj, the parent's own question, the child's question, small talk, today's khoj, a
different khoj, the same khoj again (also in another language), adding a child, the child's home
name, the daily time, stopping daily messages, someone else writing on the parent's phone, child
talk, or deleting their data. Buttons, plain greetings and crisis phrases never need the model.
An "ok" or "thanks" in the middle of a conversation gets a short encouraging reply, not the menu
again; a complaint about Marg's last reply is answered as one. A parent's own question is
answered knowing their children's ages and what was just said, so "what else can I teach
her?" carries on the talk instead of asking her age, and a school idea the parent wants to
understand is explained simply.
Tested on 156 real-style messages in Hinglish, Hindi, Braj and English (99.7%).

### Today's khoj (discovery)
1. The parent taps **Aaj ki khoj**, or asks in any words.
2. Marg picks one of **10 reviewed activities** that fits the child's age and season and wasn't
   done in the last 30 days (animal walks, shadow time, leaf families, sink or float, sound
   hunt…). Each builds something the Foundational Stage curriculum (NCF 2022) names, through play.
3. Muse Spark rewords it for this family (same steps, same materials, nothing added), with open
   questions to ask and what to listen for.
4. Code adds the supervision line ("do this with your child, where you can see them").

### Telling Marg how it went (serve and return)
1. The parent says what the child said or did, by voice or text, or taps **Done**, optionally with
   a photo.
2. **Muse Spark Open** (open weights) replies: praise for what the child noticed, one question to
   extend the idea, one short tip. A "Done" tap with nothing said gets a short thanks and one
   question ("What did Munni say or notice?"), and a photo without words is never described:
   nothing is guessed about what happened.
3. If another khoj from the last two days is still waiting, a report goes to the khoj it's about
   ("he jumped like a frog" → the animal walk). A photo without words, or words that don't say
   which, gets **Which khoj is this about?** with a button per khoj. If the child's idea isn't true (the sun doesn't move; the Earth
   turns), it's never confirmed; the question opens the door to finding out.

### A photo of what the child collected
1. Only while a khoj is open. **SAM 3.1** first looks for a **face**: a photo with a face in it is
   dropped unseen, and the parent is asked for one without faces. A child's hands holding the
   leaves are fine.
2. SAM counts the activity's objects ("7 leaves"), and the reply mentions the number. The photo is
   never stored, only the counts.

### A khoj card
After an engaged report, **Muse Image** draws a card of the discovery (no child, no name in the
picture prompt), with a one-line caption checked like any reply. One card per child per day.

### The child's own question (curiosity moment)
"Munni poochh rahi hai, chaand roz shape kyun badalta hai?" → a true, simple answer to say to
the child, a two-minute way to find out together, and one question back. If Marg isn't sure, it
says "let's find out together" instead of guessing. A question about something dangerous is
answered with "only look or talk about it with a grown-up"; the activity never involves it.

### The parent's own questions
Behaviour, food, sleep: a warm, practical answer with one thing to try today. Health or medicine:
no advice, a referral to the anganwadi worker, the ASHA didi or a doctor. Asked about Marg itself
("what can you do?", "can my child talk to you?"), the answer sticks to what Marg really does.

### How is my child doing?
"How is my child doing?" or "Munni ne ab tak kya kiya" gets a short summary for each child,
built from the record by code: the khojs done and skipped in the last 30 days, what the child
explored, and what they asked Marg about in their own talks (topics only, never their words).

### Children and their names
Up to three children. Another child is added with "Another child" (or in words): Marg confirms
by name and asks whether they may talk to Marg too, without sending a khoj until asked. Several
children can be given in one answer ("Munni 5 aur Golu 7"): each is added and gets their own
child-talk question. With
several children, Marg asks which child today's khoj is for. A home name can be
given or changed later ("bacche ka naam Prisa hai"): it's saved and confirmed; a full name isn't.

### Daily reminder *(off by default)*
At the time the parent chose, an approved WhatsApp template with a button that opens today's khoj.
Off until Meta approves the template; the parent's chosen time is kept for then.

### Questions about Marg itself
"How do you keep my child safe?", "who sees my data?", "do you sell it?", "I can't read, how do
I use this?", "is this free?", "are you a real person?": parents, students and teachers alike get
an answer drawn only from a reviewed list of facts about Marg (`app/constants/marg_facts.py`),
each one checked against the code. Anything the list doesn't cover gets an honest "I don't know",
never a guess. The list says, among other things, that every message is checked both ways, what
is kept and for how long, that Marg never sells or shares information for ads (the small team may
read a chat only to fix a problem), that voice notes work for anyone who can't type while replies
are written for now, and that Marg is free to use.

### Questions Marg doesn't answer
Anything that isn't about their child or Marg (the weather, a poem, a ration card, a pension)
gets a kind, short "Marg can't help with that", with no activity tacked on. For a government
paper or scheme, Marg says where to ask (the gram panchayat, the anganwadi or a CSC) and never
what a scheme gives. "What model are you?" gets a plain answer: Meta's Muse Spark, with Llama
Guard checking safety. A worry that a child isn't speaking, walking or hearing as expected gets
"have it checked soon" (anganwadi or health centre) with a home idea, never "wait and see". A
question about an older child's stream or career gets real guidance and a note that the child can
write to Marg as a student. These replies are counted (`off_topic=true`).

### How it ends
Each khoj ends with the reply's question back to the child, and a card if the child was engaged.
The open khoj stays open for 48 hours; the next comes the next day, or when asked. "Roz ka message
band karo" stops the daily reminder; deleting their data ends everything (§1). "Sab band karo,
mujhe ye nahi chahiye", which could mean either, gets both as buttons (**Stop daily message** /
**Delete my data**); nothing changes until one is tapped, and deleting still asks once more.

---

## 3. The child talks to Marg directly

### How it starts
1. The parent says yes once per child (after the first khoj, or by asking "can my child talk to
   you?").
2. The child taps **Main bachcha hoon 🙋**, or says "Main Munni hoon". If a child or student seems
   to be writing on the parent's phone without that, Marg asks who is writing and answers no one
   the parent hasn't added.

### What the child gets
- Short, true answers in a child's words, and one thing to go and look at.
- Never asks for personal details; never secrecy or "our secret". "Tell Mummy and Papa too" at
  the start and end of a talk, and whenever the child talks about feelings or something that
  happened to them.
- When Marg won't answer something directly (how a gun works, "I'll hit Raju"), it replies like a
  kind elder: why, gently, and something safe to wonder about or a way to calm down. The blocked
  answer itself is never used; the redirect is checked like any reply.
- A child in distress gets a child-worded crisis reply with Childline 1098.

### How it ends
After **6 exchanges or 10 minutes**, when the child says bye or walks away, or when a parent
takes the phone back ("I am the parent", then the **Yes, I'm the parent** button): a kind goodbye with
something to go and find, then a 30-minute break before the next talk. The parent gets a summary
of the **topics**, never the child's words, and never what a child disclosed.

---

## 4. Students (classes 6–12): a mentor from official sources

### How it starts
After choosing "student", Marg asks whether a parent or teacher knows they're talking to Marg
(**Yes** goes on; **No** asks them to check at home first), then their class and district. The
district is checked against the government's official list (LGD): a close spelling or a name
typed in Hindi ("बाड़मेर") is offered back to confirm ("Is your district Barmer, Rajasthan?"), a
state alone ("Delhi") gets "which district?", and after one more try what they wrote is kept, so
no one is stuck. Teachers' districts are checked the same way.

### Asking anything about studies and careers
1. Marg searches **53 official documents** (scholarships, sports trials, exams, public service,
   skilling…) with keyword search in Postgres; Muse Spark first turns a Hindi or Hinglish question
   into English search terms and the exam or scheme names in it.
2. Every fact (an exam, a scheme, an amount, a date) cites its source, and the reply ends with the
   official links. A fact with no source is never said; if nothing relevant is found, Marg says
   honestly it doesn't have verified details yet, and still helps with paths and next steps.
3. A school question ("what is Newton's first law", "what is 3+4 and why") gets a short,
   direct answer with a village example; careers come up when the student asks about the future.
4. A student who may be under 18 and mentions marriage pressure gets the child-protection line
   with Childline 1098.

*(The documents are pending verification of every figure from India; NEET, JEE and a few others
are missing.)*

### A step-by-step plan
1. "Mera plan bana do", "Mujhe IAS ka step by step rasta batao", or the **Make a plan** button.
   Plan words go straight to the plan; other wording is read by Muse Spark. "How do I become X?"
   stays a question for the mentor, which can offer the plan.
2. Marg drafts three to six steps, each with an action and a timeframe, at least one free this
   week; any cost or exam step cites a source. It's saved as the student's plan.

### Memory
After each answer Marg updates a short memory of the student's aims and constraints, so later
answers build on earlier ones.

### How it ends
Each answer ends with its sources and, where a plan would help, a **Make a plan** button; a plan
ends with its steps saved, ready to see again ("mera plan dikhao").

---

## 5. Teachers: the chapter, connected to the world

### How it starts
After choosing "teacher", Marg asks the subject, the class and the district. A chapter mentioned
on the way ("class 8, kal bal aur dabav padhana hai") is kept and answered once the profile is
done.

### What the teacher gets
- **Teaching help:** "how do I start this so everyone understands?", "students confuse mass and
  weight": an opening from village life, the idea in three simple steps, a question to check
  they understood, and a mistake students often make. Marg remembers the chapter, so a follow-up
  needn't name it again.
- **The bridge:**
1. "Kal class 8 mein Force and Pressure padhana hai", or a whole subject.
2. Marg connects it to **three real fields**, at least one outside science and one reachable
   without a degree: why it connects, a plain example of the work, a five-minute activity for 40
   students with nothing to buy and no electricity, careers, and a local hook.
3. "Dashboard" sends a 15-minute signed link to the district's anonymous numbers (groups smaller
   than five are hidden).
- **A worry about a child:** "ek bachcha roz chot ke nishaan lekar aata hai" gets fixed, reviewed
  steps, never a lesson: talk to the child gently and alone, don't promise secrecy, tell the head
  teacher today, and the Child Helpline (1098) if the child may be unsafe.
- **Anything else** (a transfer, salary, leave): an honest "I help with teaching", and the way
  back to a chapter.

### How it ends
Each bridge ends with **Another activity** (one more activity for the same chapter) and **New
chapter** (start over).

---

## 6. The web demo (`/demo`)
- The same pipeline as WhatsApp, with a cookie session instead of a phone number.
- Text, voice notes and photos; khoj cards show in the page; **🔊 Listen** reads a reply aloud.
  While recording, the mic turns into a green ⏹ with a timer; tap it or Send to send.
- **A live trace** beside the chat: each step (safety, routing, which model, how long, what it
  cost) appears as it happens.
- Rate limits per visitor and per IP, and a daily cost cap.
- **Reset** deletes the visitor and every row about them.

## 7. For the team
- **`/status`**: success rate, latency and cost from every recorded step, and readiness.
- **`/readyz`**: database, schema and the queue (is the worker alive?) are critical; the model
  API, safety and ffmpeg are checked too.
- **Admin dashboard** (15-minute signed link from the CLI): young learners' curiosity over time
  and students' aims, anonymous.
- **`marg eval`**: 99 hand-written cases through the real pipeline, scored by code and by a judge
  model; crisis and adversarial cases are hard gates.
- **Understanding banks**, run live in one command each: 156 parent messages
  (`scripts.intent_bank`), 72 onboarding answers (`scripts.onboarding_bank`) and 37 student
  messages (`scripts.student_route_bank`); each fails below 97%.

## 8. Built to run reliably
- Every inbound message is stored once, even if WhatsApp delivers it three times; every reply part
  is sent once.
- Messages from one person a second apart become one turn.
- Several workers can share the queue: a person's turn runs under their lease; if a worker dies
  mid-turn, another takes it over and answers once.
- A failed send is retried with backoff; a failed step gets a fixed fallback, recorded.
- A provider that keeps failing is skipped for a while (the breakers in §1), so one slow host
  doesn't slow every reply.
- Smoke test: 10 people at once, 50 replies, nothing lost, doubled or left silent
  (`docs/load/2026-10-28-smoke-test.md`).

## Models and where they're used

| Model | Used for |
|---|---|
| Muse Spark 1.3 | reading what people mean (parents, students, onboarding answers), rewording the khoj, parent answers, the mentor and plans, teacher bridges, child talk, the policy safety check and backup, the eval judge |
| Muse Spark Open (open weights) | the reply to a child's report, signal and memory extraction (Spark is its fallback) |
| Muse Voice Transcribe | voice notes to text |
| Muse Image | khoj cards |
| SAM 3.1 | the face check and object counts on photos |
| Llama Guard 4 | the safety check on every message and reply |

## Glossary

| Term | Meaning |
|---|---|
| **Khoj** (Aaj ki Khoj) | "Today's discovery": a two-minute activity a parent does with the child, offline, with things at home |
| **Serve and return** | The child says something, the adult answers it and asks one question back; what Marg's reply to a report does |
| **Curiosity moment** | Marg's answer to a question the child asked, with a way to find out together |
| **Child talk** | A child talking to Marg directly, with the parent's one-time yes, in short sessions |
| **Khoj card** | A picture of the child's discovery, drawn by Muse Image after an engaged report |
| **Intent** | What a message means (a report, a question, "send it again"…), read by Muse Spark; code decides what to do with it |
| **Bridge** | For a teacher: a chapter connected to three real kinds of work, with classroom activities |
| **Plan** (roadmap) | For a student: three to six steps toward a goal, each sourced where it involves cost or an exam |
| **Fail closed** | When safety checks can't run, a fixed holding reply goes out, never unchecked text |
| **Breaker** | A switch that skips a provider while it keeps failing, so its backup answers at once |
| **Hard gate** | An eval case family (crisis, adversarial) that must pass every time |
