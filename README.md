# Marg.ai

**Talent is everywhere; exposure isn't. Marg brings children the exposure they're missing
through the people already around them: parents, teachers, and older children themselves.**

Today it serves rural India: on WhatsApp, in Hindi, Hinglish, English and Braj, for parents of
3–8-year-olds, teachers, and students.

Built for the Meta Global AI Developer Hackathon (Indie track, **Build for Your World**),
Oct 26 – Nov 4, 2026, by Santram Gurjar.

---

## Contents

| Section | In brief |
|---|---|
| [What Marg is](#what-marg-is) | A two-minute daily discovery for parents, chapters linked to real work for teachers, a sourced mentor for students |
| [At a glance](#at-a-glance) | The four judging criteria, with where to check each |
| [Why](#why) | A village in Rajasthan, and children who lack exposure, not talent |
| [Impact](#impact) | Reach through the phone already in the house, what it costs, and how it travels |
| [Run it locally](#run-it-locally) | Python, Docker and one Meta Model API key: the whole system on your machine, web demo included |
| [Field tests](#field-tests) | Eight real people, unscripted: 31 things broke, every one fixed the same day |
| [What it does](#what-it-does) | Parents, the child's own questions, teachers, students, one growing record |
| [Built during the hackathon](#built-during-the-hackathon) | Everything that runs was built Oct 26 – Nov 4, 2026; what existed before kickoff, and why replies are text |
| [The models](#the-models) | Six Meta models, each with one job, and where they run |
| [How it works](#how-it-works) | The pipeline, ports and adapters, and why no message is lost or doubled |
| [Safety and children's privacy](#safety-and-childrens-privacy) | Two checks on every message, fixed crisis replies, child rules, data minimisation |
| [What's next](#whats-next) | A daily limit for child talk, reading children's words, anganwadi workers, more sources |
| [Quality](#quality) | 3,352 tests, 101 eval cases, the latest scorecard, and what hands-on testing found |
| [Try it](#try-it) | The video, the web demo and WhatsApp |
| [Repository map](#repository-map) | Where everything lives |
| [Licences](#licences) | Every model and library, and the attributions they ask for |

More detail: what each feature does, step by step, in
[docs/submission/features.md](docs/submission/features.md); how the system works and how to debug
it in [docs/guides/debugging-and-architecture.md](docs/guides/debugging-and-architecture.md); the
design, one document per build step, in [docs/design/](docs/design/README.md).

---

## What Marg is

Marg closes the exposure gap for rural Indian children by equipping the people already around
them. Parents of 3–8-year-olds get a two-minute discovery to do offline with things at home;
teachers get today's chapter connected to real work; students get a mentor that states facts only
from official sources. It isn't a tutor, and it isn't screen time for children: the world is the
curriculum, the parent is the teacher, and Marg is the guide.

The way it teaches is the one India's national curriculum for ages 3–8 sets out: children
"learn best through play", and "most learning occurs through play, listening, and talking",
in the child's home language, with parents as "co-partners" in the child's learning
([NCF Foundational Stage 2022, NCERT, pp. 38, 76, 219](https://ncert.nic.in/pdf/NCF_for_Foundational_Stage_20_October_2022.pdf)).
Marg's replies follow *serve and return*: "responsive, back-and-forth exchanges between a young
child and a caring adult" that "play a key role in shaping brain architecture"
([Harvard Center on the Developing Child](https://developingchild.harvard.edu/science/key-concepts/serve-and-return/)).

Families talk to Marg the way they already talk on WhatsApp: by voice note or text.

## At a glance

| Criterion | The evidence, and where to check it |
|---|---|
| **Impact** | Fewer than one in four Class 3 children in rural government schools can read a Class 2 story (ASER 2024), and 250 million children under five are at risk of not reaching their potential (The Lancet, 2017). Marg reaches families through the phone they already have: no app, just a voice note, at under one US cent a reply in model calls. → [Impact](#impact) |
| **Meta AI tooling** | Six Meta models, each with one job: Muse Spark 1.3, Muse Spark Open (open weights), Muse Voice Transcribe, SAM 3.1, Muse Image and Llama Guard 4, plus measured feedback on where they fell short for Hindi and Braj. → [The models](#the-models) · [feedback](docs/submission/submission-form.md#provide-feedback-from-your-experience-using-meta-products) |
| **Technical depth** | Hexagonal (ports and adapters) architecture, enforced by an import-graph test; every message checked on the way in and out, failing closed, with Muse Spark backing up Llama Guard; 3,352 tests, including property-based ones; 101 eval cases through the real pipeline, with crisis and adversarial cases as hard gates (76% of the 82 scored pass on the latest full run); a design document and decisions log for every step. → [How it works](#how-it-works) · [Safety](#safety-and-childrens-privacy) · [Quality](#quality) |
| **Demo** | A live web demo that shows a trace of every step behind each reply, and the three-minute video (English subtitles uploaded, not auto-generated). → [Try it](#try-it) |

## Why

I grew up in a village in Rajasthan, where learning meant memorising books, and it took me thirty
years to learn to ask *why*. Parents there still say "padho, padho": read. Nobody shows them how
to make a child curious, and few children ever meet someone who has walked a path beyond the
village.

In rural India, fewer than one in four Class 3 children in government schools can read a Class 2
story: **23.4%** in 2024 ([ASER 2024, National findings, p. 47](https://asercentre.org/wp-content/uploads/2022/12/ASER-2024-National-findings.pdf)).
Children here don't lack talent. They lack **exposure**: someone to ask them *why*, and anyone to
show them what they could become. Marg closes that gap where the child already is, with the
people already around them.

## Impact

Marg's reach is the phone already in the house. In rural India, almost 90% of 14–16-year-olds
report having a smartphone at home ([ASER 2024, p. 48](https://asercentre.org/wp-content/uploads/2022/12/ASER-2024-National-findings.pdf)).
Marg needs no app, only WhatsApp, and anyone can ask by voice note.

- **It multiplies.** One equipped parent reaches a child every day; one teacher reaches a whole
  class; one learner record is built to carry a child from their first *why* toward their first
  career decision.
- **It travels.** A new language or dialect is word lists and prompt work, not a rebuild: Braj
  was added in a day. Nothing in the design is only for one village, and the need is global:
  "250 million children (43%) younger than 5 years in low-income and middle-income countries
  are at risk of not reaching their developmental potential" ([The Lancet, 2017](https://pubmed.ncbi.nlm.nih.gov/27717614/)).
  Marg fits anywhere families share one phone and speak a language at home that school doesn't.
  Per region, three things change, each reviewed locally: the language word lists, the official
  sources, and the crisis helplines. Channels and models sit behind ports, so the core stays the
  same.
- **Affordable at village scale.** About 0.6 US cents per reply in model calls, measured in a full
  eval run ($0.65 for 111 replies), so about 3 US cents a day for an active family (around five
  replies), not counting WhatsApp fees and hosting. The whole build, with every test and
  evaluation, used about $32 of Model API credits (Baseten and DeepInfra are billed separately).
- **The need is large.** An estimated 250 million children under five in low- and middle-income
  countries are at risk of not reaching their developmental potential
  ([Lancet series, 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC5884058); 2010 data).

What Marg has **not** shown yet is that it changes outcomes: that needs families using it for
months.

## Run it locally

Needs Python 3.13, [uv](https://docs.astral.sh/uv/), Docker and ffmpeg, and one account key:
the Meta Model API's. Llama Guard 4 (on DeepInfra) and Muse Spark Open (on Baseten) are optional.
Leave their keys empty and Muse Spark checks every message in and out and writes the
reflections, the same backups that take over when those hosts are down. The hosted demo runs
all of them. Every setting is listed in [`.env.example`](.env.example), with how to generate
the salt and signing keys; for the web demo alone, the WhatsApp ids can be any placeholder.

```sh
make setup                               # the environment from its lockfile
cp .env.example .env                     # then fill in the keys
docker compose up -d postgres            # the database
make migrate                             # the schema
.venv/bin/python -m app.cli ingest-corpus   # the official sources, for the mentor
.venv/bin/uvicorn app.main:create_app --factory --port 8000
open http://127.0.0.1:8000/demo
```

See the [guide, §2](docs/guides/debugging-and-architecture.md). The checks: `make check`
(format, lint, types and unit tests) and `make test-int` (Postgres).

## Field tests

**Unscripted field tests with 8 real people: a teacher, students and a mother.** 31 things broke,
and every one was fixed and tested the same day.

- **The first field test** (1 November, in my village, on WhatsApp, unscripted): one person, two
  sessions, 0 failed turns. It found eleven things no test had: a child's name given without the
  age, a graduate who couldn't get past "class 1 to 12", a question about Braj, frustration shown
  with an emoji after the same reply three times. All eleven were fixed and tested the same night
  ([report](docs/field-tests/2026-11-01-village-whatsapp.md)).
- **The second field test** (2 November, on the web demo and WhatsApp, unscripted): a
  government-school teacher speaking Hindi by voice, parents and students: seven people (ten
  accounts, since a browser reset starts a new one), 82 turns, 0 failed. It found twenty more: a
  class range in Hindi words, a mistaken Done on a khoj, a school topic refused as homework, a
  Hindi chapter answer that took 22 s, a student's "hi" that took 10 s. All twenty were fixed and
  tested the same day; one more (an exam Marg has no source for) waits for official sources
  ([report](docs/field-tests/2026-11-02-web-demo.md)).

## What it does

Everyone talks to Marg on WhatsApp, by voice or text, in Hindi, Hinglish, English or Braj.
Consent comes first, and a user's data is deleted with one message ("mera data hatao").

- **Parents of children aged 3–8: *Aaj ki Khoj* (today's discovery).** Marg picks one of 10
  reviewed activities that fits the child's age and season (shadow time, leaf families, sink or
  float…) and rewords it for this family, with open questions to ask and what to listen for. The
  child does it offline, in the courtyard. The parent reports what the child said, by voice, and
  Marg praises what the child noticed, asks one question that extends their idea, and gives the
  parent one tip about how children learn. A photo of what the child collected is checked for
  faces, then counted. Good discoveries become a shareable card.
- **The child's own questions.** A parent can pass on a question ("chaand roz shape kyun badalta
  hai?"), or, with one-time consent, the child asks Marg directly by voice note, in short
  sessions with strict child-safety rules (the parent reads the reply aloud). When Marg won't
  answer something directly (how a gun works), it says why, kindly, and turns the curiosity to
  something safe.
- **Teachers.** "Kal class 8 mein Force and Pressure padhana hai" → three real fields the chapter
  leads to (at least one outside science, one reachable without a degree), each with a
  five-minute activity for 40 students and nothing to buy.
- **Students, classes 6–12.** A mentor that answers only from **53 official documents**
  (scholarships, sports trials, exams, public service, skilling) and cites them, says honestly
  when it doesn't know, and builds a step-by-step plan.
- **One record that grows with the child.** Curiosity signals from age 3, aims and constraints
  later, on one learner record. Letting the mentor at 16 build on what the child noticed at 4
  is the next step: the record keeps both today, and the mentor doesn't read the early part yet.

Full walkthrough: [docs/submission/features.md](docs/submission/features.md).

**What Marg is not.** Not an "AI for education" chatbot: it equips adults, and a young child's
learning happens offline with their hands. Not a basic RAG app: retrieval serves one part of the
system, with structured claims, citations and an honest "I don't know", inside a pipeline with
safety on both sides. Not medical advice: health and medicine questions are referred to the
anganwadi worker, the ASHA didi or a doctor, never answered.

## Built during the hackathon

Everything that runs was built between **Oct 26 and Nov 4, 2026**. The git tag
[`pre-kickoff`](../../tree/pre-kickoff) marks the line: before it, the repository held only
**planning and design documents, the golden evaluation cases (test data) and a list of corpus
sources**. All code, prompts, the activity catalogue, the corpus files, the web demo, the eval
harness (and a voice sidecar, since removed) came after it; `git log pre-kickoff..main` shows each
step.

**Every model Marg calls is a Meta model**, as the organisers require, and everything Marg runs
is in this repository. Two consequences:

- **Replies are text.** Meta's MMS-TTS is the only Meta speech-output model, and its licence is
  CC-BY-NC 4.0 (non-commercial). The organisers leave each licence to the entrant, and a prize
  submission is hard to square with "non-commercial", so it isn't used. Voice notes *in* still
  work (Muse Voice Transcribe), and the web demo reads replies aloud with the browser's own voice,
  which isn't a model call. An MMS voice was built during the hackathon and then removed from
  this build (git tag `voice-sidecar-2026-11-02`); the reply path still speaks through a port,
  ready for a Meta speech model whose licence allows it.
- **The source search is keyword search in Postgres**, with Muse Spark turning a Hindi or
  Hinglish question into English search terms first. An earlier version also used a non-Meta
  embedding model; it was removed.

## The models

Marg is a **compound AI system**: six Meta models and plain code working together behind a
deterministic router, rather than one chatbot, each model with one job.

**Open Meta models, and where they run:** Muse Spark Open on Baseten and Llama Guard 4 on
DeepInfra, both called at runtime. The rest run on the Meta Model API.

| Model | Where it runs | What it does in Marg |
|---|---|---|
| **Muse Spark 1.3** | Meta Model API | Reads what a parent's own words mean (a report, a question, the child's question, "send that khoj again", another child) and the language and dialect they're in (Hinglish without the usual marker words, Braj); plans and personalises each discovery; answers parents; writes teachers' chapter bridges, the student mentor's answers and plans; talks with children and writes their redirects; the second safety check; the eval judge |
| **Muse Spark Open** (open weights) | Baseten | Reflects on what the child said; extracts curiosity and aspiration signals. Spark 1.3 takes over if it's slow. In a full 86-case eval run it did 16 of the 126 generation steps (13%): 3 parent reflections, and 13 of 15 signal extractions |
| **Muse Voice Transcribe** | Meta Model API | Every voice note. Script slips (Hindi returned in Gujarati or Gurmukhi letters) are converted back to Devanagari |
| **Muse Image** | Meta Model API | The khoj card. No child and no name ever go into the image prompt |
| **SAM 3.1** | Meta Model API | First checks there's no face in a child's photo (otherwise it's dropped unseen), then counts the leaves or stones the child collected. Photos are never stored |
| **Llama Guard 4** | DeepInfra | Every message and every reply, written and spoken, with Muse Spark as the second opinion and the backup |

Every generative call returns **structured output** validated into a typed model, with one
repair retry carrying the validation error; model ids, timeouts and cost caps live in
[`app/core/config.py`](app/core/config.py), and every prompt is a versioned file in
[`app/prompts/`](app/prompts/).

## How it works

```
 WhatsApp (Meta Cloud API) ─webhook─┐     ┌─ Browser (/demo, cookie session)
                                    ▼     ▼
   api/      verify the signature, parse, store in the inbox (once per message id), < 1 s
   worker/   claim the user under a lease → one turn at a time per person, any number of workers
   pipeline/ fetch media → transcribe → route (rules: buttons, safety, consent; Muse Spark reads a student's plan request)
             → safety in ‖ generate (a parent's free text: Muse Spark reads its intent first)
             → safety out → send; every step recorded with its time and cost
   layers/   journey · curiosity · child talk · teacher bridges · mentor · plans · memory
   safety/   crisis phrases → Llama Guard 4 ‖ Muse Spark policy → child rules (d1, d7, d8)
   store/    Postgres: inbox, turns, steps, outbox (sent once per part), learners, signals
```

- **Ports and adapters.** Domain rules are pure and have no I/O; every SDK sits behind a protocol
  in [`app/providers/ports.py`](app/providers/ports.py); only `channels/` knows a WhatsApp payload.
  An import-graph test enforces the direction.
- **Reliable by construction.** The webhook only stores and acknowledges; turns run in the worker.
  A redelivered webhook or a retried worker never produces a second reply. A worker that dies
  mid-turn loses its lease and another takes over. Every external call has a timeout, bounded
  retries with backoff and `Retry-After`, and a documented fallback.
- **The web demo** runs the same pipeline and shows a live trace of every step (safety, routing,
  which model) as it happens.

More: [docs/guides/debugging-and-architecture.md](docs/guides/debugging-and-architecture.md),
and every module and class in [docs/code-map.md](docs/code-map.md).

## Safety and children's privacy

- **Nothing unchecked reaches a user.** Every reply needs a passing output check before the
  outbox accepts it; the types make any other path impossible. If the checks can't run, the user
  gets a fixed holding reply.
- **Crisis replies are fixed text** with official helplines (Tele-MANAS 14416, Childline 1098),
  sent even when every provider is down, and a child gets child-worded versions.
- **Two checks, not one.** Llama Guard 4 and a Muse Spark policy check run in parallel. On a
  user's message, Llama Guard's self-harm, violence, crime, child-exploitation and hate flags
  count only when Muse Spark agrees (it flagged "doctor banna hai, plan bana do" as self-harm
  and a parent's "Munni ko yaad nahi" as hate), and Muse Spark catches what Llama Guard misses.
- **Child rules in code:** no personal questions to a child, no secrecy or "best friend"
  language to a student or child, no hazard in a child's activity (a danger may be explained,
  never suggested), a supervision line on every activity, session limits for child talk, and the
  parent's summary names topics, never the child's words.
- **One family, one phone.** Most families can't give each child a phone, so children use the
  parent's. A child talks to Marg only after saying who they are ("Main Munni hoon", or their
  button) and only if the parent switched child talk on for them. When the words sound like
  someone other than the parent ("I'm in class 10…"), Marg asks who is writing and answers no
  one the parent hasn't added. Honestly: this reads who *seems* to be writing; it can't verify
  a person, so every reply still passes every check.
- **Data minimisation (DPDP Act 2023):** role, class, district, language; for a child only a
  nickname and a birth year. Phone numbers are salted hashes; raw audio is deleted after
  transcription; photos are never stored; logs hold only ids and hashes.

## What's next

- **A daily limit on a child's time with Marg.** Today a child session ends after 6 questions or
  10 minutes, and the next can start 30 minutes later, so nothing caps a child's total for the
  day. Planned: a daily cap the parent can set, with the time shown in the parent's summary, so
  Marg stays a short daily spark, not screen time.
- **Reading what a child means, too.** Muse Spark reads what a parent's words mean (a report, a
  question, someone else writing). A child's messages in child talk still go through fixed rules
  for things like "Hindi" or "bye", which miss some ways children write. Planned: the same reading
  for children, once its extra second per reply is worth it.
- **Anganwadi and ASHA workers.** They already see the families Marg serves, and a role for them
  (a few families' khojs and questions, with each family's consent) would carry Marg to parents
  without a phone of their own. Not built for the hackathon.
- **A wider library of sources.** The mentor answers only from 53 official documents (exams,
  scholarships, sports, skilling, public service, health courses), so a goal they don't cover,
  such as sports selection trials or a state's police recruitment, gets an honest "I don't have
  verified details" instead of a guess. Covering every exam, scheme and state rule takes an
  extensive search of official sources and their ingestion, each fact copied with its link and
  date; that is planned after the hackathon.

## Quality

| | |
|---|---|
| Tests | **3,352**: 3,139 unit and contract tests, plus 213 integration tests on Postgres; property-based tests (Hypothesis) for the state machine, message splitting, spoken-text rules, the chunker, signatures, payload parsing and the hazard matcher |
| Checks | `ruff format`, `ruff check`, `mypy --strict` (no `Any`), `pytest`: all must pass before every commit |
| Evals | `marg eval` plays **101** hand-written cases through the real pipeline and real models; code checks plus a judge model. Crisis and adversarial cases are hard gates |
| Latest full scorecard | **76%** of the 82 scored cases pass (62); both hard gates pass; safety 5.00/5, reading level 4.73/5, cultural resonance 4.84/5 ([evals/results/](evals/results/)) |
| Latency | p50 6.1 s, p95 11.1 s per reply (eval run); a 10-person smoke test lost, doubled or silenced nothing ([docs/load/](docs/load/2026-10-28-smoke-test.md)) |

76% is honest, not perfect: the judge is strict, and single runs move by several points (two
full runs on the same day gave 73% and 76%). The failing cases are listed in each scorecard;
about a quarter of them lack an official source (no sports-selection or state police source yet),
where Marg says it doesn't know rather than guess.

**Found by using it.** Rough, hands-on tests on the live demo found what the test suite missed.
Each one is fixed and kept as a regression test.

| What happened | Why it mattered | Now |
|---|---|---|
| "Hindi pleasee" got an English reply | People stretch words when they text | Stretched words are read in their normal form |
| A class-10 student on a parent's phone was answered as the parent | Families share one phone | Marg asks "Who's writing?" and answers no one the parent hasn't added |
| The child tapped her name and her question was dropped | She had already asked it | Her message is answered after she taps |
| A child got English replies on an English account | Children write the way they speak | Replies follow the child's own language |
| A child's "Hindi" got "Mummy and Papa will do that" | Asking for a language isn't an account change | It switches only her session |
| A refresh showed an empty chat | It looked as if everything was lost | The conversation reloads, a page at a time |

## Try it

- **Watch:** the demo video *(link added at submission)*.
- **Try it on the web:** <https://marg-ai.fly.dev/demo>, in English by default; write in
  Hindi or Hinglish and Marg answers in that.
- **Try it on WhatsApp:** this link opens a chat with "Hi Marg, English please" ready to send,
  so Marg answers in English: `https://wa.me/<number>?text=Hi%20Marg%2C%20English%20please`
  *(number added at submission)*. Families in the village write in Hindi or Hinglish and get
  that.
- **Run it locally:** see [Run it locally](#run-it-locally); the web demo at `/demo` needs no WhatsApp account.

## Repository map

| Path | What's there |
|---|---|
| [`app/`](app/) | The service: `api`, `channels`, `pipeline`, `layers`, `safety`, `domain`, `providers`, `store`, `worker`, `rag`, `evals`, `prompts`, `constants` |
| [`content/activities/`](content/activities/) | The 10 reviewed discovery activities, their hazards and materials |
| [`corpus/`](corpus/) | The official sources for the mentor, each with `source_url` and `retrieved_on` |
| [`evals/`](evals/) | Golden cases and scorecards |
| [`docs/design/`](docs/design/README.md) | The design, one document per build step, each with its decisions log |
| [`docs/field-tests/`](docs/field-tests/) | The two field-test reports |
| [`tests/`](tests/) | Unit, contract, property and integration tests |

## Licences

| Component | Licence |
|---|---|
| Muse Spark, Muse Voice Transcribe, Muse Image, SAM 3.1 (Meta Model API) | Meta Model API terms |
| Muse Spark Open | Muse Model License (Meta) |
| Llama Guard 4 | Llama 4 Community License (Meta) |
| FastAPI, Pydantic, pydantic-settings, SQLAlchemy, Alembic, PyYAML, structlog | MIT (structlog MIT or Apache-2.0) |
| asyncpg, openai, cryptography | Apache-2.0 (cryptography Apache-2.0 or BSD-3-Clause) |
| httpx, Jinja2, uvicorn | BSD-3-Clause |

**Built with Muse Spark Open. Built with Llama.** (The attributions the Muse Model License and
the Llama 4 Community License ask for.)

Marg's own code: **all rights reserved** ([LICENSE](LICENSE)). You may view it and run it to
evaluate this hackathon entry; any other use needs the author's written permission.
