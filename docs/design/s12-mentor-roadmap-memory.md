# S12 — Mentor, Roadmap and profile memory

> **Hackathon build level: Phase 2, except `LayerResult`, which every layer uses.** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

## 1. Purpose

This is the student side of Marg.ai, the "Aspirational Layer":

- **Mentor:** answers a student's question using only retrieved corpus facts, cites every
  factual claim, and says honestly when it doesn't know.
- **Roadmap:** turns an ambition into 3–6 concrete, sourced steps, and stores them. (Progress
  tracking and check-ins are deferred, §4.9.)
- **Memory:** keeps a short rolling profile of the user (ambitions, constraints), so later
  sessions start from who they are without replaying the whole history.

S12 also owns the short **off-topic redirect**, and the **`LayerResult`** type every generate
handler returns.

## 2. Read first

- [contracts.md](contracts.md): §2.2 `TurnContext` (`memory`, `active_roadmap`, `recent_exchanges`,
  `is_session_start`), `ProfileMemory`, `Exchange`; §2.3 `TurnOutcome.writes` / `post_turn`;
  §2.4 `TurnWrite` (`SaveRoadmap`), `PostTurnTask` (`UpdateMemory`); §2.6 `CanonicalReply`,
  `Citation`; §2.7 layer output names; §3 `LanguageModel`, `GenerationRequest.semantic_check`;
  §1 `Route`, `RoadmapStatus`, `RoadmapStepStatus`, `StepName.UPDATE_MEMORY`
- [data-model.md](data-model.md): `roadmaps`, `roadmap_steps`, `profile_memory`, `turns`
- [s11-rag.md](s11-rag.md): `QueryRewriter`, `Retriever`, `RetrievalResult.nothing_relevant`
- [s05-llm-orchestrator.md](s05-llm-orchestrator.md): prompt registry, structured-output retry, the generate step dispatch
- [s09-translation.md](s09-translation.md): what happens to `CanonicalReply` next
- [plan.md](../../plan.md) §4.5; [CLAUDE.md](../../CLAUDE.md) §1, §10 (grounding), §11

## 3. Scope

**In:**
- Generate-step handlers for `Route.MENTOR`, `Route.ROADMAP` and `Route.OFF_TOPIC`.
- `LayerResult` (`app/layers/results.py`), the shared result of every generate handler (s08, s10, s10b, s12).
- Citation validation and repair.
- The don't-know path.
- Roadmap drafting and persistence (through a `SaveRoadmap` write); showing the active roadmap.
- The `UpdateMemory` post-turn task.
- Context assembly within a token budget.
- Prompts `mentor`, `roadmap`, `memory`, `off_topic`.

**Out:**
- Retrieval itself: S11.
- Deciding the route: S5 router, which needs to know whether a roadmap is active (§4.6).
- Translating into the user's register: S9 (canonical replies are English, B11).
- Safety checks: S7. Crisis or refuse never reach S12.
- Aspiration signals: S13.
- Search grounding: off for the MVP (B8).
- **Deferred (B9):** roadmap progress updates, session check-ins and the `rm:done` button (§4.9).

## 4. Design

### 4.1 Where S12 code runs

`layers/` is pure (it may import only `domain`, `providers.ports`, `prompts` and `rag`), so the
layers **return** results and the pipeline **persists** them. A roadmap is not written during
`generate`. It's returned as a `SaveRoadmap` write and applied by s04 **in the finalize
transaction, with the outbox rows** (contracts §2.4). That way a reply blocked by `safety_out`, or
a turn that loses its lease, never leaves a roadmap the student didn't see.

```
pipeline generate step ── dispatch on RouteDecision.route
   MENTOR    → MentorLayer.answer(ctx)            → LayerResult(reply)
   ROADMAP   → RoadmapLayer.handle(ctx)           → LayerResult(reply, writes=[SaveRoadmap] | [])
   OFF_TOPIC → OffTopicLayer.redirect(ctx)        → LayerResult(reply)
TurnOutcome.writes ── s04 finalize: outbox rows + SaveRoadmap, one transaction
TurnOutcome.post_turn ── [UpdateMemory] for eligible turns (§4.7), run by s04 after finalize
```

### 4.2 Context assembly — `app/layers/context.py`

Every S12 prompt gets the same context block, assembled to fit `CONTEXT_BUDGET_TOKENS = 6000`
(module constant), counted with `approx_tokens` from s11.

| Order | Section | Rule |
|---|---|---|
| 1 | Profile | role, grade, district, language. Always included. No hash, no number |
| 2 | Memory | `ProfileMemory.summary`, ambitions, constraints. Always included if present (≤ 600 chars) |
| 3 | Active roadmap | goal + steps as `position. action`. Always included if present |
| 4 | Retrieved chunks | as `[C1] title — heading\ntext`. Up to 5. Never trimmed: if over budget, drop the lowest-ranked chunk |
| 5 | Recent exchanges | oldest dropped first until it fits. At least the most recent one is kept |
| 6 | User message | the combined `user_text`, always last, as a registry-wrapped user slot |

Memory, roadmap step text and recent exchanges come from user text, so they're passed as
`user_vars` (registry-wrapped), never as `system_vars` (s05 §4.3). Chunks are curated and may go in
`system_vars`, still wrapped in `<sources>` tags.

Chunks are labelled `C1…Cn` in the prompt. The model cites labels, and code maps labels back to
`chunk_id`s. Models handle short labels far more reliably than UUIDs, and a label can't
accidentally name a chunk that wasn't retrieved.

```python
@dataclass(frozen=True)
class PromptContext:
    profile_block: str
    memory_block: str | None
    roadmap_block: str | None
    chunk_blocks: list[LabelledChunk]      # label "C1".. → RetrievedChunk
    exchange_blocks: list[str]
    user_text: str

def build_prompt_context(ctx: TurnContext, retrieval: RetrievalResult | None) -> PromptContext: ...
```

### 4.3 Mentor — `app/layers/mentor.py`

**Flow:**
1. Retrieve (S11). The query is rewritten first **only when `QUERY_REWRITE_ENABLED`** is true (B9);
   otherwise retrieval uses the raw `user_text`.
2. If `retrieval.nothing_relevant`, call the mentor prompt in **don't-know mode**: no chunks are
   passed, and the validator forces `knows=False` and `claims=[]`.
3. Otherwise call the mentor prompt in grounded mode.
4. Validate citations (below), then assemble the body in code.

**Output schema (`MentorAnswer`)** — strict schema rules (s05 §4.1): no field defaults; optional
fields are `T | None` and still required.

```python
class MentorClaim(BaseModel):
    text: str = Field(max_length=300)                        # one factual sentence
    sources: list[str] = Field(min_length=1, max_length=3)   # chunk labels, e.g. ["C2"]

class MentorAnswer(BaseModel):
    knows: bool
    opening: str = Field(max_length=200)          # empathy or acknowledgement; no facts
    claims: list[MentorClaim] = Field(max_length=6)
    guidance: str | None = Field(max_length=400)  # general, non-factual advice
    next_question: str | None = Field(max_length=160)  # one question to keep the student going
    suggest_roadmap: bool
```

Checks (Pydantic validators for structure, plus a `semantic_check` for the label rule):
- `knows=False` ⇒ `claims == []`.
- `knows=True` ⇒ `len(claims) ≥ 1`.
- `opening` and `guidance` contain **no figures that look like facts**: no `₹`, `Rs`, `%`, no
  4-digit year, no date pattern. This is a cheap structural guard that stops uncited facts from
  slipping in through the uncited fields. Class numbers ("class 10") are allowed.

**Citation validation** (`semantic_check`, s05 hook): every label in `claims[*].sources` must be
one of the labels passed in. Then:
1. **First failure:** one repair retry, with the problem appended ("C7 was not provided. Cite
   only C1–C4."). This is the standard structured-output retry from S5.
2. **Still invalid:** drop every claim with an unknown label. If no claims remain, the answer
   becomes the don't-know answer (`knows=False`) built from the model's `opening` and `guidance`,
   and the step is recorded `DEGRADED` with `detail="citations_dropped"`.

**Body assembly (deterministic, in code, not by the model):**

```
{opening}
{claim 1 text} [1]
{claim 2 text} [2]
{guidance}
{next_question}
```

Citations are numbered by first use. `[n]` markers stay in `CanonicalReply.body`, and S9 keeps
them in `text` and removes them from `spoken_text`. `CanonicalReply.citations` holds the unique
cited chunks in order of first use (`Citation(title, source_url, chunk_id)`). `body_language =
ENGLISH`, because grounding works in the corpus language and S9 localises (B11). If
`suggest_roadmap` is true and there's no active roadmap, add a button
`ReplyButton(id="rm:create", title="Make a plan")` (the title is localised by S9's button rules).

**Child-protection line.** For an under-18 student describing family pressure such as early
marriage (golden student-mentor-006), the layer appends `crisis.child_protection_line(language)`
from s07: a fixed sentence, never generated.

**Don't-know mode** prompt instruction: say plainly that you don't have verified information on
this yet; give general, safe guidance (talk to a science teacher, the school's career cell,
finish the current class); never name an institute, exam, fee or date. This covers golden case
student-mentor-004.

**Prompt outline `app/prompts/mentor.md.j2`:**

```
+++
id = "mentor"
version = "1.0.0"
model_setting = "MODEL_TEXT"
reasoning_effort = "medium"
max_output_tokens = 1200
output_model = "MentorAnswer"
+++
You are Marg, a mentor for rural Indian students in classes 6–12. …
Rules:
- Every factual statement (exam, scheme, eligibility, amount, date, institute, process) goes in
  `claims` and cites the source labels it came from. Never state a fact that isn't in a source.
- `opening`, `guidance` and `next_question` contain no facts and no numbers.
- Don't assume a laptop, paid coaching or a city. Suggest free, nearby first steps.
- Never promise admission, selection, a job or a scholarship.
- Take every ambition seriously, including sports, arts and self-employment.
{% if system.dont_know %}No sources were found. Set knows=false and claims=[]. …{% endif %}
<sources>{% for c in system.chunk_blocks %}[{{ c.label }}] {{ c.title }} — {{ c.heading_path }}
{{ c.text }}
{% endfor %}</sources>
=== USER ===
Profile: {{ system.profile_block }}
{{ user.memory }}
{{ user.active_roadmap }}
{{ user.recent_conversation }}
{{ user.message }}
```

### 4.4 Roadmap — `app/layers/roadmap.py`

Two cases, decided by whether an active roadmap exists:

```
no active roadmap ─────────────────────────────▶ draft a new roadmap (RoadmapDraft) → SaveRoadmap
active roadmap, plain request ("mera plan") ───▶ show the current roadmap + button "New plan" (rm:create)
active roadmap, rm:create or "naya plan" ──────▶ draft a new roadmap; SaveRoadmap abandons the old one
```

**Drafting (`RoadmapDraft`):**

```python
class RoadmapDraftStep(BaseModel):
    action: str = Field(max_length=160)          # imperative, concrete: "Ask your class teacher for the NMMS form"
    timeframe: str = Field(max_length=40)        # "this week", "before your class 9 exams"
    cost_inr: Decimal | None = Field(ge=0)
    source: str | None                           # chunk label, e.g. "C3"
    free_now: bool                               # doable this week at no cost

class RoadmapDraft(BaseModel):
    goal: str = Field(max_length=80)             # "Become a doctor (NEET-UG)"
    steps: list[RoadmapDraftStep] = Field(min_length=3, max_length=6)
```

Validation in code (`semantic_check` plus post-repair rules):
- Every `source` label must have been provided. Same repair-then-drop rule as the mentor, except
  a step whose label is invalid keeps its action with `source=None` and `cost_inr=None`.
- `cost_inr` set ⇒ `source` required. A cost is a fact.
- A step whose `action` mentions any keyword from the retrieved documents' `keywords` (exam and
  scheme names) must have a `source`. Otherwise it gets one repair retry, then the step is dropped.
  If fewer than 3 steps remain → don't-know roadmap reply (below).
- At least one step has `free_now=True`. Otherwise repair retry, then `DEGRADED` with the reply sent anyway.
- **Don't-know roadmap:** if retrieval is `nothing_relevant`, no roadmap is drafted or stored.
  The reply says the plan can't be verified yet and gives the same safe general steps as mentor
  don't-know mode (golden roadmap-003).

**Reply body** (deterministic): goal line, numbered steps `n. action — timeframe [c]`. `CanonicalReply.citations`
comes from the step sources. The S9 spoken version reads the steps in order (golden roadmap-005).

**Write:** `SaveRoadmap(kind="save_roadmap", goal, steps: list[ResolvedRoadmapStep],
abandon_roadmap_id: UUID | None, prompt_version)`. When applied by s04: mark any active roadmap
`ABANDONED`, insert `roadmaps` (`ACTIVE`) and `roadmap_steps` (`TODO`, `source_url` from the
resolved chunk). The partial unique index on active roadmaps guarantees there's only one, even
under a race.

**Showing the current roadmap** renders the stored steps in the same format, with no model call.
Steps stay `TODO` in the MVP, since progress tracking is deferred.

Prompt: `roadmap.md.j2` (drafting; same context block, plus rules: 3–6 steps; at least one free
step this week; no paid coaching as a required step; facts only from sources). Model `MODEL_TEXT`,
`reasoning_effort="medium"`, `max_output_tokens=1000`.

### 4.5 Sessions

`TurnContext.is_session_start` (contracts §2.2, computed by s04 with `SESSION_GAP` from
`app/domain/rules/session_rules.py`) exists, but **nothing in S12 uses it in the MVP**: its only consumer
was the session check-in, which is deferred (§4.9).

### 4.6 Router requirements (implemented in S5)

- The router prompt gets `has_active_roadmap: bool` and the active roadmap's goal.
- "Plan banao", "roadmap", "naya plan", and the `rm:create` button → `ROADMAP`.
- Reply ids `rm:*` → `ROADMAP` without an LLM call.
- Progress reports ("maine form bhar diya") route to `MENTOR` in the MVP, which acknowledges them
  in general terms (progress tracking is deferred).

### 4.7 Memory — `app/layers/memory.py` (the `UpdateMemory` post-turn task)

**When:** the orchestrator adds `UpdateMemory` to `TurnOutcome.post_turn` for every turn whose
route is `MENTOR`, `ROADMAP` or `EXPOSURE` and that didn't send a fixed reply. Teachers have memory
too (subject, classes, chapters covered; approved, B8). Never for onboarding, crisis, refuse,
off-topic, fixed replies, or **`JOURNEY` turns** (parents have no profile memory in the MVP;
their continuity comes from `learner_activities` and curiosity signals, s10b/s13). s04 runs it
**after finalize, in its own short transaction**, so it adds no user-visible latency. Cost is one
small call per turn, negligible at Muse Spark prices. Updating every turn is chosen over "every N
turns" because a missed ambition is worse than a few cents, and N-turn batching complicates crash recovery.

```python
class MemoryUpdate(BaseModel):
    summary: str = Field(max_length=600)        # third person, facts the user told us, no names
    ambitions: list[str] = Field(max_length=5)  # each ≤ 60 chars, e.g. "doctor (NEET)", "kabaddi at state level"
    constraints: list[str] = Field(max_length=5)  # each ≤ 60 chars, e.g. "family money is tight"
```

- Inputs: the previous `ProfileMemory` (or none), this turn's `user_text` and reply text.
  Instructions: keep what's still true, add what's new, drop what the user contradicted. Record
  only what the user said about themselves, never content from sources.
- **Privacy guard** (`semantic_check`): `summary`, ambitions and constraints contain no digit run
  of 6 or more characters (phone numbers, PINs, Aadhaar fragments) and no email address. On
  failure: repair retry, then skip the update.
- Written by `ProfileMemoryRepository.upsert(user_hash, update, source_turn_id, prompt_version)`.
- If the user was deleted before the task runs, the upsert's foreign key fails; the task records
  `SKIPPED` with `detail="user_gone"` and stops. The next turn's update catches up otherwise.
- Failure never affects the user. It's recorded as a `turn_steps` row with step `UPDATE_MEMORY`
  (`FAILED` or `SKIPPED`).

Prompt `memory.md.j2`: `MODEL_TEXT`, `reasoning_effort="low"`, `max_output_tokens=400`.

### 4.8 Off-topic redirect — `app/layers/off_topic.py`

```python
class OffTopicReply(BaseModel):
    reply: str = Field(max_length=300)                  # 1–2 sentences: what Marg can help with
    related_field: str | None = Field(max_length=60)    # e.g. "sound engineering" for a song request
```

Rules in `off_topic.md.j2`:
- Never reproduce lyrics, essays or full homework. Offer to help the student start it themselves (golden off-topic-002).
- Stay politically neutral (off-topic-003).
- Offer a career angle when there's a natural one (off-topic-001). For parents, offer today's khoj instead.

No retrieval, no citations. `MODEL_TEXT`, `reasoning_effort="minimal"`, `max_output_tokens=200`.

### 4.9 Deferred (post-MVP, B9)

The design below is kept so it can be picked up later. It's **not** in S12's scope, interfaces,
tests or exit check.

- **Roadmap progress.** With an active roadmap, a `roadmap_progress` classification call returns
  `RoadmapProgressUpdate(kind: "progress" | "show" | "new_goal", completed_positions,
  skipped_positions, new_goal)`, with validators (positions exist and are `TODO`; completed and
  skipped sets don't overlap; `kind=progress` ⇒ ≥ 1 position; `kind=new_goal` ⇒ `new_goal` set).
  A write `ApplyRoadmapProgress(roadmap_id, completed_positions, skipped_positions)` would set the
  steps to `DONE`/`SKIPPED` with `completed_at`, and the roadmap to `COMPLETED` when no `TODO`
  remains. The reply congratulates briefly and names the next step, never regenerating the
  roadmap. Property: applying the same progress twice equals applying it once. Prompt
  `roadmap_progress.md.j2` at `"low"`, 300 tokens. Golden case **roadmap-004 is deferred** with it.
- **Session check-in.** On the first `MENTOR` or `ROADMAP` turn of a session
  (`TurnContext.is_session_start`), with an active roadmap that has a `TODO` step, the body would
  end with "Last time we planned: {next TODO action}. Have you done it?" and a button
  `rm:done:{position}` ("Ho gaya"), which the roadmap layer treats as a progress update without an
  LLM call. At most once per session; never on onboarding, crisis or refuse turns.

## 5. Interfaces

```python
# app/layers/results.py — the shared result of every generate handler (s08, s10, s10b, s12)
class LayerResult(BaseModel):
    reply: CanonicalReply
    writes: list[TurnWrite]                    # applied by s04 in the finalize transaction
    usages: list[StepUsage]                    # one per model call, summed into the GENERATE row
    prompt_versions: dict[str, str]
    outcome: Literal[StepOutcome.OK, StepOutcome.DEGRADED]
    degraded_reason: str | None

# app/layers/mentor.py
class MentorLayer:
    def __init__(self, llm: LanguageModel, rewriter: QueryRewriter, retriever: Retriever,
                 prompts: PromptRegistry, settings: Settings) -> None: ...
    async def answer(self, ctx: TurnContext) -> LayerResult: ...

# app/layers/roadmap.py
class RoadmapLayer:
    def __init__(self, llm: LanguageModel, rewriter: QueryRewriter, retriever: Retriever,
                 prompts: PromptRegistry, settings: Settings) -> None: ...
    async def handle(self, ctx: TurnContext, button_reply_id: str | None) -> LayerResult: ...

# app/layers/off_topic.py
class OffTopicLayer:
    async def redirect(self, ctx: TurnContext) -> LayerResult: ...

# app/layers/memory.py
class MemoryLayer:
    async def update(self, previous: ProfileMemory | None, user_text: str, reply_text: str
                     ) -> tuple[MemoryUpdate, StepUsage] | StepFailure: ...

# app/domain/writes.py (TurnWrite variant owned here)
class ResolvedRoadmapStep(BaseModel):
    action: str; timeframe: str; cost_inr: Decimal | None; source_url: HttpUrl | None
class SaveRoadmap(BaseModel):
    kind: Literal["save_roadmap"]
    goal: str
    steps: list[ResolvedRoadmapStep]
    abandon_roadmap_id: UUID | None
    prompt_version: str

# app/domain/models/ — persisted shapes loaded into TurnContext
class RoadmapStep(BaseModel):
    position: int; action: str; timeframe: str; cost_inr: Decimal | None
    source_url: HttpUrl | None; status: RoadmapStepStatus; completed_at: datetime | None
class Roadmap(BaseModel):
    id: UUID; goal: str; status: RoadmapStatus; steps: list[RoadmapStep]; created_at: datetime

# app/store/repositories/roadmaps.py
class RoadmapRepository:
    async def get_active(self, user_hash: UserHash) -> Roadmap | None: ...
    async def save(self, session: AsyncSession, user_hash: UserHash, write: SaveRoadmap) -> None: ...  # inside finalize

# app/store/repositories/memory.py
class ProfileMemoryRepository:
    async def get(self, user_hash: UserHash) -> ProfileMemory | None: ...
    async def upsert(self, user_hash: UserHash, update: MemoryUpdate, source_turn_id: TurnId,
                     prompt_version: str) -> None: ...
```

## 6. Data

- **Creates:** `roadmaps`, `roadmap_steps`, `profile_memory` (migration `s12_roadmaps_memory`),
  including the partial unique index `ON roadmaps (user_hash) WHERE status = 'active'`.
- **Reads:** `turns` (recent exchanges, via the S4 context builder), `roadmaps` and
  `roadmap_steps` (into `TurnContext.active_roadmap`), `profile_memory` (into `TurnContext.memory`),
  corpus tables through S11.
- **Writes:** `roadmaps`/`roadmap_steps` only through `SaveRoadmap` in s04's finalize transaction;
  `profile_memory` in the `UpdateMemory` post-turn task; `turn_steps` rows `GENERATE` and `UPDATE_MEMORY`.
- Everything cascades on user deletion (data-model.md).

## 7. Configuration

`MODEL_TEXT`, `TIMEOUT_GENERATE_S` (the whole generate step, including retrieval and the optional
rewrite), `TIMEOUT_UPDATE_MEMORY_S`, `RECENT_EXCHANGES`, `QUERY_REWRITE_ENABLED` (B9),
`SEARCH_GROUNDING_ENABLED` (stays `false`, B8), plus S11's retrieval settings. Budgets and length
limits are module constants or schema `Field`s.

## 8. Failure modes

| Failure | What the user gets | Recorded |
|---|---|---|
| Retrieval finds nothing relevant | Honest don't-know reply with safe general guidance | `GENERATE` OK, `detail="dont_know"` |
| Model cites a chunk it wasn't given | Repair retry; then the claim is dropped (or the answer becomes don't-know) | `DEGRADED`, `citations_dropped` |
| Fact-looking number in `opening`/`guidance` | Repair retry; then the field is dropped from the body | `DEGRADED`, `uncited_figure_removed` |
| Roadmap has fewer than 3 valid steps after repair | Don't-know roadmap reply; nothing stored | `DEGRADED`, `roadmap_unverifiable` |
| Mentor/roadmap model call fails (timeout, 5xx, invalid twice) | `TRY_AGAIN_LATER` fixed reply | `GENERATE` FAILED with kind |
| Two roadmap saves race | The second insert hits the partial unique index → the finalize transaction rolls back → the turn is retried with fresh context | `StoreError` logged |
| Reply blocked by `safety_out` | Holding reply; **no** roadmap is saved (writes never applied) | S7 |
| Memory update fails or leaks PII-like content | Nothing visible; memory unchanged | `UPDATE_MEMORY` FAILED/SKIPPED |

## 9. Tests

**Unit** (fake `LanguageModel` returning scripted outputs, fake retriever):
- `test_mentor_cites_only_provided_labels`
- `test_mentor_unknown_label_triggers_one_repair_then_drops_claim`
- `test_mentor_all_claims_dropped_becomes_dont_know_degraded`
- `test_mentor_nothing_relevant_uses_dont_know_mode_and_passes_no_chunks`
- `test_mentor_answer_rejects_knows_false_with_claims` / `…_knows_true_without_claims`
- `test_guidance_with_rupee_amount_rejected` / `…_with_year_rejected` / `test_guidance_with_class_number_allowed`
- `test_body_assembled_with_numbered_citations_in_first_use_order`
- `test_duplicate_source_across_claims_yields_single_citation`
- `test_suggest_roadmap_adds_button_only_without_active_roadmap`
- `test_query_rewrite_skipped_when_disabled` (the fake rewriter is never called)
- `test_child_protection_line_appended_for_minor_family_pressure`
- `test_roadmap_draft_requires_3_to_6_steps` (2 and 7 rejected; 3 and 6 accepted)
- `test_roadmap_cost_without_source_rejected`
- `test_roadmap_step_naming_exam_keyword_without_source_repaired_then_dropped`
- `test_roadmap_requires_one_free_now_step`
- `test_roadmap_nothing_relevant_stores_nothing` (no `SaveRoadmap` in `writes`)
- `test_active_roadmap_request_shows_current_without_llm_call`
- `test_rm_create_with_active_roadmap_abandons_old` (the write carries `abandon_roadmap_id`)
- `test_memory_rejects_six_digit_runs_and_emails`
- `test_memory_not_scheduled_for_journey_onboarding_crisis_fixed_or_off_topic_turns`
- `test_memory_failure_never_changes_reply`
- `test_off_topic_reply_length_and_no_retrieval`
- `test_context_drops_oldest_exchange_first_and_keeps_latest`; `test_context_never_trims_inside_a_chunk`
- `test_user_derived_context_goes_in_user_slots_not_system` (memory, roadmap, exchanges)
- `test_writes_not_applied_when_safety_out_blocks` (pipeline-level, fake safety)

**Property (hypothesis):**
- Citation numbering: for any list of claims with valid labels, the body markers `[n]` are
  exactly `1..len(citations)`, each citation is referenced at least once, and the order is by first use.
- Context assembly: for any profile, memory, chunks and exchanges, `approx_tokens(rendered) ≤
  CONTEXT_BUDGET_TOKENS` or only the mandatory sections remain; user text and profile are always present.

**Negative:** an empty `user_text` never reaches S12 (S5's router turns it into `REPEAT_PLEASE`),
asserted with a guard that raises `DomainError`; `RoadmapDraft` with `cost_inr=-1` rejected; a
profile with no grade → retrieval runs without a grade filter (not an error).

**Integration (`-m integration`):**
- `test_save_roadmap_write_commits_with_outbox_atomically`: fail the outbox insert, and no roadmap row exists.
- `test_partial_unique_index_allows_one_active_roadmap`.
- `test_user_deletion_cascades_roadmaps_and_memory`.
- `test_memory_upsert_overwrites_previous`.
- `test_memory_task_after_user_deleted_records_skipped`.

## 10. Exit check

On a real phone (or `/demo` once S14 exists), with a real corpus and models:
1. A student asks "क्लास 8 में कोई स्कॉलरशिप मिलती है क्या?" and gets a cited answer. The text
   shows `[1]` with the official link, and the voice note doesn't read the link.
2. "Marine biologist kaise bante hain?" gets an honest don't-know reply with no invented institutes.
3. "Doctor banna hai, plan bana do" stores a roadmap (3–6 steps, at least one free this week,
   exam steps cited). Confirm the row in `roadmaps`.
4. "Mera plan dikhao" shows the same roadmap with a "New plan" button, and no new row.
5. `profile_memory` holds a summary mentioning the ambition, with no phone-like numbers.
6. Golden cases student-mentor-001…010, roadmap-001, 002, 003, 005, multiturn-001…003 and
   off-topic-001…003 pass in `marg eval` (once S15 exists; until then, check by hand).
   roadmap-004 is deferred. Verification loop green.

## 11. Open questions

1. ~~English canonical body~~ **Resolved by B11:** mentor and roadmap generate in English, and a
   separate translation step localises.
2. ~~Search grounding~~ **Resolved by B8:** off for the MVP. A grounded web result has no
   `chunk_id`, so turning it on later needs a contract change (an optional `chunk_id` plus a
   `source_kind`) and its own validation.
3. ~~Teacher memory~~ **Resolved by B8:** teachers get memory.

## 12. Contract changes (resolved 2026-10-25)

| Request (v1) | Resolution |
|---|---|
| `StepName.UPDATE_MEMORY` | Applied (contracts §1). Memory is the `UpdateMemory` post-turn task (B2). |
| `MentorClaim`, `OffTopicReply`, `LayerResult`, `ResolvedRoadmapStep` in §2.6 | Applied (contracts §2.7). |
| `PendingEffect`, `SaveRoadmap`, `ApplyRoadmapProgress` | Unified into `TurnWrite` (B2). `SaveRoadmap` applied; `ApplyRoadmapProgress` **deferred** (B9). `LayerResult.effects` renamed `writes`. |
| `enqueue_reply` applies effects with the outbox | Applied as s04's finalize transaction applying `TurnOutcome.writes` (B2). |
| `TurnContext.is_session_start` | Applied (contracts §2.2), computed with `SESSION_GAP`. Unused in the MVP since check-ins are deferred. |

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-28 | **`TIMEOUT_MENTOR_S` 18 s** for the mentor and the roadmap (parents' replies stay 12 s), inside the 25 s turn budget | The eval: two mentor turns timed out at 12 s. Owner: "yes we can" | owner |
| 2026-10-25 | v1 written | aspirational layer design | owner |
| 2026-10-25 | `PendingEffect` → `TurnWrite`, `LayerResult.writes`; roadmap progress, check-ins and `rm:done` moved to Deferred; memory as a post-turn task, teachers included, no memory for journey turns; query rewriting behind `QUERY_REWRITE_ENABLED`; strict-schema fields without defaults; user-derived context in user slots | B2, B8, B9, B11 and the consolidated contracts | owner |
| 2026-10-28 | **Owner: build the Aspirational engine** (auto-commit when green; review at the end of step 8) | Time allows | owner |
| 2026-10-28 | **Mentor, roadmap and memory built (§4.2–§4.8).** Build choices, pending review: (1) the student role opens in onboarding (third role button, ASK_ROLE names students, copy `onb-2026-10-28.1`; the guardian, class and district steps were already in the state machine); (2) students are routed without a model: `rm:` buttons and plan phrases ("plan banao", "mera plan", "naya plan", "roadmap", Hindi forms) → ROADMAP, any other message → MENTOR; (3) off-topic is folded into the mentor's don't-know mode (nothing relevant is retrieved for a song or cricket, and the prompt redirects kindly, offering a related career), so there is no separate OffTopicLayer; (4) like the parent layers, mentor and roadmap write in the student's register directly (C3c), not English plus S9; (5) a reply still citing a label it wasn't given after the repair retry becomes reviewed don't-know copy (DEGRADED `citations_dropped`) rather than a partly dropped answer; a provider outage stays TRY_AGAIN_LATER; (6) sources are numbered per document, not per chunk; (7) the "step naming an exam keyword needs a source" rule isn't enforced in code (retrieved chunks don't carry document keywords): the prompt asks for it, and a cost without a valid source is never stored; (8) the child-protection line is a phrase rule (marriage words) for a student whose estimated age is under 18 (or unknown), with Childline 1098 from `crisis_replies.py`; (9) a short plan request ("plan banao") is searched together with the student's remembered ambitions; (10) a question asked during onboarding is answered by the mentor in the same turn the profile completes; (11) prompts carry a rule against gendered verbs about Marg (live check: "nahi suna sakti"). Live check 2026-10-28 on 50 documents: NMMS (Hindi) cited from the guideline PDFs in 5.2 s; Sainik admission grounded; marine biologist and a song request honest/redirected; an ISRO plan saved with sourced steps in 4.7 s | S12 build | pending owner review |
| 2026-10-29 | **Stay on a named goal, plus one line** (`mentor` 1.1.4, `query_rewrite` 1.0.3): the mentor answers about the goal the student named; if the sources name another way into the same field (doctor: nursing or pharmacy), that is its last claim, one cited sentence, never a different field. The rewriter adds one related course of the same field to the search | Golden cases student-mentor-002 (a doctor question; no other health path) and multiturn-001 (the army question pulled to nursing on 2026-10-28) wanted opposite things. Live: 002 2/2 (with the new nursing and pharmacy sources), army 3/4 then 2/2 | owner |
