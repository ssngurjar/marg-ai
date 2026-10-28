# Pending owner review (Santram)

Everything built or decided so far that waits for the owner's review. Tick an item when it's
reviewed; anything changed goes into that step doc's Decisions log in the same commit.

Last updated: 2026-10-27 (after the S5 and S8 phone checks; both ticked in plan.md, pending this review).

## 1. Safety host (decided 2026-10-27)

- [x] Groq retired Llama Guard 4 (2026-03-05); the owner chose **DeepInfra**
  (`meta-llama/Llama-Guard-4-12B`, $0.18/1M). NVIDIA's free endpoint was ruled out for real users
  (trial terms: no production use, content may be used to improve NVIDIA products).
- [x] DeepInfra balance added; spike B run (`docs/spikes/safety-guard.md`).
- [x] Spike B follow-up decided: crisis phrase rules + Muse Spark policy check on every user
  message; Llama Guard S1/S2/S4 need confirmation, S11 always counts; token cap 800. The full
  check got 36/36 right on two runs.
- [x] WhatsApp token replaced with a permanent System User token (2026-10-27).
- [x] **S5 phone check passed** (2026-10-27): Hinglish, Hindi and English questions answered with
  every reply checked; voice note → "can't read this yet". It surfaced two Llama Guard problems,
  both now covered (below and s07 log): DeepInfra timeouts and overload, and a harmless answer on
  teaching colours flagged with a different code each time (S2, S4, S8).
- [x] DeepInfra is the only production host for Llama Guard 4, and it failed on day one (timeouts,
  then `429 engine_overloaded`). Decided: Muse Spark backs it up (s07 log, CLAUDE.md §11).
- [x] A Llama Guard flag on our reply gets a Muse Spark second opinion before blocking (s07 log).
- [ ] **Review the safety behaviour you approved today** in `app/safety/safety_gate.py`'s
  docstring and the s07 decisions log: Llama Guard's 1.5 s limit, the Muse Spark backup on both
  sides, the second opinion on reply flags, and `TIMEOUT_SAFETY_OUT_S` 6 s.

## 2. S5 copy (users read these words)

- [ ] Crisis replies, `app/constants/crisis_replies.py`: SELF_HARM (Tele-MANAS 14416, source
  pib.gov.in) and ABUSE (Child Helpline 1098, source wcd.gov.in), each in Hinglish, Hindi and
  English. 112 is left out until it's copied from an official page that states it (S7).
- [ ] Fixed replies, `app/constants/fixed_replies.py`: TRY_AGAIN_LATER, HOLDING, REPEAT_PLEASE,
  UNSUPPORTED_MEDIA, REFUSE (HARMFUL, PRIVACY, MEDICAL, GENERAL, GENERIC). Wording avoids
  gendered verbs, since a parent may be a mother or a father.
- [ ] **Crisis phrase list**, `app/constants/crisis_lexicon.py` (v1): self-harm phrases and
  the abuse people/harm lists in Hindi, Hinglish and English. Recall first; brothers and
  cousins left out so sibling fights stay parenting questions. Ideally also checked by a
  counsellor or teacher (s07 Q2).
- [ ] **Backup reply check prompt**, `app/prompts/reply_policy.md.j2` (v1.0.0): used only when
  Llama Guard is down; what counts as harmful, self-harm, medical instructions, or endangering a
  child.
- [ ] **Safety policy prompt**, `app/prompts/minor_policy.md.j2` (v1.0.1): what counts as a
  self-harm signal, an abuse disclosure, a medical request, and a harmful request.
- [ ] Known false positive you accepted: "pakka IAS ban jaunga na?" gets the crisis reply when
  Llama Guard tags it S11.
- [ ] The parent-answer prompt, `app/prompts/parent_answer.md.j2` (v1.0.0): warm and play-based,
  one thing to try today, no medical advice, no facts or figures, no labelling a child, and the
  parent's message treated as data.
- [ ] Optional: show these texts to two or three parents in the village and note what reads oddly.

## 2b. S8 onboarding (built 2026-10-27)

- [x] `WHATSAPP_DISPLAY_NUMBER` set in `.env` from the account's own number (read from Meta with
  the new token, 2026-10-27).
- [x] **S8 phone check passed for parents** (2026-10-27): consent → parent → child (nickname and
  birth year only) → child-talk consent; "mera data hatao" → confirm → every table empty for that
  user, purged right after the reply was delivered.
- [ ] **Teacher path on the phone** (covered by tests only): after `Hi` and consent, tap **Main
  teacher hoon**, answer subject, class and district, and check the invite link opens a chat
  with Marg with "Namaste Marg" typed in.
- [ ] **Onboarding copy**, `app/constants/onboarding_copy.py` (`onb-2026-10-27.1`): the consent
  intro (the legally important text), the role question (parent / teacher), student "coming
  soon", the child question, child-talk consent, the teacher invite and waiting messages, the
  deletion confirmation, in Hinglish, Hindi and English. Hinglish comes from s08; Hindi and
  English are translations, and the MVP-only entries are new.
- [ ] **Profile extraction prompt**, `app/prompts/profile_extraction.md.j2` (v1.1.0).
- [ ] Known limit: if a user taps two onboarding buttons faster than one turn, only the last
  counts (the first is asked again).

## 2c. S10b parent journey (from 2026-10-27)

- [ ] **The 10 launch activities**, `content/activities/*.yaml`: enabled on 2026-10-27 as
  "reviewed by: owner" so building could start. Still to do: a real read by the owner, then a
  village review by a parent and an anganwadi worker or teacher; any change bumps `version`.
- [ ] **Journey copy**, `app/constants/journey_copy.py`: the supervision line, the "Poochiye /
  Dhyan dijiye" labels, the khoj buttons, "which child?", "coming soon for this age", the
  reflection fallback. Three languages.
- [ ] **Prompts**: `activity_personalise.md.j2` (v1.0.2) and `parent_reflection.md.j2` (v1.0.0).
  Live check 2026-10-27: personalisation fine in all three languages (3.5-4.1 s); reflections on
  Muse Spark Open were specific and warm, including for a child who refused (4-6 s).
- [ ] **Word lists**: child hazards (`app/constants/child_hazards.py`, the d7 rule) and words a
  khoj or reflection may not use (`journey_words.py`: careers, exams, labels for a child).
- [ ] Known behaviour to accept or change: the d7 rule also runs on parent answers, so an answer
  that warns about a road or fire ("keep her away from the road") is blocked and replaced with
  the generic redirect.
- [ ] **Submit the nudge templates** in WhatsApp Manager (`marg_daily_khoj` in hi + en,
  `marg_daily_khoj_hinglish` in en) and note the category Meta gives them. Their body must match
  the text recorded on each nudge turn word for word (`app/constants/fixed_replies.py`, NUDGE:
  "Aaj ki khoj taiyaar hai! 2 minute, bachche ke saath." / "आज की खोज तैयार है! 2 मिनट, बच्चे के
  साथ।" / "Today's discovery is ready! 2 minutes, with your child."), with one quick-reply
  button. Once approved, set `NUDGES_ENABLED=true` in `.env` (sending is off until then).
- [ ] **Nudge copy**, `app/constants/journey_copy.py`: "Roz ki khoj ka message kab bhejein?"
  (sent after the first khoj), the buttons "Subah 8 baje" / "Shaam 6 baje" / "Khud poochhenge"
  (s10b said "Main khud poochunga", which is masculine), and the on/off confirmations.
- [ ] **Phone test (nudges):** after onboarding a new child, tap "Subah 8 baje"; write "time
  badlo" and "roz ka message band karo". Once templates are approved: wait for 8:00 IST.

## 2d. S6 voice (from 2026-10-27)

- [ ] **Fixed copy**, `app/constants/fixed_replies.py`: "please repeat" no longer says "write it"
  (v2, it now answers voice notes too); the new "too long" reply, in three languages.
- [ ] **Hinglish fixed replies are spoken from the Hindi text** of the same reply (the Hindi
  voice reads only Devanagari). Listen to a few, e.g. the crisis reply, before the demo.
- [ ] **Speech-to-text hint words**, `app/constants/stt_keywords.py` (v1): Marg, khoj, aaj ki
  khoj, doosri khoj, anganwadi, ASHA didi. Add words parents use that it mishears.
- [ ] **Filler sounds**, `app/domain/rules/filler_detector.py`: a voice note of only "umm",
  "hmm", "अं"… gets "please repeat". Short real answers ("haan", "nahi", "accha") are never
  filler.
- [ ] **Safety on spoken text** (S6): safety_out now classifies the spoken text along with the
  text when they differ (the voice note reads the spoken text). Llama Guard sees a little more
  per reply; a harm only in the spoken text now blocks the reply.
- [ ] **Phone test**: send a voice note in Hinglish and in Hindi; check the transcript in the
  reply, the voice reply's sound, and a silent or 1-second note ("please repeat").
- [x] **Voice for the demo** (decided 2026-10-28, s06 log): MMS-TTS is the voice in the video and
  the submission; Indic Parler-TTS is on hold (no GPU host) and stays switchable with `TTS_ENGINE`.
  **Superseded 2026-10-29:** Kokoro-82M (Apache-2.0) is the voice, the female Hindi blend at 1.1×
  (owner's pick by ear, s06 log). Set `TTS_ENGINE=kokoro` in `.env` and start marg-ai-tts with it.
- [ ] **Excited spoken wording** (2026-10-29): parent_reflection 1.2.2, child_talk 1.0.4 and
  curiosity_moment 1.0.4 open the spoken text with real wonder ("वाह! … कमाल कर दिया!", "अरे
  वाह, क्या बढ़िया सवाल है!"), short sentences and "!", calm for anything dangerous. Listen on
  the phone.
- [x] **Ask the organisers** (no longer needed: Kokoro replaced MMS, C8 closed 2026-10-29) in #office-hours whether MMS-TTS (CC-BY-NC 4.0) is fine in a
  hackathon submission, and keep the answer (C8).
  - 2026-10-28, #office-hours auto-reply: an Apache-2.0 TTS model alongside the Meta models is
    fine ("None of the listed Meta models do text-to-speech"); whether CC-BY-NC fits a
    prize-winning submission "is for the organizers to rule on", question passed to them.
    Pending their answer.

## 2e. Curiosity moment, C11 (from 2026-10-27)

- [ ] **Prompt** `app/prompts/curiosity_moment.md.j2` (v1.0.0). Live check 2026-10-27 (synthetic
  messages, Muse Spark 1.3): moon phases, rain (Hindi) and plants (English) gave a true, simple
  answer, a 2-4 step mini-activity from the materials list, a question back and a gentle
  "people who study this…" line, in 2.3-5.7 s. "Bukhar kyun aata hai?" and "neend poori nahi
  hoti" correctly went to the parent answer.
- [x] **Decided 2026-10-28: (b), talk about it, never do it.** Was: may an answer *talk about* a d7 hazard? "Saanp ke kaan kahan hote hain?" can't
  be answered without the word snake, which d7 blocks in every journey reply, so the parent gets
  the fixed fallback below. Options: (a) keep d7 strict everywhere (now); (b) let `say_to_child`
  name an animal or thing the child asked about, while the mini-activity stays strict; (c) send
  hazard topics to "ask the anganwadi didi". Recommended: (b), with a short list of "talk about,
  never do" topics (snake, scorpion, fire, river).
- [ ] **Copy**, `app/constants/journey_copy.py`: the "Saath mein pata lagaiye (2 minute)" and
  "Phir bachche se poochiye" labels, the "let's find out together" opening, and the fallback
  ("Bahut accha sawaal hai! Iska jawab abhi nahi de paaye. Bachche se poochiye…").
- [ ] **Words that push a child toward a job** (`EXPOSURE_PUSH_WORDS` in
  `app/constants/journey_words.py`): "tum bhi ban sakti ho", "banna chahiye"… blocked in the
  "who explores this" line.
- [ ] **The trigger** (`app/domain/rules/child_question_detector.py`) is stricter than s10b
  wrote: it needs an asking word ("poochh rahi", "asked", "पूछ") or the child's nickname, so a
  plain "beta … kya karein?" stays a parent question. Check it on real parent messages.
- [ ] **Phone test:** "Munni poochh rahi hai, chaand roz shape kyun badalta hai?" (text and voice).

## 2f. Child talk, C13 (from 2026-10-27)

- [ ] **Prompt** `app/prompts/child_talk.md.j2` (v1.0.0). Live check 2026-10-27 (synthetic
  messages): short, true answers for ages 4-7 in all three languages (2.3-6.1 s); "yeh hamara
  secret hai, tum meri best friend ho" → no secret, "tell Mummy and Papa everything"; a
  medicine question → "tell Mummy and Papa now".
- [ ] **Child copy**, `app/constants/child_talk_copy.py`: hello, goodbye (with a find-out
  activity), "Mummy-Papa ko bhi batana", "Yeh kaam Mummy-Papa karenge", cooldown, the parent's
  summary (topics only), the "not switched on" message to the parent, the
  "Main bachcha hoon 🙋" button, and the topic names. Ideally a counsellor or teacher reads it.
- [ ] **Child crisis texts** (same file): self-harm/sadness and abuse, in a child's words, with
  1098 (from the official source in `crisis_replies.py`). After sadness the parent gets a gentle
  note with Tele-MANAS 14416; after an abuse disclosure the parent is told nothing (C15).
- [ ] **Word lists**, `app/constants/child_safety_words.py`: secrecy/attachment phrases (d8, on
  every reply) and personal topics a reply may not ask a child about (d1). Note: "राज़" also
  matches "राज" (rule, kingdom) after normalising.
- [x] **Decided 2026-10-28: fixed as recommended (`RegisterChooser`).** Was: language for short messages. The register detector reads "bye", "Main Munni
  hoon" and your English-detected voice note as English. Child talk now uses the family's
  onboarding language; for parents each message is still re-detected. Recommended: re-detect
  only when a message has at least 4 words or is in another script.
- [ ] **Abandoned sessions:** a child who stops without "bye" is closed after 10 minutes, but
  the parent's summary for it is only sent once nudges (a turn-less sender) exist.
- [ ] **Phone test:** with child talk on for a child, tap "Main bachcha hoon 🙋" on a khoj, ask
  two questions by voice, say "bye"; check the goodbye and the summary. Also try "mera data
  hatao" inside the session (nothing should change).

## 2g. Curiosity signals, S13 (from 2026-10-27)

- [ ] **Prompt** `app/prompts/curiosity_extract.md.j2` (v1.0.0, Muse Spark Open). Live check
  2026-10-27 (synthetic reports): "kuch nahi kaha" → 0; "bola suraj" → 1; an engaged answer →
  2; a new idea of the child's own → 3 with "asked"; all six on Open in 1.5-3.2 s. It records
  domains and engagement only, never a label.
- [ ] The young-learner trajectory (sessions, breadth, engagement slope, question rate) is
  computed and tested; the admin dashboard that shows it is **not built yet**.

## 2h. Khoj card, C6 (from 2026-10-27)

- [ ] **Look at a live card**: one was made on 2026-10-27 (shadow-time): a textless Madhubani /
  Warli-style triptych of a tree's shadow at morning, noon and evening, with the caption "Munni ne
  parchhai ka raaz khoja! / Din mein parchhai hilti rahi, raat ko kahan gayi, Munni ne poocha!"
  (18 s to make, about $0.01).
- [ ] **Card style and the 10 activity scenes**, `app/constants/khoj_card_style.py` (v1, from
  spike F). Ideally look at one card per activity before the demo.
- [ ] **Caption prompt**, `app/prompts/khoj_card_text.md.j2` (v1.0.0).
- [ ] **When a card is sent:** only after a report with engagement 2 or more, at most one per
  child per day, only while the parent's 24-hour window is open. Safety: if Llama Guard is down
  or flags it, no card (there's no backup check for images).
- [ ] **Spike F decisions** (section 4): images at `low` strength and `KHOJ_CARD_ENABLED=true`
  are what's built; tick them there if you agree.
- [ ] **Phone test:** report a khoj with a detailed answer ("Munni ne kaha… aur poocha…") and
  wait for the card after the reflection; forward it to someone.

## 2i. Web demo, S14 (from 2026-10-27)

- [ ] **Try it**: open `<tunnel URL>/demo`, say Hi, go through onboarding as a parent, ask for
  "aaj ki khoj", report back, record a voice note, press Reset. The right panel shows every step.
- [ ] **JSON instead of multipart** for messages (a voice note as base64): FastAPI's form parsing
  needs `python-multipart`, a new dependency you haven't approved. Say if you'd rather add it.
- [ ] **Page copy**: the tagline and footer in `app/static/demo/index.html` (English only), and
  the error messages in `demo.js`. The web consent text is still the WhatsApp one (s14 §4.9
  wants a web variant saying a cookie identifies the browser).
- [ ] **Limits**: 30 messages per visitor per hour, 90 per IP, 20 new sessions per IP, and
  $5 of web spend per India day (`DAILY_COST_CAP_USD`).
- [ ] **Not in this build**: the admin dashboard (S13). Photos on the web are built (2j).

## 2j. Activity photos, C7 (from 2026-10-28)

- [x] **Decided 2026-10-28** (s10b log): any person refuses a photo, a hand too; web photos are
  held only until their turn has looked at them (≤ 10 minutes); a reviewed list of what to count
  per activity.
- [ ] **What each activity counts** (`photo_count_phrases` in `content/activities/*.yaml`, each
  bumped to version 2): leaf-families `leaf`, stone-tower `stone`, shadow-time `stone`,
  sink-or-float `stone, leaf, bottle cap`; the other six count nothing (a photo is welcomed and
  thanked without a number).
- [ ] **Photo copy**, `app/constants/fixed_replies.py`: PHOTO_HAS_PERSON ("Is photo mein koi
  insaan dikh raha hai, isliye humne ise turant hata diya…") and PHOTO_NOT_NEEDED, in three
  languages.
- [ ] **Prompt** `parent_reflection.md.j2` v1.1.0: the counts (never the photo) are given to the
  model, which may say "5 patthar!" and build its question on them.
- [ ] Known behaviour to accept or change: a photo sent with a report that contains a person ends
  the turn with PHOTO_HAS_PERSON; the khoj stays open and the parent can send the report again.
- [ ] Known behaviour: a photo with no words gets no curiosity signals and so no khoj card (both
  need the parent's words).
- [ ] **Phone test:** during a khoj (e.g. "Pattharon ka minar"), send a photo of the stones with no
  people; then a photo with a hand in it (should be refused); then a photo with no khoj open.
- [ ] **Web test:** the 📷 button on `/demo`, the same three cases.
- [ ] **Real photos** (`samples.md` set B) to measure the person check and counting beyond the 15
  synthetic test pictures (`docs/spikes/images.md`).

## 2k. /status and the admin dashboard, S13 (from 2026-10-28)

- [x] **Decided 2026-10-28:** the admin view shows counts from a single child; everyone else's
  floor stays 5.
- [x] ~~Run `make migrate`~~ (done 2026-10-28, database at `s04_user_leases`), then open
  `http://127.0.0.1:8000/status`, and `.venv/bin/python -m app.cli admin-link` for the dashboard.
- [ ] **Look at the pages**: wording of the tiles and headings, what you'd want on screen in the
  video (`/status` and the `/demo` trace are safe to film; the dashboard isn't, or blur it).
- [ ] Build choices in the s13 log (pages built without Jinja2, 503 instead of a partial status,
  admin-only claims for now).

## 2l. The Aspirational engine: corpus, mentor, roadmap, memory (S11, S12, from 2026-10-28)

- [x] ~~Run `make migrate`~~ (done 2026-10-28, database at `s04_user_leases`); voice server started and corpus ingested on 2026-10-28 (50 documents, 235 chunks). Was: start the voice server (it now also serves
  `/embed`; first start downloads multilingual-e5-small, about 470 MB), then
  `.venv/bin/python -m app.cli ingest-corpus`.
- [ ] **Review the corpus: 50 documents in `corpus/`** (scholarships 18, sports 7, exams 10,
  public service 5, exposure fields 6, entrepreneurship 3, skilling 1). Drafted by agents from the
  official pages, and every file passes the validator, **but check every number from India before
  trusting it**: WebFetch returns a model's reading of a page, not the raw text (the scholarship
  amounts were checked against page images; most others weren't). Use the s11 §4.2 checklist.
- [ ] **Things the agents flagged:** several scholarship guideline periods end with 2025-26 (still
  the documents the portals link); PMS-SC allowances may now be higher than the 2021 figures; the
  Pragati guideline is dated 2020-21; `rajasthan-scholarship-documents.md` was translated from a
  Hindi PDF; ISRO YUVIKA 2026 is over; `sai-selection-trials.md` lists October 2026 trials (stale
  soon); INSPIRE-MANAK 2026-27 nominations closed; `sainikschoolsociety.in` is not a .gov.in
  domain (check it's official); a few generic advice lines in the sports docs aren't from pages.
- [ ] **The biggest gaps, which only a fetch from India can fill:** NEET, JEE Main, Navodaya
  (class 6 and 9), UPSC / NDA, SSC, Agniveer, PMKVY, ITI and apprenticeships, AICTE, NSS, ST and
  minority scholarships. Their sites refused us from abroad. Until then the mentor honestly says
  it doesn't know (e.g. "doctor banna hai").
- [ ] Fix in `corpus/SOURCES.md`: `pmegp.in` is a domain-for-sale page; `kviconline.gov.in` and
  `pmkvyofficial.org` don't resolve.
- [ ] **Prompts:** `mentor.md.j2`, `roadmap.md.j2`, `memory.md.j2`, `query_rewrite.md.j2` (all
  1.0.0). **Copy:** `app/constants/student_copy.py` (sources label, "Plan banao", the don't-know
  and no-plan texts, the child-protection line with 1098) and the onboarding change (third role
  button, `onb-2026-10-28.1`).
- [ ] **Decide later:** the 0.80 relevance threshold (10/11 right; the kabaddi question just
  missed, s11 log); whether to turn on query rewriting after the S15 eval.
- [ ] **Aspiration signals** (prompt `aspiration_extract.md.j2` 1.0.0, Muse Spark Open): the
  0-4 specificity rubric and the field and constraint lists (s13 §4.3); the dashboard now has a
  students section next to the young learners (admin only).
- [ ] **Phone test:** "Main student hoon" → guardian → class → district; then "क्लास 8 में कोई
  स्कॉलरशिप मिलती है क्या", "Marine biologist kaise bante hain", "ISRO scientist banna hai, plan
  bana do", "mera plan dikhao".

## 2m. Teachers: the Exposure layer and district dashboards (S10, from 2026-10-28)

- [ ] **Fill `corpus/curriculum/ncert_chapters.yaml` from India** (classes 6-10, Science, Maths,
  Social Science, English and Hindi medium, from the official book pages on ncert.nic.in only).
  It ships empty because the site refused us; bridges still work from the teacher's own words.
- [ ] **Prompt** `exposure.md.j2` 1.0.0 and **copy** `app/constants/teacher_copy.py` (labels,
  "Aur activity" / "Naya chapter", ask-for-chapter, the dashboard-link text), and the new
  `PROFILE_DONE_TEACHER` (asks for a chapter, keeps the parents' invite link).
- [ ] **Decide:** should a teacher's own career question go to the mentor? Now every teacher
  message is an exposure message (no model routing).
- [ ] **Phone test:** onboard as a teacher (class 8, science, your district); send "Kal class 8
  mein Force and Pressure padhana hai"; tap Aur activity; send "बच्चों को कुछ नया सिखाना है";
  tap Naya chapter; send "dashboard" and open the link.

## 2n. Several workers: leases and LISTEN/NOTIFY (E1 upgrade, s04, from 2026-10-28)

- [x] `make migrate` run by the owner on 2026-10-28: the local database is at `s04_user_leases`.
- [ ] **Decide:** keep the worker inside the api by default (`RUN_WORKER_IN_API=true`, one process,
  what the demo uses), or run `python -m app.worker` beside the api (`make worker`). Both are safe
  with leases. Recommended: keep the default for the hackathon.
- [ ] **For Neon later:** set `DATABASE_LISTEN_URL` to the direct (non-pooler) connection string;
  without it, replies still work, but a separate worker polls every 2 s.
- [ ] **Try it:** run `make up` with `RUN_WORKER_IN_API=false` and `make worker` in two terminals,
  then send a WhatsApp message: one reply. Kill one worker with `kill -9` mid-turn: the other
  answers within about a minute.

## 2o. The web demo's live trace (E2 upgrade, s14, from 2026-10-28)

- [ ] **Try it:** open `/demo`, send "Hi": the trace on the right fills in step by step while the
  reply is being made (no one-second jumps). Stop the database for a moment: a small
  "reconnecting…" pill shows, and replies still arrive by polling.
- [ ] **Decide:** the stream sends the whole turn each time (one `turn` event) rather than the
  three event types the design named. Recommended: keep it (simpler, and replays are harmless).
- [ ] **Bug fixed on the way:** a web visitor's khoj card was sent to WhatsApp and failed; it
  now goes to their page, live.

## 2p. Summary when a child walks away mid-talk (s10b §4.16, from 2026-10-28)

- [ ] **Decide:** the summary for a session the child left without "bye" is sent by
  maintenance with the reviewed copy only, and checked by code, not by Llama Guard (nothing in
  it was written by a model). Recommended: keep it.
- [ ] **Phone test:** start child talk, ask one question, then stop replying for 10 minutes:
  the parent gets "Mummy-Papa ke liye: aaj Munni ne … ke baare mein baatein ki" once.

## 2q. The web demo's consent wording (s08, s14 §4.9, from 2026-10-28)

- [ ] **Review the legal copy:** `_INTRO_WEB` in `app/constants/onboarding_copy.py` (Hinglish,
  Hindi, English): "Yeh ek demo hai: is browser ko sirf ek cookie se pehchana jata hai, aapka
  naam ya phone number nahi liya jata … Upar 'Reset' dabakar kabhi bhi sab delete kar sakte
  hain." WhatsApp's wording is unchanged. Copy version `onb-2026-10-28.3`.

## 2r. The eval scorecard (S15, from 2026-10-28)

- [x] `EVAL_DATABASE_ADMIN_URL` added to `.env` beside `DATABASE_URL` (the test Postgres; each
  run creates and drops its own `marg_eval_*` database there). `MODEL_JUDGE` and
  `TIMEOUT_JUDGE_S` have defaults.
- [ ] **Read the scorecard** in `evals/results/` (the newest `.md`): the honest pass rate, the
  hard gates (crisis, adversarial) and every failing case with the judge's reason.
- [ ] **Collect the two photo fixtures** for parent-journey-010/011 (`evals/fixtures/images/`:
  leaves only; and a consented adult holding leaves, never a child). Until then they're skipped.
- [ ] **Decide:** the judge's token cap went from 2000 to 6000 (it was cutting answers off), and
  the judge sees only the cited sources, not every retrieved one. Recommended: keep both.

## 2s. Safety and deletion fixes from the first eval run (2026-10-28)

- [x] **Decided:** Llama Guard's self-harm flag (S11) counts only when the Muse Spark check agrees
  (it had sent the crisis reply to "Doctor banna hai, plan bana do").
- [ ] **Review crisis lexicon v1.1** (`app/constants/crisis_lexicon.py`): "jeena nahi hai",
  "jeene ki ichha nahi", "apne aap ko nuksan / khatam" and their Hindi.
- [ ] **Review the added deletion phrases** (`OnboardingAnswerParser.DELETION_PHRASES`):
  "data hata do", "data mita do", "remove my data", "डेटा हटा दो" and similar. Each still asks
  for a yes before anything is deleted.

## 2t. Hardening (S16, from 2026-10-28)

- [x] **Smoke test accepted (2026-10-28):** 10 visitors, 50 replies, nothing lost or doubled;
  p95 wait 14.9 s against 12 s, kept as is.
- [ ] **Your WhatsApp token:** reading the phone number or `/me` with it fails (Graph error 200,
  a permissions error), so `/readyz` can't check it. Send "Hi" from your phone before filming;
  make it a permanent system-user token before judging.
- [ ] **Walk the pre-demo checklist** (`docs/submission/pre-demo-checklist.md`) the day before
  submission.

## 2u. Braj, village examples and short spoken sentences (from 2026-10-28)

- [ ] **Check the Braj words with people in your village** (`app/constants/braj_words.py`): the
  markers that tell a Braj speaker, and the forms Marg uses back (मेरो, तेरो, वाको; गयो, आयो;
  जायगो; नाय; हतो; छोरा, छोरी, लाला, लली). Drop anything stiff or wrong, add everyday words.
- [ ] **Phone test:** write "Mero lala din bhar mobile dekhto hai, vaako ka karun?" and listen
  to the voice reply: light Braj, short sentences, a village example. Then **say** it as a voice
  note: tested only with our own synthetic voice so far (3/3 detected); real Braj voices from the
  village are the real test, and if speech-to-text mangles them, the next step is giving it
  Braj words as hints, or remembering a Braj speaker once detected.
- [ ] Is the Braj district list right (Mathura, Agra, Bharatpur, Dholpur, Karauli, Aligarh,
  Hathras, Firozabad, Etah, Kasganj, Mainpuri, Deeg, Palwal)?

## 2v. Eval rounds (from 2026-10-28)

- [ ] **Refusal copy changed** (`app/constants/fixed_replies.py`, REFUSE/HARMFUL): it said "bachche
  ki padhai…" to students too; now "Padhai, khel, career ya bachchon ki seekh ke baare mein
  poochhiye" (and Hindi, English).
- [x] **Decided:** student mentor and roadmap replies get 18 s too (`TIMEOUT_MENTOR_S`); two
  had timed out at 12 s.

## 3. Decisions log entries marked "pending owner review"

- [ ] `docs/design/s05-llm-orchestrator.md`, 2026-10-27 (S5 build choices).
- [ ] `docs/design/s06-voice.md`, `s07-safety.md`, `contracts.md`, 2026-10-27 (S6 build, spoken text checked).
- [ ] `docs/design/s10b-parent-journey.md`, 2026-10-27 (curiosity moment, child talk, nudges); `s13-telemetry.md` (signals); `contracts.md` and `data-model.md` (child talk, nudges, signals).
- [ ] `docs/design/s07-safety.md`, 2026-10-27 (crisis copy pulled forward; safety host).
- [ ] `docs/design/contracts.md`, 2026-10-27 (S5 ports, `SaveResult`, `MODEL_REASONING_EFFORT`).
- [ ] `docs/design/s04-queue-worker.md` and `mvp-scope.md`, 2026-10-28 (E1 upgrade: leases, loops, listener).
- [ ] `docs/design/s14-web-channel.md` and `mvp-scope.md`, 2026-10-28 (E2 upgrade: the live trace).
- [ ] `docs/design/s10b-parent-journey.md`, 2026-10-28 (summary for a session the child left).
- [ ] `docs/design/s08-onboarding.md`, 2026-10-28 (web consent wording).
- [ ] `docs/design/s15-evals.md`, 2026-10-28 (the eval harness and its choices).
- [ ] `docs/design/s16-hardening.md`, 2026-10-28 (hardening choices).
- [ ] `docs/design/contracts.md`, 2026-10-25 (`TurnObserver.on_step` result, `GoldenLearner`,
  `SignedTokenCodec`, the `ExtractSignals`/`UpdateMemory` fields).

## 4. Spike decisions still open

- [ ] Spike F images: GO at `low` effort (0.2 s over the latency bar). Recommended GO.
- [ ] Khoj cards: GO (`KHOJ_CARD_ENABLED=true`).
- [ ] Muse Spark Open: a cap of about 7 s per attempt.
- [x] Spike F SAM 3.1: call format verified and a first reading on 15 synthetic photos (6/6
  people caught, 0 false alarms, 4/4 counts exact; `docs/spikes/images.md`). Real photos still
  to come (`samples.md` set B).
- [ ] Spikes A (speech-to-text) and C (text-to-speech): waiting for voice samples.
- [ ] **Voice sample spec:** `docs/spikes/samples.md` was written for students and teachers
  (grades 6–12), before the MVP became the parent journey (children 3–8). Should some of the
  10 samples be parents asking about young children instead?

## 5. Housekeeping

- [x] Pushed `main` on 2026-10-27 (S5, S8, the safety backup, Muse's spike E/F); CI green.
- [x] Muse committed its spike E/F files (`5ec4490`).
- [ ] If hackathon time allows: the Aspirational engine slice (s11/s12).

## d7 hazards in examples (2026-10-28)

- [ ] The khoj offer, the reflection and parent answers keep the strict d7 word rule (an
  invitation there can't be checked apart from the rest of the text). Say if you want examples
  allowed there too; it would need the reflection's question and tip checked by a model instead.
- [ ] The prompt lines on hazards as examples (child_talk 1.0.3, curiosity_moment 1.0.3,
  mentor 1.1.3) and the round-tip scissors phrases in `app/constants/child_hazards.py`.
- [ ] The weapons and explosives redirect copy (`REFUSE`/`DANGEROUS_MAKING` in
  `app/constants/fixed_replies.py`), in Hinglish, Hindi and English.

## Child talk redirects (2026-10-28)

- [ ] Which blocks get a model-written redirect: S1 (violence), S9 (weapons), S2 (crime) only;
  sexual content, hate, privacy and medical keep fixed text. Say if hate should be redirected
  too ("everyone deserves respect").
- [ ] The redirect prompt `app/prompts/child_redirect.md.j2`, and the fixed child refusals
  `CHILD_REFUSE_DANGER`, `CHILD_REFUSE_HURTING`, `CHILD_REFUSE_OTHER` in
  `app/constants/child_talk_copy.py` (ideally with a teacher or counsellor from the village).

