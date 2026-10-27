# S13 — Telemetry: turn metrics, aspiration and curiosity signals, trajectory, dashboards

> **Hackathon build level: Full (scoped). Parent and young-learner parts (mvp-scope.md §4.5).** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

## 1. Purpose

Make the system **measurable**, for two audiences:
- **Operators and judges** see whether it works: latency per step, success rate, and cost
  (`/status`).
- **Educators and judges** see whether it matters: the *trajectory* of each learner. For
  students, how ambitions widen and sharpen over time. For young children in the parent journey,
  how curiosity broadens and deepens, and whether the child starts asking their own questions.
  Both are shown on `/dashboard`. Teachers reach it through a signed link sent on WhatsApp, with
  no passwords (A4).

S5 already writes one `turn_steps` row per step. S13 adds the signal-extraction post-turn task
(aspiration signals for students, curiosity signals for parent reports), the trajectory math,
the aggregate queries and the two pages.

## 2. Read first

- [contracts.md](contracts.md): §1 `StepName.EXTRACT_SIGNALS`, `StepOutcome`, `FixedReplyKind`,
  `Route`, `AspirationField`, `ConstraintKind`, `CuriosityDomain`, `Sentiment`; §2.2 `Learner`,
  `TurnContext`; §2.3 `StepUsage`, `TurnOutcome.post_turn`; §2.4 `PostTurnTask` (`ExtractSignals`),
  `ActivityReported`; §7 `SESSION_SIGNING_KEY`, `DAILY_COST_CAP_USD`, `K_ANONYMITY_FLOOR`
- [data-model.md](data-model.md): `turns`, `turn_steps`, `aspiration_signals`, `curiosity_signals`,
  `learners`, `learner_activities`, `roadmap_steps`, `inbox_messages`, `outbox_messages`, view `turn_metrics`
- [00-overview.md](00-overview.md) §4 (post-turn tasks run after finalize)
- [s10b-parent-journey.md](s10b-parent-journey.md) §4.4 flow B (the report that produces curiosity signals)
- [plan.md](../../plan.md) §4.8; [CLAUDE.md](../../CLAUDE.md) §3 (trajectory properties), §11 (no text on dashboards, hashes only)

## 3. Scope

**In:**
- The `ExtractSignals` post-turn task, and the `AspirationSignals` and `CuriositySignals` schemas
  with their fixed vocabularies.
- `app/domain/rules/session_rules.py` (pure math), including `SESSION_GAP`.
- Aggregate SQL and the `turn_metrics` view.
- `/status`, `/dashboard`, `/dashboard/data.json`.
- The k-anonymity floor.
- Signed dashboard links for teachers (district scope) and admin, using the shared `SignedTokenCodec`.
- The `Route.DASHBOARD_LINK` generate handler.

**Out:**
- Writing `turn_steps`: S5.
- Load testing and alert thresholds: S16.
- Eval scorecards: S15.
- Public-facing marketing pages.
- **Deferred (B9):** classroom codes (§4.8).

## 4. Design

### 4.1 Turn metrics (read model, no new writes)

`turn_steps` (S5) plus `turns` (S4) already hold everything per turn. S13 adds a SQL **view**,
`turn_metrics`, created in the S13 migration, so every query reads the same definition:

```sql
CREATE VIEW turn_metrics AS
SELECT t.id                         AS turn_id,
       t.user_hash,
       t.route,
       t.status,
       t.fixed_reply_kind,
       t.failure_step,
       t.failure_kind,
       t.started_at,
       first_in.received_at         AS first_received_at,
       first_out.sent_at            AS first_sent_at,
       EXTRACT(EPOCH FROM (first_out.sent_at - first_in.received_at)) * 1000 AS user_latency_ms,
       COALESCE(steps.cost_usd, 0)  AS cost_usd,
       (t.status = 'completed'
        AND (t.fixed_reply_kind IS NULL OR t.fixed_reply_kind NOT IN ('holding','try_again_later'))
       )                            AS served_ok
FROM turns t
LEFT JOIN LATERAL (SELECT min(received_at) AS received_at FROM inbox_messages i WHERE i.turn_id = t.id) first_in ON true
LEFT JOIN LATERAL (SELECT min(sent_at) AS sent_at FROM outbox_messages o WHERE o.turn_id = t.id) first_out ON true
LEFT JOIN LATERAL (SELECT sum(cost_usd) AS cost_usd FROM turn_steps s WHERE s.turn_id = t.id) steps ON true;
```

- **User latency** runs from the first inbound message being stored to the first reply part
  being sent. That's what the user actually waits. `NUDGE` turns have no inbound message, so their
  latency is NULL and they're excluded from latency percentiles.
- **`served_ok`**: the turn completed and the user got a real answer, not a holding or try-later
  fallback. Crisis, refuse and repeat-please replies count as served correctly. (`completed`
  includes turns that sent a fallback, B3, which is why `fixed_reply_kind` is checked.)

### 4.2 The `ExtractSignals` post-turn task — `app/telemetry/signals.py`

`ExtractSignals` is a `PostTurnTask` (contracts §2.4). The orchestrator adds it to
`TurnOutcome.post_turn` when the turn qualifies; s04 runs it **after finalize, in its own short
transaction**. It's off the critical path, and failure never affects the reply.

| Turn | Extracted | Skipped (`turn_steps` `SKIPPED`, `detail`) |
|---|---|---|
| Student (`role == STUDENT`), route `MENTOR`, `ROADMAP` or `OFF_TOPIC`, no fixed reply | `AspirationSignals` for the student's `self` learner | — |
| Parent, route `JOURNEY`, and the turn's writes include an `ActivityReported` | `CuriositySignals` for the reported activity's learner | — |
| Route `CHILD_TALK` with a generated reply (C13), or a `JOURNEY` curiosity-moment turn (C11) | `CuriositySignals` for the active learner, with `child_asked_question = true` when the child (or the parent relaying) asked a question; judged from the child's own words, never labelling the child | — |
| Teacher turns | — | `not_learner_turn` |
| Fixed replies, onboarding, crisis, refuse, data deletion, dashboard link, nudge | — | `not_applicable` |
| Parent `JOURNEY` turn with no report (an activity offered, a question, settings) | — | `no_report` |

Writes are idempotent: `INSERT … ON CONFLICT (turn_id) DO NOTHING`, so a retried task can't
double-count. If the user (and so the learner) was deleted before the task ran, the insert's
foreign key fails; the task records `SKIPPED` with `detail="user_gone"`.

### 4.3 Aspiration signals (students) — `app/domain/aspiration.py`

**Vocabularies** (contracts §1): `AspirationField`, `ConstraintKind`, `Sentiment`.

`AspirationField`: `medicine`, `health_allied` (nursing, pharmacy, physiotherapy),
`engineering`, `technology_computing`, `science_research`, `space_aerospace`,
`agriculture`, `public_policy`, `civil_services`, `defence_police`, `law`, `teaching`,
`sports`, `arts_design`, `media_communication`, `entrepreneurship`, `finance_commerce`,
`skilled_trades` (ITI, electrician, mechanic …), `other`.

`ConstraintKind`: `money`, `distance` (no college or academy nearby), `family` (family
expectations or permission), `gender_norms`, `language` (English barrier), `time` (work or
chores), `marks` (exam results), `information` (doesn't know where to ask), `device` (no phone or internet of their own).

**Specificity rubric (0–4), for the student's own words in this turn:**

| Level | Meaning | Examples |
|---|---|---|
| 0 | No career content | "Photosynthesis samajh nahi aaya", "koi gaana sunao" |
| 1 | Curiosity, no field | "Ye padh ke koi job milti hai kya?", "aage kya karun?" |
| 2 | Names a field or interest | "Mujhe sports pasand hai", "science mein interest hai" |
| 3 | Names a role or a concrete path | "Doctor banna hai, NEET dena hai", "state level kabaddi" |
| 4 | Reports an action taken, or commits to one with a timeframe | "Maine NMMS form bhar diya", "Is hafte district trial mein jaunga" |

```python
class AspirationSignals(BaseModel):          # structured output; also the persisted shape
    fields: list[AspirationField] = Field(max_length=3)
    specificity: int = Field(ge=0, le=4)
    constraints: list[ConstraintKind] = Field(max_length=3)
    sentiment: Sentiment
```

Checks (`semantic_check`): `specificity == 0` ⇒ `fields == []`; `specificity ≥ 2` ⇒ `len(fields) ≥ 1`; no duplicates.

**Prompt `aspiration_extract.md.j2`:** the rubric table and the vocabularies, with an
instruction to judge **only the student's message** (the reply and sources are context, not
evidence). Inputs: `user_text` and the previous exchange (user slots, so "uske liye" resolves),
role, grade. `MODEL_TEXT`, `reasoning_effort="minimal"`, `max_output_tokens=150`.

Persisted to `aspiration_signals` with `learner_id` = the student's `self` learner (from
`TurnContext.learners`).

### 4.4 Curiosity signals (young children) — `app/domain/aspiration.py`

Extracted from the **parent's report** of what the child said or did with the khoj (s10b flow B).
It describes what the child engaged with. It **never labels the child** (no "gifted", "slow",
"good at maths"): only domains, a level of engagement, and whether the child asked a question.

`CuriosityDomain` (contracts §1): `nature_living`, `earth_sky`, `numbers_patterns`,
`words_stories`, `making_building`, `movement_body`, `art_music`, `people_feelings`, `everyday_work`.

**Engagement rubric (0–3):**

| Level | Meaning | Example parent report |
|---|---|---|
| 0 | No response, or the child didn't want to | "Usne kuch nahi kaha, khelne chala gaya" |
| 1 | Brief, one-word or yes/no | "Bola 'suraj'" |
| 2 | An engaged answer to the question | "Bola parchhai suraj ki wajah se ghoomti hai" |
| 3 | An extended explanation, or a new idea of their own | "Bola raat ko chaand ki bhi parchhai banegi kya, aur khud try karne gaya" |

`child_asked_question` is true when the report says the child asked their own question
("usne poocha…"), whatever the engagement level. It's the single most important early-curiosity signal.

```python
class CuriositySignals(BaseModel):           # structured output; also the persisted shape
    domains: list[CuriosityDomain] = Field(max_length=3)
    engagement: int = Field(ge=0, le=3)
    child_asked_question: bool
```

Checks (`semantic_check`): no duplicate domains; `engagement == 0` ⇒ `child_asked_question` is
false; `engagement ≥ 2` ⇒ `len(domains) ≥ 1`. The activity's own catalogue domains are passed as
a hint, but the extraction may name others the child went into.

**Prompt `curiosity_extract.md.j2`:** the rubric, the vocabulary and the "never label the child"
rule. It judges **only the parent's report of the child**, not Marg.ai's reply. Inputs: the
activity title and domains (system data), the report (a user slot), the child's age.
`MODEL_TEXT`, `reasoning_effort="minimal"`, `max_output_tokens=120`.

Persisted to `curiosity_signals` with the learner from the `ActivityReported` write.

### 4.5 Trajectory math — `app/domain/rules/session_rules.py` (pure, no I/O)

Inputs are plain domain records, so the math can be property-tested without a database.

```python
SESSION_GAP = timedelta(hours=6)      # the only definition of a session; s04 uses it for TurnContext.is_session_start

@dataclass(frozen=True)
class SignalPoint:                     # students
    at: datetime                       # turns.started_at
    fields: frozenset[AspirationField]
    specificity: int                   # 0..4

@dataclass(frozen=True)
class CuriosityPoint:                  # young learners
    at: datetime
    domains: frozenset[CuriosityDomain]
    engagement: int                    # 0..3
    child_asked_question: bool

@dataclass(frozen=True)
class StudentTrajectory:
    sessions: int
    breadth: int                       # distinct fields explored, excluding OTHER
    specificity_by_session: list[int]  # max specificity per session, chronological
    specificity_slope: float | None    # None when sessions < 2
    returned: bool                     # sessions >= 2

@dataclass(frozen=True)
class YoungLearnerTrajectory:
    sessions: int
    activities_offered: int
    activities_done: int
    done_rate: float | None            # None when activities_offered == 0
    curiosity_breadth: int             # distinct curiosity domains across all reports
    engagement_by_session: list[int]   # max engagement per session, chronological
    engagement_slope: float | None     # None when sessions < 2
    child_question_rate: float | None  # reports with child_asked_question ÷ reports; None when no reports
    child_talk_sessions: int           # child_sessions for this learner (C13)
    questions_per_session: float | None  # child-talk turns with child_asked_question ÷ sessions; None when 0 sessions
    child_talk_domains: int            # distinct curiosity domains from child-talk turns
    returned: bool

def split_sessions(times: Sequence[datetime]) -> list[list[int]]: ...   # indices grouped into sessions
def breadth(points: Sequence[SignalPoint]) -> int: ...
def curiosity_breadth(points: Sequence[CuriosityPoint]) -> int: ...
def ols_slope(per_session: Sequence[int]) -> float | None: ...
def student_trajectory(points: Sequence[SignalPoint]) -> StudentTrajectory: ...
def young_learner_trajectory(points: Sequence[CuriosityPoint], offered: int, done: int) -> YoungLearnerTrajectory: ...
```

**Exact definitions:**
- **Sessions:** sort by time. A new session starts when `at − previous.at > SESSION_GAP`. A gap of
  exactly 6 h stays in the same session. Ties in time keep their relative order (see the properties below).
- **Breadth** (students) = `| ⋃ fields over all points | − (1 if OTHER present else 0)`.
- **Curiosity breadth** (young learners) = `| ⋃ domains over all points |`.
- **Per-session value** = `max(specificity)` or `max(engagement)` over that session's points.
- **Slope:** ordinary least squares of `s_i` against the session index `i = 0..n−1`:
  `slope = Σ (i − ī)(s_i − s̄) / Σ (i − ī)²`. Defined only for `n ≥ 2`, which guarantees the
  denominator is positive. Units: levels per session. The same `ols_slope` serves both trajectories.
- **Done rate** = `activities_done / activities_offered` from `learner_activities` (`done` vs all
  rows; `skipped` counts as offered and not done).
- **Child-question rate** = reports with `child_asked_question` ÷ reports.
- **Cohort return rate** = learners with `returned` ÷ learners whose first session started more
  than 24 h ago. Newer learners are excluded so they don't drag the rate down.

(Roadmap completion rate is deferred with roadmap progress tracking, B9. Steps stay `todo` in the MVP.)

### 4.6 Aggregate SQL — `app/store/repositories/telemetry.py`

**Step latency, last 24 h** (`/status`):

```sql
SELECT step,
       count(*)                                                         AS runs,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ms)       AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)       AS p95_ms,
       avg((outcome IN ('ok','degraded'))::int)                         AS ok_rate,
       avg((outcome = 'degraded')::int)                                 AS degraded_rate
FROM turn_steps
WHERE started_at >= now() - interval '24 hours'
GROUP BY step
ORDER BY step;
```

**Turn level, last 24 h:**

```sql
SELECT count(*)                                                      AS turns,
       avg(served_ok::int)                                            AS served_ok_rate,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY user_latency_ms) AS p50_user_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY user_latency_ms) AS p95_user_ms,
       count(*) FILTER (WHERE fixed_reply_kind = 'crisis')            AS crisis_turns,
       count(*) FILTER (WHERE route = 'journey')                      AS journey_turns,
       count(*) FILTER (WHERE route = 'nudge')                        AS nudges_sent
FROM turn_metrics
WHERE started_at >= now() - interval '24 hours';
```

(`percentile_cont` ignores the NULL latencies of nudge turns.)

**Cost today (IST day)**, `cost_today_usd(channel: Channel | None)`:

```sql
SELECT COALESCE(sum(s.cost_usd), 0)
FROM turn_steps s
JOIN turns t ON t.id = s.turn_id
JOIN users u ON u.user_hash = t.user_hash
WHERE s.started_at >= (date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata')
  AND (:channel IS NULL OR u.channel = :channel);
```

This is the one definition of "today's cost". S14 imports it with `channel='web'` for the demo's
`DAILY_COST_CAP_USD` check; `/status` (admin) shows it with `channel=NULL`.

**Student trajectory inputs** (district or all):

```sql
SELECT l.id AS learner_id, t.started_at, s.fields, s.specificity
FROM aspiration_signals s
JOIN turns t    ON t.id = s.turn_id
JOIN learners l ON l.id = s.learner_id
JOIN users u    ON u.user_hash = l.owner_user_hash
WHERE l.relation = 'self' AND u.role = 'student'
  AND (:district IS NULL OR u.district = :district)
ORDER BY l.id, t.started_at;
```

Child talk on the dashboard (C13) is **aggregate only**: sessions per learner (median), questions per session, domains touched, end reasons (turn limit, time limit, child ended, crisis, expired: crisis counted only on the admin `/status`). Parent summaries are counted (sent / not sent), **never their text**; no transcript of a child ever reaches a page.

**Young-learner trajectory inputs** (all only; parents aren't asked their district, s08):

```sql
SELECT l.id AS learner_id, t.started_at, c.domains, c.engagement, c.child_asked_question
FROM curiosity_signals c
JOIN turns t    ON t.id = c.turn_id
JOIN learners l ON l.id = c.learner_id
WHERE l.relation = 'parent'
ORDER BY l.id, t.started_at;

SELECT learner_id, count(*) AS offered, count(*) FILTER (WHERE status = 'done') AS done
FROM learner_activities GROUP BY learner_id;
```

Python then computes the trajectories per learner and aggregates. Cohorts are small (hundreds of
learners), so in-process aggregation is fine.

### 4.7 Pages — `app/api/dashboard.py`, templates in `app/static/dashboard/`

Server-rendered HTML (Jinja2), with charts drawn as **inline SVG generated server-side**. No
JavaScript chart library and no new dependency. Each page also has a JSON twin for the demo
video and for debugging.

**`GET /status`** (public, B8):
- p50 and p95 user latency, served-ok rate, turn count (24 h).
- Per-step table: runs, p50, p95, ok rate, degraded rate. It includes the image steps
  `FETCH_IMAGE`, `ANALYZE_IMAGE` and `MAKE_CARD` (C6, C7) with no special handling: they're ordinary
  `turn_steps` rows. `MAKE_CARD` runs as a post-turn task, so it's excluded from user latency.
- Journey counts (24 h): journey turns, nudges sent, photos received, photos rejected by the person
  check (`PHOTO_HAS_PERSON`), khoj cards sent.
- Corpus chunk count.
- Last-updated time.
- With the admin scope (§4.9) only: cost today (all channels, and web against the cap; it already
  includes image generation and segmentation, because Muse Image and SAM 3.1 calls record their
  `cost_usd` in `turn_steps` like every other provider call), crisis-turn count, and failure kinds by step.

**`GET /dashboard`** (scoped by signed link, §4.9). For the scope's cohort:

*Students*
1. **Headline:** students, sessions, cohort return rate, median breadth, median slope.
2. **Specificity over time:** stacked bars per ISO week, share of student sessions at each level 0–4.
3. **Breadth distribution:** histogram of breadth (0, 1, 2, 3, 4+).
4. **Fields explored:** count of distinct students per `AspirationField`.
5. **Constraints mentioned:** count of distinct students per `ConstraintKind`. This tells a
   teacher *what holds students back*, which is the actionable part.
6. **Roadmaps:** created (completion is deferred).
7. **Route mix:** share of mentor, roadmap, exposure and off-topic turns.

*Parents & young learners* (admin scope only, since parents have no district):
8. **Headline:** children, parents, cohort return rate, median done rate.
9. **Curiosity breadth distribution:** histogram (1, 2, 3, 4+ domains).
10. **Domains explored:** count of distinct children per `CuriosityDomain`.
11. **Engagement over time:** stacked bars per ISO week, share of reports at each level 0–3.
12. **Child-question rate** over time, per ISO week.
13. **Photos and cards** (C6, C7): share of reports that came with a usable photo (counts found),
    and khoj cards sent. **Forwarding can't be measured**: WhatsApp doesn't tell a business when a
    user forwards a message, so "viral" reach is shown only as cards sent, never as an estimate.

**k-anonymity floor:** any displayed number or chart cell derived from **fewer than
`K_ANONYMITY_FLOOR` (5) distinct learners** shows "fewer than 5" instead of the value. A section
shows "Not enough learners yet" when its cohort has fewer than 5. It's implemented once, in
`app/telemetry/aggregates.py::suppress_small(count_by_key, floor)`, and applied to every
aggregate before rendering. **No raw text, no hashes, no nicknames and no per-learner rows ever reach a page.**

### 4.8 Deferred: classroom codes (B9)

Classroom codes (a teacher shares `join MARG-XXXX` so students attach to their class, giving a
per-class dashboard) were designed in v1 and trimmed for time. Without them, a teacher's view is
their **district**, which still shows the trajectory story at k ≥ 5. Adding codes later means one
table, one `users` column, a `join` onboarding branch and a `classroom` scope kind. Nothing else
here would change.

### 4.9 Signed dashboard links (decision A4) — `app/telemetry/links.py`

No passwords. A teacher is already authenticated by WhatsApp (their phone number), so a
WhatsApp message is the login.

**Flow:**
1. A teacher in `ACTIVE` state sends "dashboard" (or taps a `dash:open` button). The router (S5)
   maps the exact keyword (case-insensitive, also "डैशबोर्ड") or the button to
   `Route.DASHBOARD_LINK`, only for `role == TEACHER`. A student or parent saying "dashboard"
   goes to their normal routes.
2. The generate handler (`DashboardLinkLayer`, owned here) mints a token and replies: "Your
   district dashboard (valid 15 minutes): {url}". The reply is fixed-format text (no LLM), still
   goes through `safety_out` and the outbox like any other, and isn't translated beyond its fixed
   three-language versions.
3. `GET /dashboard?t=<token>` verifies the token, sets an HttpOnly, Secure, SameSite=Lax cookie
   `marg_dash` holding a fresh token with `DASHBOARD_COOKIE_TTL_S` (2 h), and redirects to
   `/dashboard` (the token is stripped from the URL, so it doesn't sit in browser history).
4. Admin access: `marg admin-link` (CLI) mints an `admin` token for you. There's no admin password
   or static admin token.

**Tokens use the shared `SignedTokenCodec`** (`app/core/sessions.py`, also used by s14's session cookie):

```python
class SignedTokenCodec:
    def __init__(self, key: SecretStr, previous_key: SecretStr | None, clock: Clock) -> None: ...
    def issue(self, purpose: str, payload: Mapping[str, JsonValue], ttl_s: int) -> str: ...
    def verify(self, token: str, purpose: str) -> VerifiedToken | None: ...

class VerifiedToken(BaseModel):    # frozen
    payload: dict[str, JsonValue]
    issued_at: datetime
    expires_at: datetime
    needs_refresh: bool            # signed with the previous key (or close to expiry, codec-defined)
```

The signature is HMAC-SHA256 over `"<purpose>." + body` with `SESSION_SIGNING_KEY`
(`SESSION_SIGNING_KEY_PREVIOUS` is accepted for verification only). The purpose prefix is the
domain separation: a web session token (purpose `"demo_session"`, s14) can't be accepted as a dashboard
token, and vice versa. Dashboard tokens use purpose **`"dash"`** with this payload:

```python
class DashboardClaims(BaseModel):
    v: Literal[1]
    scope: Literal["teacher", "admin"]
    sub: str                        # the teacher's user_hash, or "admin"
    district: str | None            # teacher scope; None for admin
```

- Verification: `verify(token, "dash")` returns `None` on any failure (bad signature, expired,
  wrong purpose, malformed). Then `DashboardClaims.model_validate(payload)`; a validation failure
  is also a rejection. Link TTL `DASHBOARD_LINK_TTL_S` (15 min); cookie TTL 2 h.
- Failure gives `401` with a page explaining how to get a new link. It never says which check
  failed. Internally that's `LinkInvalid` (contracts §4), logged as `dashboard_link_rejected` with a
  reason code and no token.
- Known limitation: the link isn't single-use. Anyone with it can view **aggregates** for 15
  minutes. That's acceptable because the page holds no personal data and enforces k-anonymity.

**Scope resolution** (what cohort a token sees):
- `admin`: all learners, both student and young-learner sections. Cost and crisis counts are visible on `/status`.
- `teacher`: students whose `users.district` exactly equals the teacher's district (as stored by
  s08), student sections only, still subject to k ≥ 5. A teacher with no district sees "Not enough learners yet".

## 5. Interfaces

```python
# app/telemetry/signals.py
class SignalExtractor:
    def __init__(self, llm: LanguageModel, prompts: PromptRegistry, settings: Settings) -> None: ...
    async def run(self, task: ExtractSignals, ctx: TurnContext) -> SignalOutcome: ...
    # SignalOutcome = AspirationResult | CuriosityResult | Skipped | StepFailure, each with StepUsage where a call was made

def signals_task_for(ctx: TurnContext, route: Route, fixed_kind: FixedReplyKind | None,
                     writes: Sequence[TurnWrite]) -> ExtractSignals | None: ...   # §4.2 table; used by the orchestrator

# app/domain/rules/session_rules.py   — §4.5
# app/telemetry/aggregates.py
class CohortScope(BaseModel):
    kind: Literal["all", "district"]
    district: str | None

class CohortDashboard(BaseModel):            # what the template renders; also /dashboard/data.json
    students: StudentSection
    young_learners: YoungLearnerSection | None   # None outside admin scope

class StatusReport(BaseModel): ...           # §4.7 /status contents; cost and crisis fields None unless admin

def suppress_small(counts: Mapping[K, int], floor: int) -> dict[K, int | None]: ...
async def build_dashboard(repo: TelemetryRepository, scope: CohortScope, include_young: bool) -> CohortDashboard: ...
async def build_status(repo: TelemetryRepository, include_admin: bool) -> StatusReport: ...

# app/telemetry/links.py
def mint_dashboard_link(codec: SignedTokenCodec, claims: DashboardClaims, ttl_s: int) -> str: ...
def read_dashboard_token(codec: SignedTokenCodec, token: str) -> DashboardClaims: ...   # raises LinkInvalid

# app/layers/dashboard_link.py
class DashboardLinkLayer:
    async def handle(self, ctx: TurnContext) -> LayerResult: ...

# app/store/repositories/telemetry.py
class TelemetryRepository:
    async def step_latency_24h(self) -> list[StepLatencyRow]: ...
    async def turn_summary_24h(self) -> TurnSummaryRow: ...
    async def cost_today_usd(self, channel: Channel | None) -> Decimal: ...
    async def student_points(self, scope: CohortScope) -> dict[LearnerId, list[SignalPoint]]: ...
    async def young_learner_points(self) -> dict[LearnerId, list[CuriosityPoint]]: ...
    async def activity_counts(self) -> dict[LearnerId, ActivityCounts]: ...
    async def route_mix(self, scope: CohortScope) -> dict[Route, int]: ...
    async def save_aspiration(self, turn_id: TurnId, learner_id: LearnerId, signals: AspirationSignals,
                              prompt_version: str) -> None: ...                    # ON CONFLICT DO NOTHING
    async def save_curiosity(self, turn_id: TurnId, learner_id: LearnerId, signals: CuriositySignals,
                             prompt_version: str) -> None: ...                     # ON CONFLICT DO NOTHING
```

`LearnerId` and `UserHash` keys never leave the repository and aggregates layer. `CohortDashboard` holds counts only.

## 6. Data

- **Creates** (migration `s13_telemetry`): the view `turn_metrics`; the tables
  `aspiration_signals` and `curiosity_signals` (data-model.md), with the enum-array `CHECK`s.
- **Reads:** `turns`, `turn_steps`, `inbox_messages`, `outbox_messages`, `users` (role, district,
  channel), `learners`, `learner_activities`, `aspiration_signals`, `curiosity_signals`,
  `roadmaps`, `corpus_chunks` (count).
- **Writes:** `aspiration_signals`, `curiosity_signals`, `turn_steps` (the `EXTRACT_SIGNALS` row).
- Indexes: `aspiration_signals (learner_id)`, `curiosity_signals (learner_id)`; `turns (started_at)` (from s04).

## 7. Configuration

`SESSION_SIGNING_KEY`, `SESSION_SIGNING_KEY_PREVIOUS`, `MODEL_TEXT`, `TIMEOUT_EXTRACT_SIGNALS_S`,
`DAILY_COST_CAP_USD`, `PUBLIC_BASE_URL` (builds dashboard links), `DASHBOARD_LINK_TTL_S` (900),
`DASHBOARD_COOKIE_TTL_S` (7200), `K_ANONYMITY_FLOOR` (5).

## 8. Failure modes

| Failure | Effect | Recorded |
|---|---|---|
| Signal extraction fails or returns invalid output twice | None for the user; that turn has no signal | `EXTRACT_SIGNALS` FAILED |
| Task retried after signals were written | Duplicate prevented by `UNIQUE (turn_id)` | — |
| User deleted before the task ran | Skipped | `SKIPPED`, `user_gone` |
| Expired, tampered or wrong-purpose dashboard token | `401` page with how to get a new link | log `dashboard_link_rejected` (reason code, no token) |
| Cohort under 5 learners | "Not enough learners yet" | — |
| Aggregate query error | `/dashboard` → 503 page; `/status` shows what it could | error log |
| A student or parent sends "dashboard" | Normal routing; no link minted | — |

## 9. Tests

**Unit:**
- `test_aspiration_specificity_zero_requires_no_fields`; `test_specificity_two_requires_a_field`; `test_signals_reject_duplicates`
- `test_curiosity_engagement_zero_cannot_have_child_question`; `test_curiosity_engagement_two_requires_a_domain`
- `test_signals_task_for` over the §4.2 table (parametrised: student mentor → aspiration; parent report → curiosity; parent offer only → none; teacher, crisis, onboarding, fixed, nudge → none)
- `test_signal_extraction_failure_does_not_touch_reply`
- `test_curiosity_prompt_receives_report_in_user_slot_only`
- `test_breadth_excludes_other`; `test_curiosity_breadth_counts_distinct_domains`
- `test_slope_none_for_single_session`; `test_slope_known_series` (`[0,1,2,3]` → 1.0; `[3,3,3]` → 0.0; `[4,0]` → −4.0)
- `test_done_rate_none_when_nothing_offered`; `test_child_question_rate_none_without_reports`
- `test_session_split_gap_exactly_6h_same_session`; `test_session_split_6h_plus_1s_new_session`
- `test_suppress_small_hides_counts_below_floor`, boundary 4 → hidden, 5 → shown
- `test_dashboard_contains_no_user_hash_nickname_or_text` (render from fixture data; assert no 64-hex string, none of the fixture user texts and none of the fixture nicknames appear)
- `test_dashboard_token_roundtrip_via_codec`; `test_tampered_payload_rejected`; `test_tampered_signature_rejected`;
  `test_expired_rejected` (exp == now → rejected; now − 1 s → accepted, with the injected clock);
  `test_session_purpose_token_not_accepted_as_dash`; `test_unknown_claims_version_rejected`
- `test_dashboard_link_only_for_teachers` (router-level, with S5)
- `test_teacher_scope_is_exact_district_and_hides_young_learners`
- `test_status_hides_cost_and_crisis_without_admin_scope`
- `test_nudge_turns_excluded_from_latency_percentiles`

**Property (hypothesis), the invariants from CLAUDE.md §3:**
- Breadth (both kinds) is monotonic non-decreasing: for any point sequence and any prefix,
  `breadth(prefix) ≤ breadth(full)`.
- Order invariance: for points sharing a timestamp, any permutation gives identical session
  contents (as multisets), breadth, per-session max and slope.
- Bounds: `0 ≤ breadth ≤ len(AspirationField) − 1`; `0 ≤ curiosity_breadth ≤ len(CuriosityDomain)`;
  per-session specificity in 0..4 and engagement in 0..3; `|specificity slope| ≤ 4` and
  `|engagement slope| ≤ 3`; the slope of a constant series is 0.
- Sessions partition the points: their concatenation equals the sorted input, and within a
  session every consecutive gap is ≤ 6 h.
- `done_rate` and `child_question_rate` are in [0, 1] or None.
- Codec: `verify(issue(p, payload, ttl), p).payload == payload` for generated payloads with a
  future expiry; flipping any single character of the token, or verifying with a different
  purpose, gives `None`.

**Negative:** `/dashboard` without a token or cookie → 401; with an `admin` token → all-learners
scope; `?t=` with malformed base64 → 401 (not 500); `/dashboard/data.json` obeys the same scope and suppression.

**Integration (`-m integration`):**
- `test_turn_metrics_view_user_latency` (seed inbox, turn and outbox rows with known times).
- `test_step_latency_percentiles_sql` (known durations → known p50/p95).
- `test_cost_today_uses_ist_day_boundary` (rows at 18:29 and 18:31 UTC on either side of IST midnight), and the `channel='web'` filter.
- `test_signals_insert_is_idempotent_per_turn` (both tables).
- `test_district_scope_only_includes_matching_students`.
- `test_user_deletion_removes_learner_signals_and_counts_drop`.

## 10. Exit check

1. After a day of real testing, `/status` shows p50/p95 per step and user latency from real turns,
   plus journey counts. The admin link additionally shows cost today against the cap.
2. A test teacher sends "dashboard" on WhatsApp, gets a link, and opens it on a phone. It shows
   their district's student trajectory charts, or "Not enough learners yet" for fewer than 5.
   Opening it after 15 minutes gives 401.
3. A student who moved from "science homework" → "plants job?" → "agriculture scientist" (golden
   multiturn-003) has aspiration signals at specificity 0 → 1 → 3, visible (in aggregate, admin
   scope) as a rising slope.
4. A parent who reported "Munni ne poocha raat ko parchhai kahan jaati hai" has a curiosity signal
   with `earth_sky`, engagement 3 and `child_asked_question = true`, counted in the young-learner section.
5. Viewing page source shows no hashes, phone numbers, nicknames or message text.
6. Verification loop green, including integration tests.

## 11. Open questions

1. ~~Classroom codes~~ **Resolved by B9:** trimmed; teacher scope is the district (§4.8).
2. ~~Public `/status`~~ **Resolved by B8:** latency, success and journey counts are public; cost
   and crisis counts are admin-only.
3. **Signals for teacher turns:** excluded. Teacher-side metrics (exposure bridges per teacher,
   chapters covered) could be a later addition.
4. **Young-learner dashboard for anyone but admin:** parents aren't asked a district, so only the
   admin scope shows this section. Should anganwadi workers or teachers ever see aggregates of
   young learners near them? That would need a coarse location for parents, which s08 deliberately
   doesn't collect. Open.

## 12. Contract changes (resolved 2026-10-25)

| Request (v1) | Resolution |
|---|---|
| `AspirationField`, `ConstraintKind`, `Sentiment`; `Route.DASHBOARD_LINK` | Applied (contracts §1). |
| `AspirationSignals` fields; `DashboardClaims` | Applied (contracts §2.7); `DashboardClaims` loses `classroom_id` (B9). |
| `LinkInvalid` → 401 | Applied (contracts §4). |
| Settings `PUBLIC_BASE_URL`, `DASHBOARD_LINK_TTL_S`, `DASHBOARD_COOKIE_TTL_S`, `K_ANONYMITY_FLOOR` | Applied (contracts §7). |
| `aspiration_signals` enum CHECKs; `turn_metrics` view | Applied (data-model). `aspiration_signals` is keyed by `learner_id` (B12). |
| `classrooms` table, `users.classroom_id` | **Rejected** (B9): classroom codes trimmed. |
| `SESSION_GAP` shared constant; `TurnContext.is_session_start` | Applied (contracts §2.2). |
| (new) `CuriositySignals`, `curiosity_signals` table, `CuriosityDomain` | Already in contracts and data-model (B12); defined here. |
| (new) shared `SignedTokenCodec` with `issue(purpose, payload, ttl_s)` / `verify(token, purpose)` | Used here; s14 owns the implementation in `app/core/sessions.py`. Not listed in contracts.md (see the final report). |

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-25 | v1 written | telemetry design | owner |
| 2026-10-25 | Classroom codes moved to Deferred, teacher scope = district; tokens via the shared `SignedTokenCodec` (purpose `"dash"`); aspiration signals keyed by learner; `CuriositySignals` and young-learner metrics added; `ExtractSignals` as a post-turn task; cost-today query takes a channel filter for s14 | A4, B2, B8, B9, B12 and the consolidated contracts | owner |
| 2026-10-26 | Image steps (`FETCH_IMAGE`, `ANALYZE_IMAGE`, `MAKE_CARD`) on `/status`; journey counts add photos received/rejected and cards sent; young-learner section adds photos-with-counts and cards sent (forwarding isn't measurable); cost includes image generation and segmentation | Owner decisions C6, C7 | owner |
| 2026-10-26 | Curiosity signals also from `CHILD_TALK` turns and curiosity-moment turns (`child_asked_question`); young-learner metrics add child-talk sessions, questions per session and domains; aggregate only, summaries counted never shown | Owner decisions C11–C13 | owner |
| 2026-10-27 | **Curiosity signals built (§4.2, §4.4, §4.5).** The extraction runs on Muse Spark Open (C9) with Spark 1.3 as the fallback, `max_output_tokens` 800 (at 120-300, Open's answers were cut off and every call fell back; live check: 6/6 on Open, 1.5-3.2 s, each matching the rubric). Post-turn tasks run in the background after delivery (the dispatcher waits for them on shutdown), not after finalize, so the reply never waits for them. Layers mark a turn with `LayerResult.curiosity` (report, child's words, relayed question); `ExtractSignals` carries the source and the child's age; a relayed question always counts as the child asking. `curiosity_signals` gains `source`. Trajectory math is `CuriosityTrajectory` in `app/domain/rules/curiosity_trajectory.py`; the dashboard that shows it is built with S14 | Build choices | pending owner review |
