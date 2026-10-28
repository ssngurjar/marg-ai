# Marg.ai

**A voice-first WhatsApp guide that closes the exposure gap for rural Indian children, by
coaching the people already around them.** Parents of 3–8-year-olds get a two-minute discovery to
do offline with things at home; teachers get today's chapter connected to real work; students get
a mentor that states facts only from official sources. It isn't a tutor, and it isn't screen time
for children: the world is the curriculum, the phone is the coach.

Built for the Meta Global AI Developer Hackathon (Indie track, **Build for Your World**),
Oct 26 – Nov 4, 2026, by Santram Gurjar.

| | |
|---|---|
| Demo video | *(link added at submission)* |
| What each feature does, step by step | [docs/submission/features.md](docs/submission/features.md) |
| How the system works, and how to debug it | [docs/guides/debugging-and-architecture.md](docs/guides/debugging-and-architecture.md) |
| The design, step by step | [docs/design/](docs/design/README.md) |

---

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
Marg needs no app and no reading, only WhatsApp and a voice note.

- **It multiplies.** One coached parent reaches a child every day; one teacher reaches a whole
  class; one record carries a child from their first *why* to their first career decision.
- **It travels.** A new language or dialect is word lists and prompt work, not a rebuild: Braj
  was added in a day.
- **It's cheap to run.** Under one US cent per reply in model calls, measured in our eval runs
  ($0.44 for 73 cases), not counting WhatsApp fees and hosting.
- **The need is large.** An estimated 250 million children under five in low- and middle-income
  countries are at risk of not reaching their developmental potential
  ([Lancet series, 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC5884058); 2010 data).

What Marg has **not** shown yet is that it changes outcomes: that needs families using it for
months. The first field test is in my own village.

## What it does

Everyone talks to Marg on WhatsApp, by voice or text, in Hindi, Hinglish, English or Braj.
Consent comes first, and a user's data is deleted with one message ("mera data hatao").

- **Parents of children aged 3–8: *Aaj ki Khoj* (today's discovery).** Marg picks one of 10
  reviewed activities that fits the child's age and season (shadow time, leaf families, sink or
  float…) and rewords it for this family, with open questions to ask and what to listen for. The
  child does it offline, in the courtyard. The parent reports what the child said, by voice, and
  Marg praises what the child noticed, asks one question that extends their idea, and gives the
  parent one tip about how children learn. A photo of what the child collected is checked for
  people, then counted. Good discoveries become a shareable card.
- **The child's own questions.** A parent can pass on a question ("chaand roz shape kyun badalta
  hai?"), or, with one-time consent, the child talks to Marg directly in short, voice-only sessions
  with strict child-safety rules. When Marg won't answer something directly (how a gun works),
  it says why, kindly, and turns the curiosity to something safe.
- **Teachers.** "Kal class 8 mein Force and Pressure padhana hai" → three real fields the chapter
  leads to (at least one outside science, one reachable without a degree), each with a
  five-minute activity for 40 students and nothing to buy.
- **Students, classes 6–12.** A mentor that answers only from **50 official documents**
  (scholarships, sports trials, exams, public service, skilling) and cites them, says honestly
  when it doesn't know, and builds a step-by-step plan.
- **One record that grows with the child.** Curiosity signals from age 3, aims and constraints
  later, so the mentor at 16 can build on what the child noticed and loved at 4.

Full walkthrough: [docs/submission/features.md](docs/submission/features.md).

**What Marg is not.** Not an "AI for education" chatbot: it coaches adults, and a young child's
learning happens offline with their hands. Not a basic RAG app: retrieval serves one part of the
system, with structured claims, citations and an honest "I don't know", inside a pipeline with
safety on both sides. Not medical advice: health and medicine questions are referred to the
anganwadi worker, the ASHA didi or a doctor, never answered.

---

## Built during the hackathon

Everything that runs was built between **Oct 26 and Nov 4, 2026**. The git tag
[`pre-kickoff`](../../tree/pre-kickoff) marks the line: before it, the repository held only
**planning and design documents, the golden evaluation cases (test data) and a list of corpus
sources**. All code, prompts, the activity catalogue, the corpus files, the web demo, the eval
harness and the ML sidecar came after it; `git log pre-kickoff..main` shows each step.

**Everything Marg runs is in this repository.** The ML sidecar
([`services/ml_sidecar/`](services/ml_sidecar/)) speaks the replies with Kokoro-82M and turns
text into vectors for the source search. It began on Oct 27 as a separate project and moved in
here on Oct 29, so the whole system can be read, checked and run from one place. It keeps its
own Python environment because the voice model needs Python 3.12 and PyTorch, which the main
service doesn't carry.

---

## The models: eight, each with one job (six from Meta)

Marg is a **compound AI system**: several models and components working together behind a
deterministic router, rather than one chatbot.

| Model | Where it runs | What it does in Marg |
|---|---|---|
| **Muse Spark 1.3** | Meta Model API | Plans and personalises each discovery; answers parents; writes teachers' chapter bridges, the student mentor's answers and plans; talks with children and writes their redirects; the second safety check; the eval judge |
| **Muse Spark Open** (open weights) | Baseten | Reflects on what the child said; extracts curiosity and aspiration signals and the student's memory. Spark 1.3 takes over if it's slow |
| **Muse Voice Transcribe** | Meta Model API | Every voice note. Script slips (Hindi returned in Gujarati or Gurmukhi letters) are converted back to Devanagari |
| **Muse Image** | Meta Model API | The khoj card. No child and no name ever go into the image prompt |
| **SAM 3.1** | Meta Model API | First proves no person is in a child's photo (otherwise it's dropped unseen), then counts the leaves or stones the child collected. Photos are never stored |
| **Llama Guard 4** | DeepInfra | Every message and every reply, written and spoken, with Muse Spark as the second opinion and the backup |
| Kokoro-82M (open weights) | the ML sidecar, self-hosted | Spoken replies in Hindi and English (not a Meta model; chosen by ear and by a transcription check against MMS-TTS) |
| multilingual-e5-small | the ML sidecar, self-hosted | Embeddings for the official-source search (not a Meta model) |

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
   pipeline/ fetch media → transcribe → route (rules, no model) → safety in ‖ generate
             → safety out → speak → send; every step recorded with its time and cost
   layers/   journey · curiosity · child talk · teacher bridges · mentor · plans · memory
   safety/   crisis phrases → Llama Guard 4 ‖ Muse Spark policy → child rules (d1, d7, d8)
   store/    Postgres: inbox, turns, steps, outbox (sent once per part), learners, signals
```

- **Ports and adapters.** Domain rules are pure and have no I/O; every SDK sits behind a protocol in
  [`app/providers/ports.py`](app/providers/ports.py); only `channels/` knows a WhatsApp payload.
  An import-graph test enforces the direction.
- **Reliable by construction.** The webhook only stores and acknowledges; turns run in the worker.
  A redelivered webhook or a retried worker never produces a second reply. A worker that dies
  mid-turn loses its lease and another takes over. Every external call has a timeout, bounded
  retries with backoff and `Retry-After`, and a documented fallback.
- **The web demo** runs the same pipeline and shows a live trace of every step (safety, routing,
  which model, voice) as it happens.

More: [docs/guides/debugging-and-architecture.md](docs/guides/debugging-and-architecture.md),
and every module and class in [docs/code-map.md](docs/code-map.md).

## Safety and children's privacy

- **Nothing unchecked reaches a user.** Every reply needs a passing output check before the
  outbox accepts it; the types make any other path impossible. If the checks can't run, the user
  gets a fixed holding reply.
- **Crisis replies are fixed text** with official helplines (Tele-MANAS 14416, Childline 1098),
  sent even when every provider is down, and a child gets child-worded versions.
- **Two checks, not one.** Llama Guard 4 and a Muse Spark policy check run in parallel; Llama
  Guard's self-harm flag counts only when Muse Spark agrees (it flagged "doctor banna hai, plan
  bana do"), and Muse Spark catches what Llama Guard misses.
- **Child rules in code:** no personal questions to a child, no secrecy or "best friend"
  language to a student or child, no hazard in a child's activity (a danger may be explained,
  never suggested), a supervision line on every activity, session limits for child talk, and the
  parent's summary names topics, never the child's words.
- **Data minimisation (DPDP Act 2023):** role, class, district, language; for a child only a
  nickname and a birth year. Phone numbers are salted hashes; raw audio is deleted after
  transcription; photos are never stored; logs hold only ids and hashes.

## Quality

| | |
|---|---|
| Tests | **2,282** unit and contract tests, plus integration tests on Postgres; property-based tests (Hypothesis) for the state machine, message splitting, spoken-text rules, the chunker, signatures, payload parsing and the hazard matcher |
| Checks | `ruff format`, `ruff check`, `mypy --strict` (no `Any`), `pytest`: all must pass before every commit |
| Evals | `marg eval` plays **78** hand-written cases through the real pipeline and real models; code checks plus a judge model. Crisis and adversarial cases are hard gates |
| Latest full scorecard | **57%** of cases pass; both hard gates pass; safety 5.00/5, reading level 4.80/5, cultural resonance 4.65/5 ([evals/results/](evals/results/)) |
| Latency | p50 5.3 s, p95 13.4 s per reply (eval run); a 10-person smoke test lost, doubled or silenced nothing ([docs/load/](docs/load/2026-10-28-smoke-test.md)) |

57% is honest, not good: the judge is strict, and single runs move by several points. The
failing cases are listed in each scorecard.

## Try it

- **Watch:** the demo video *(link added at submission)*.
- **Run it locally:** see below; the web demo at `/demo` needs no WhatsApp account.

### Run it locally

Needs Python 3.13, [uv](https://docs.astral.sh/uv/), Docker and ffmpeg, plus keys for the Meta
Model API, Baseten and DeepInfra (every setting is listed, without values, in
[`.env.example`](.env.example)).

```sh
make setup                               # both environments from their lockfiles
cp .env.example .env                     # then fill in the keys
docker compose up -d postgres            # the database
make migrate                             # the schema
make sidecar                             # in a second terminal: the voice and the search vectors
.venv/bin/python -m app.cli ingest-corpus   # the official sources, for the mentor
.venv/bin/uvicorn app.main:create_app --factory --port 8000
open http://127.0.0.1:8000/demo
```

Without the sidecar, replies are text only and the mentor can't search its sources
([guide, §2.1](docs/guides/debugging-and-architecture.md)). The checks: `make check` (format,
lint, types and unit tests, the sidecar's included) and `make test-int` (Postgres).

## Repository map

| Path | What's there |
|---|---|
| [`app/`](app/) | The service: `api`, `channels`, `pipeline`, `layers`, `safety`, `domain`, `providers`, `store`, `worker`, `rag`, `evals`, `prompts`, `constants` |
| [`services/ml_sidecar/`](services/ml_sidecar/) | The ML sidecar: Kokoro-82M speech (`/tts`) and multilingual-e5-small vectors (`/embed`), in its own Python 3.12 environment |
| [`content/activities/`](content/activities/) | The 10 reviewed discovery activities, their hazards and materials |
| [`corpus/`](corpus/) | The official sources for the mentor, each with `source_url` and `retrieved_on` |
| [`evals/`](evals/) | Golden cases and scorecards |
| [`docs/design/`](docs/design/README.md) | The design, one document per build step, each with its decisions log |
| [`tests/`](tests/) | Unit, contract, property and integration tests |

## Licences

| Component | Licence |
|---|---|
| Muse Spark, Muse Voice Transcribe, Muse Image, SAM 3.1 (Meta Model API) | Meta Model API terms |
| Muse Spark Open, Llama Guard 4 | Meta's open-weights licences |
| Kokoro-82M, kokoro, misaki, transformers | Apache-2.0 |
| PyTorch | BSD-3-Clause |
| spaCy, en_core_web_sm | MIT |
| phonemizer-fork, espeak-ng (bundled by espeakng-loader) | GPL-3.0: Kokoro's Hindi phonemiser, installed as packages (not copied here) and run only inside the sidecar |
| multilingual-e5-small | MIT |
| FastAPI, Pydantic, SQLAlchemy, Alembic, PyYAML, structlog | MIT (structlog MIT or Apache-2.0) |
| asyncpg, openai, cryptography | Apache-2.0 (cryptography Apache-2.0 or BSD-3-Clause) |
| httpx, Jinja2, uvicorn | BSD-3-Clause |

Marg's own licence: *(to be chosen by the owner before the repository goes public)*.
