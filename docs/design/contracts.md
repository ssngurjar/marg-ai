# Contracts — shared vocabulary

> Hackathon build: see [mvp-scope.md](mvp-scope.md) for which parts are built now. Contracts
> for Phase 2 parts stay defined here so the MVP code grows into them without renaming.

**This is the single source of truth for names.** Enums, domain models, ports, errors and settings
are defined here once. Step docs reference them and never redefine them. Changing a contract
needs the owner's approval (docs/design/README.md, "How to use them" §3). Make the change here,
in the same commit as the code, and add a line to the Decisions log at the end of this file.

Shapes are given as Python signatures. Field lists are the minimum; a step may add fields once
the change is approved. All models are Pydantic v2 `BaseModel`s with `model_config =
ConfigDict(frozen=True, extra="forbid")` **except** the WhatsApp webhook models in
`app/channels/whatsapp/payloads.py`, which use `extra="ignore"`. They're external input, and Meta
adds fields without notice (s03 §4.4). All datetimes are timezone-aware UTC. Money is `Decimal`.

---

## 1. Enums — `app/domain/enums.py`

All are `StrEnum`. Values are lowercase snake_case and are persisted, so **never rename a value**.
Add a new one and migrate instead.

```python
class Channel(StrEnum):            WHATSAPP = "whatsapp"; WEB = "web"
class MessageKind(StrEnum):        TEXT; AUDIO; IMAGE; INTERACTIVE; UNSUPPORTED   # IMAGE: s10b activity photos (C7)
class Language(StrEnum):           HINDI = "hindi"; HINGLISH = "hinglish"; ENGLISH = "english"
class Role(StrEnum):               STUDENT; TEACHER; PARENT
class ConversationState(StrEnum):  NEW; AWAITING_CONSENT; AWAITING_ROLE; AWAITING_GUARDIAN;
                                   AWAITING_CHILD; AWAITING_PROFILE; ACTIVE; AWAITING_DELETION_CONFIRM
class Mode(StrEnum):               EXPOSURE; MENTOR; ROADMAP; JOURNEY
class Route(StrEnum):              ONBOARDING; EXPOSURE; MENTOR; ROADMAP; JOURNEY; CRISIS; REFUSE;
                                   OFF_TOPIC; DATA_DELETION; REPEAT_PLEASE; DASHBOARD_LINK; NUDGE; KHOJ_CARD; CHILD_TALK
class StepName(StrEnum):           FETCH_MEDIA; TRANSCRIBE; SAFETY_IN; ROUTE; GENERATE; TRANSLATE;
                                   SAFETY_OUT; SYNTHESIZE; ENQUEUE_REPLY; EXTRACT_SIGNALS; UPDATE_MEMORY;
                                   FETCH_IMAGE; ANALYZE_IMAGE; MAKE_CARD
class StepOutcome(StrEnum):        OK; DEGRADED; FAILED; SKIPPED
class FailureKind(StrEnum):        TIMEOUT; RATE_LIMITED; UNAVAILABLE; INVALID_RESPONSE;
                                   EMPTY_INPUT; UNSUPPORTED_INPUT; BUDGET_EXCEEDED; INTERNAL
class InboxStatus(StrEnum):        PENDING; PROCESSING; DONE; FAILED
class TurnStatus(StrEnum):         PROCESSING; COMPLETED; FAILED
class OutboxStatus(StrEnum):       PENDING; SENDING; SENT; DELIVERED; READ; FAILED
class PartKind(StrEnum):           TEXT; AUDIO; IMAGE; INTERACTIVE; TEMPLATE
class SafetyDecision(StrEnum):     ALLOW; BLOCK; CRISIS
class SafetyCategory(StrEnum):     # Llama Guard 4 / MLCommons hazard taxonomy (format confirmed in S2)
    VIOLENT_CRIMES = "s1"; NON_VIOLENT_CRIMES = "s2"; SEX_CRIMES = "s3"; CHILD_EXPLOITATION = "s4"
    DEFAMATION = "s5"; SPECIALIZED_ADVICE = "s6"; PRIVACY = "s7"; INTELLECTUAL_PROPERTY = "s8"
    INDISCRIMINATE_WEAPONS = "s9"; HATE = "s10"; SELF_HARM = "s11"; SEXUAL_CONTENT = "s12"
    ELECTIONS = "s13"; CODE_INTERPRETER_ABUSE = "s14"
    # domain policy categories (s07, s10b), not from Llama Guard:
    MINOR_PII = "d1"; GUARANTEE_PROMISE = "d2"; ROMANTIC = "d3"; MEDICAL = "d4"
    ABUSE_DISCLOSURE = "d5"; PROMPT_LEAK = "d6"; CHILD_PHYSICAL_HAZARD = "d7"
    CHILD_MANIPULATION = "d8"     # secrecy, exclusivity or attachment language toward a child (output)
class FixedReplyKind(StrEnum):     CRISIS; HOLDING; REPEAT_PLEASE; TRY_AGAIN_LATER; TOO_LONG;
                                   UNSUPPORTED_MEDIA; REFUSE; ONBOARDING; CONSENT_DECLINED;
                                   DATA_DELETED; ASK_CHAPTER; NUDGE; PHOTO_HAS_PERSON; PHOTO_NOT_NEEDED;
                                   CHILD_TALK_NOT_ENABLED; CHILD_TALK_COOLDOWN; CHILD_SESSION_END
class MediaPurpose(StrEnum):       INBOUND_AUDIO; REPLY_AUDIO; KHOJ_CARD
class EmbedPurpose(StrEnum):       QUERY; PASSAGE
class RoadmapStatus(StrEnum):      ACTIVE; COMPLETED; ABANDONED
class RoadmapStepStatus(StrEnum):  TODO; DONE; SKIPPED
class ConsentEventKind(StrEnum):   GRANTED; GUARDIAN_CONFIRMED; CHILD_PROFILE_CONSENT; CHILD_TALK_CONSENT; REVOKED; DELETION_REQUESTED
class LearnerRelation(StrEnum):    SELF; PARENT                  # how the user relates to the learner
class ActivityStatus(StrEnum):     OFFERED; DONE; SKIPPED
class AspirationField(StrEnum):    MEDICINE; HEALTH_ALLIED; ENGINEERING; TECHNOLOGY_COMPUTING;
                                   SCIENCE_RESEARCH; SPACE_AEROSPACE; AGRICULTURE; PUBLIC_POLICY;
                                   CIVIL_SERVICES; DEFENCE_POLICE; LAW; TEACHING; SPORTS; ARTS_DESIGN;
                                   MEDIA_COMMUNICATION; ENTREPRENEURSHIP; FINANCE_COMMERCE;
                                   SKILLED_TRADES; OTHER
class ConstraintKind(StrEnum):     MONEY; DISTANCE; FAMILY; GENDER_NORMS; LANGUAGE; TIME; MARKS;
                                   INFORMATION; DEVICE
class CuriosityDomain(StrEnum):    NATURE_LIVING; EARTH_SKY; NUMBERS_PATTERNS; WORDS_STORIES;
                                   MAKING_BUILDING; MOVEMENT_BODY; ART_MUSIC; PEOPLE_FEELINGS;
                                   EVERYDAY_WORK
class Sentiment(StrEnum):          POSITIVE; NEUTRAL; NEGATIVE
class Speaker(StrEnum):            GUIDE; LEARNER                 # who is talking this turn (C13 child talk)
class ChildSessionEndReason(StrEnum): TURN_LIMIT; TIME_LIMIT; CHILD_ENDED; CRISIS; EXPIRED
```

`Route` → owner of the `GENERATE` work: `ONBOARDING`, `DATA_DELETION` → s08; `EXPOSURE` → s10;
`JOURNEY`, `CHILD_TALK` → s10b; `MENTOR`, `ROADMAP`, `OFF_TOPIC` → s12; `CRISIS`, `REFUSE` → s07 (fixed text);
`REPEAT_PLEASE` → s06 (fixed text); `DASHBOARD_LINK` → s13; `NUDGE`, `KHOJ_CARD` → s10b. A `NUDGE` turn is
created by the scheduler, never by inbound messages, and sends a fixed, Meta-approved template.

Fixed-reply variants (`FixedReplyVariant`, `app/pipeline/fixed_reply_service.py`): `DEFAULT` for every kind,
plus `HARMFUL`, `PRIVACY`, `MEDICAL`, `GENERAL`, `GENERIC` (for `REFUSE`) and `SELF_HARM`, `ABUSE`
(for `CRISIS`, which `app/safety/crisis.py` also calls `CrisisVariant`). Crisis and refuse texts are
keyed additionally by `Speaker`: the `LEARNER` versions use a child's words (s10b §4.16).

---

## 2. Domain models

### 2.1 Identity and messages — `app/domain/models/`

```python
UserHash = NewType("UserHash", str)          # 64 lowercase hex chars
TurnId = NewType("TurnId", UUID)
LearnerId = NewType("LearnerId", UUID)

class MediaRef(BaseModel):
    channel: Channel
    provider_media_id: str | None            # WhatsApp media id
    blob_id: UUID | None                     # media_blobs row (web uploads)
    mime_type: str
    # exactly one of provider_media_id / blob_id is set (model validator)

class InboundMessage(BaseModel):
    channel: Channel
    external_id: str                         # wamid.* or web-generated uuid
    user_hash: UserHash
    kind: MessageKind
    text: str | None                         # TEXT, or the button title for INTERACTIVE
    media: MediaRef | None                   # AUDIO
    interactive_reply_id: str | None         # INTERACTIVE (button/list id we issued, or template payload)
    provider_sent_at: datetime               # when the user sent it (provider timestamp)
    received_at: datetime                    # when we stored it

class AudioClip(BaseModel):
    data: bytes
    mime_type: str                           # "audio/ogg; codecs=opus", "audio/wav", "audio/webm", "audio/mp4"
    duration_ms: int | None

class ImageClip(BaseModel):                 # s10b photos (never persisted) and khoj cards
    data: bytes
    mime_type: str                           # "image/jpeg", "image/png", "image/webp"

class Transcript(BaseModel):
    text: str
    language: Language | None                # from domain/language.detect_register, not the provider
    confidence: float | None                 # None for Muse Voice Transcribe (no such field)
    audio_duration_ms: int
```

`app/core/types.py`: `JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]`,
used for JSON Schema objects and stripped raw payloads, so nothing needs `Any`.

### 2.2 Users, learners and conversation

```python
class UserProfile(BaseModel):
    user_hash: UserHash
    channel: Channel
    state: ConversationState
    role: Role | None
    grade: int | None                        # 1..12; students and teachers
    subject: str | None                      # teachers
    district: str | None                     # students and teachers; not asked of parents
    language: Language | None
    guardian_confirmed: bool                 # students
    consented_at: datetime | None
    last_inbound_at: datetime | None         # WhatsApp 24h window
    pending_question: str | None             # s08: a question asked before onboarding finished

class Learner(BaseModel):                    # the child or student whose journey we track (s10b)
    id: LearnerId
    relation: LearnerRelation                # SELF for a student; PARENT for a parent's child
    nickname: str | None                     # ≤ 20 chars, optional, never a full name
    birth_year: int                          # validated: ≥ current_year − 19, ≤ current_year − 2
    # derived in app/domain/stages.py: age_band(birth_year, today) and nep_stage(...)

class Exchange(BaseModel):                   # one past turn, for context windows
    user_text: str
    reply_text: str
    route: Route
    at: datetime

class ProfileMemory(BaseModel):              # s12
    summary: str                             # ≤ 600 chars, rolling
    ambitions: list[str]
    constraints: list[str]
    updated_at: datetime

class TurnContext(BaseModel):                # built by the worker (s04), read by every step
    turn_id: TurnId
    profile: UserProfile
    learners: list[Learner]                  # a parent's children (≤ 3) or the student themself; [] for teachers
    active_learner: Learner | None           # who this turn is about; s10b chooses for parents
    messages: list[InboundMessage]           # oldest first; ≥ 1 (empty only for NUDGE turns)
    recent_exchanges: list[Exchange]         # last RECENT_EXCHANGES, oldest first
    memory: ProfileMemory | None
    active_roadmap: "Roadmap | None"
    open_activity: "OfferedActivity | None"  # s10b: the latest OFFERED activity for active_learner, < 48 h old
    speaker: Speaker                         # LEARNER only inside an open child session (C13)
    child_session: "ChildSession | None"     # the open child session for active_learner, if any
    is_session_start: bool                   # gap since the previous turn > SESSION_GAP (6 h)
```

`SESSION_GAP = timedelta(hours=6)` lives in `app/domain/rules/session_rules.py` and is the only definition of a session.

### 2.3 Turn results — `app/pipeline/step_models.py`

```python
class StepFailure(BaseModel):
    step: StepName
    kind: FailureKind
    detail: str                              # fixed vocabulary only: no user text, no phone numbers
    retryable: bool

class StepSuccess(BaseModel, Generic[OutputT]):
    step: StepName
    output: OutputT
    outcome: Literal[StepOutcome.OK, StepOutcome.DEGRADED]

StepResult = StepSuccess[OutputT] | StepFailure

class StepUsage(BaseModel):                  # attached to every turn_steps row
    provider: str | None                     # "meta_model_api", "llama_guard", "ml_sidecar", ...
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    audio_seconds: Decimal | None
    cost_usd: Decimal                        # Decimal("0") when free

class TurnOutcome(BaseModel):                # what run_turn returns to s04
    turn_id: TurnId
    route: Route
    delivery: "ReplyDelivery"                # sealed; built only from a SafeReply (s07); ≥ 1 part
    fixed_reply_kind: FixedReplyKind | None
    user_text: str | None                    # combined text → turns.user_text (s04 writes NULL for CRISIS)
    reply_text: str                          # SafeReply.text → turns.reply_text
    reply_register: Language
    prompt_versions: dict[str, str]          # prompt_id → version, every prompt used
    first_failure: StepFailure | None        # → turns.failure_step / failure_kind
    writes: list["TurnWrite"]                # state changes s04 applies atomically with the outbox
    post_turn: list["PostTurnTask"]          # work s04 runs after finalize (signals, memory)
```

**Turn status:** a turn whose pipeline ran to the end is `COMPLETED`, even when a step failed
and a fallback reply was sent (`first_failure` records it). `FAILED` means the turn itself
crashed or was abandoned (lease lost, exception, shutdown), and its inbox rows are retried.

### 2.4 State changes that commit with the reply — `app/domain/writes.py`

Layers never write to the database. They return `TurnWrite`s, and s04 applies every write in the
**same transaction** as the outbox rows, under the lease. So a reply blocked by `safety_out`, or a
turn that loses its lease, leaves no partial state.

```python
TurnWrite = Annotated[
    ProfileChange            # s08: state and profile fields, pending question, consent events
  | LearnerUpsert            # s08/s10b: create or update a learner (nickname, birth_year)
  | DeleteInboundMedia       # s06: web upload consumed
  | SaveRoadmap              # s12
  | ActivityOffered          # s10b: an activity was sent for a learner
  | ActivityReported         # s10b: the parent reported back (status, ≤ 200-char summary)
  | NudgePreference          # s10b: opt in / change time / opt out
  | MarkPurgeAfterDelivery   # s08: delete the user once this turn's last part is delivered
  | ChildTalkConsent         # s08: parent grants or revokes direct child talk (C13); field granted: bool
  | ChildSessionStart        # s10b: the child started talking
  | ChildSessionEnd,         # s10b: limit reached, child ended, crisis, or expired
  Field(discriminator="kind")]

class ProfileChange(BaseModel):
    kind: Literal["profile_change"]
    expected_state: ConversationState        # optimistic check; mismatch → LeaseLost
    new_state: ConversationState
    role: Role | None                        # None = unchanged (for every optional field below)
    grade: int | None
    subject: str | None
    district: str | None
    language: Language | None
    guardian_confirmed: bool | None
    consented_at: datetime | None
    pending_question: str | None
    clear_pending_question: bool
    consent_events: list[ConsentEventKind]
    consent_prompt_version: str | None
```

The other variants' fields are defined in their owner docs and listed here by name only.
`ApplyRoadmapProgress` (s12) is **deferred** (roadmap progress tracking is out of the MVP).

**Writes are applied in list order** inside finalize. A layer that creates something another write
refers to generates its id itself (`LearnerUpsert.learner_id` is a fresh `uuid4` for a new learner),
so a same-turn handoff, such as the first khoj after a parent's onboarding, can use the new learner
in its `TurnContext` and its `ActivityOffered` write before anything is committed.

```python
PostTurnTask = Annotated[ExtractSignals | UpdateMemory | MakeKhojCard | SendChildSessionSummary,
                         Field(discriminator="kind")]   # SendChildSessionSummary: s10b §4.16

class ExtractSignals(BaseModel):            # s13
    kind: Literal["extract_signals"]
    signal: Literal["aspiration", "curiosity"]
    turn_id: TurnId
    learner_id: LearnerId
    user_text: str                           # the student's message, or the parent's report

class UpdateMemory(BaseModel):              # s12
    kind: Literal["update_memory"]
    turn_id: TurnId
    user_text: str
    reply_text: str
```

class MakeKhojCard(BaseModel):              # s10b §4.13 (C6)
    kind: Literal["make_khoj_card"]
    turn_id: TurnId
    learner_id: LearnerId
    learner_activity_id: UUID

These run after finalize, each in its own short transaction. They never delay or change the
reply, and a failure is recorded as a `turn_steps` row only.

### 2.5 Safety and routing

```python
class SafetyVerdict(BaseModel):
    decision: SafetyDecision
    categories: list[SafetyCategory]         # empty when ALLOW
    source: Literal["llama_guard", "domain_policy", "fixed"]

class RouteDecision(BaseModel):
    route: Route
    mode_switch: Mode | None
    reason: str                              # ≤ 120 chars, fixed vocabulary; no user text
```

### 2.6 Replies — `app/domain/models/reply.py`, `app/safety/safety_gate.py`, `app/pipeline/reply_parts_builder.py`

```python
class Citation(BaseModel):
    title: str
    source_url: HttpUrl
    chunk_id: UUID

class ReplyButton(BaseModel):                # WhatsApp interactive, max 3 per message
    id: str                                  # ≤ 256 chars, namespaced: "onb:" (incl. "onb:childtalk:", "onb:add-child"),
                                             # "exp:", "rm:", "jrn:", "nudge:", "mode:", "kid:"
    title: str                               # ≤ 20 chars (WhatsApp limit)

class TemplateRef(BaseModel):                # PartKind.TEMPLATE (s10b nudges)
    name: str                                # Meta-approved template name
    language_code: str                       # e.g. "hi", "en"
    button_payloads: list[str]               # quick-reply payloads, e.g. ["jrn:today"]

class CanonicalReply(BaseModel):             # what every generate step returns
    body: str                                # MVP: the user's register (direct localisation, C3c).
                                             # Phase 2 with the s09 layer: English. Fixed text: the user's language.
    body_language: Language
    spoken_text: str | None                  # set when the layer localised directly; translate is then SKIPPED
    citations: list[Citation]
    buttons: list[ReplyButton]               # ≤ 3
    fixed_kind: FixedReplyKind | None        # set when this is fixed text (no translation, no LLM)

class LocalisedReply(BaseModel):             # s09 output; what safety_out sees
    text: str                                # for the screen; may include links and the sources block
    spoken_text: str                         # for TTS: no URLs, markdown, emoji, markers.
                                             # Devanagari script when register ∈ {HINDI, HINGLISH}
    register: Language
    citations: list[Citation]
    buttons: list[ReplyButton]

class OutboundPart(BaseModel):               # one outbox row's content
    part_no: int                             # 0-based, delivery order
    kind: PartKind
    text: str | None                         # for IMAGE: the caption
    audio_blob_id: UUID | None
    image_blob_id: UUID | None               # IMAGE only (khoj card)
    buttons: list[ReplyButton]
    template: TemplateRef | None             # TEMPLATE only
```

**Sealed types (s07 §4.2).** `SafeReply` (`app/safety/safety_gate.py`) can only be built by `SafetyGate`.
`ReplyDelivery` (`app/pipeline/reply_parts_builder.py`) can only be built by `ReplyPartsBuilder.build(SafeReply, …)`, and
holds the ordered `OutboundPart`s. `OutboxRepository.enqueue` accepts only a `ReplyDelivery`, so no
code path can queue a message that didn't pass the gate. Fixed replies pass through
`SafetyGate.clear_fixed`, which needs no classifier call.

### 2.7 Layer outputs and other named models

Each lives in its owner's module. They're listed here so names stay unique.

| Model | Module | Owner |
|---|---|---|
| `RouterOutput` | `app/pipeline/router.py` | s05 |
| `ProfileExtraction` (incl. `child_age`, `child_nickname`) | `app/layers/onboarding.py` | s08 |
| `TranslationOutput`, `RegisterChoice` | `app/layers/translation.py` | s09 |
| `ExposureBridge`, `ExposureField` | `app/layers/exposure.py` | s10 |
| `Activity`, `ActivityPersonalisation`, `ParentReflection`, `OfferedActivity` | `app/layers/journey.py`, `app/domain/activities.py` | s10b |
| `RetrievalQuery`, `RetrievedChunk`, `RetrievalResult` | `app/rag/` | s11 |
| `MentorAnswer`, `MentorClaim`, `OffTopicReply`, `LayerResult` | `app/layers/` | s12 |
| `RoadmapDraft`, `RoadmapDraftStep`, `ResolvedRoadmapStep`, `Roadmap`, `RoadmapStep` | `app/layers/roadmap.py`, `app/domain/models/` | s12 |
| `MemoryUpdate` | `app/layers/memory.py` | s12 |
| `MinorPolicyCheck` | `app/safety/policy.py` | s07 |
| `AspirationSignals`, `CuriositySignals` | `app/domain/aspiration.py` | s13 |
| `KhojCardText`, `PhotoFindings`, `CuriosityMoment`, `ChildReply`, `ChildSession` | `app/layers/journey.py`, `app/domain/models/` | s10b |
| `DashboardClaims` | `app/telemetry/links.py` | s13 |
| `GoldenCase`, `GoldenTurn`, `GoldenProfile`, `GoldenLearner`, `TurnExpectation`, `TurnRecord`, `CheckResult`, `JudgeItem`, `JudgeScore`, `Scorecard` | `app/evals/` | s15 |

---

## 3. Ports — `app/providers/ports.py` (and the protocols named below)

`Protocol`s only. `pipeline/` and `layers/` depend on these, never on adapters. Every provider
method is async, gets its timeout from settings through the adapter's constructor, and raises
only the `ProviderError` subclasses in §4.

```python
class RenderedPrompt(BaseModel):
    prompt_id: str                           # "mentor", "exposure", ...
    prompt_version: str                      # from the template frontmatter
    system: str
    user: str                                # user content only inside registry-wrapped slots

class GenerationRequest(BaseModel, Generic[OutputT]):
    prompt: RenderedPrompt
    output_type: type[OutputT]               # strict JSON schema (s05 §4.1): no defaults, all required
    model: str                               # from settings, never a literal in a layer
    reasoning_effort: Literal["minimal", "low", "medium", "high"]
    max_output_tokens: int                   # includes reasoning tokens, which bill at the output rate
    semantic_check: Callable[[OutputT], list[str]] | None   # non-empty list → one repair retry (s05, s09)

class GenerationResult(BaseModel, Generic[OutputT]):
    output: OutputT
    usage: StepUsage
    latency_ms: int

class LanguageModel(Protocol):
    async def generate(self, request: GenerationRequest[OutputT]) -> GenerationResult[OutputT]: ...

class TranscriptionHints(BaseModel):
    expected_languages: list[Language]
    keywords: list[str]                      # exam and scheme names for biasing

class Transcriber(Protocol):
    async def transcribe(self, clip: AudioClip, hints: TranscriptionHints) -> tuple[Transcript, StepUsage]: ...

class Synthesizer(Protocol):
    async def synthesize(self, text: str, language: Language) -> tuple[AudioClip, StepUsage]: ...

class SafetyRequest(BaseModel):
    speaker: Literal["user", "assistant"]
    text: str
    prior_user_text: str | None              # required for assistant checks
    image: ImageClip | None = None           # Llama Guard 4 is multimodal: photos in, khoj cards out (C6, C7)

class SafetyClassifier(Protocol):
    async def classify(self, request: SafetyRequest) -> tuple[SafetyVerdict, StepUsage]: ...

class Embedder(Protocol):
    dimensions: int
    async def embed(self, texts: Sequence[str], purpose: EmbedPurpose) -> list[list[float]]: ...

class MediaFetcher(Protocol):               # WhatsApp media download or web media_blobs read
    async def fetch(self, ref: MediaRef) -> AudioClip: ...
    async def fetch_image(self, ref: MediaRef) -> ImageClip: ...   # photos: memory only, never persisted

class ReplyAudioStore(Protocol):            # s06: saves reply audio after safety_out passes
    async def save(self, user_hash: UserHash, clip: AudioClip) -> UUID: ...

class ChannelAddress(BaseModel):            # decrypted only inside the sender, never logged
    channel: Channel
    address: SecretStr                       # wa_id digits for WhatsApp; user_hash for web

class DeliveryReceipt(BaseModel):
    provider_message_id: str | None          # wamid for WhatsApp; None for web
    sent_at: datetime

class ChannelSender(Protocol):
    channel: Channel
    async def send(self, part: OutboundPart, recipient: ChannelAddress,
                   audio: AudioClip | None = None, image: ImageClip | None = None) -> DeliveryReceipt: ...
    async def acknowledge(self, external_id: str) -> None: ...   # WhatsApp: read + typing; web: no-op

class StepRecorder(Protocol):               # implemented by s04; each call is its own transaction
    async def record(self, *, turn_id: TurnId, step: StepName, outcome: StepOutcome,
                     started_at: datetime, duration_ms: int, usage: StepUsage | None,
                     failure: StepFailure | None, detail: str | None,
                     decision: SafetyDecision | None = None) -> None: ...   # safety rows → turn_steps.decision
    async def set_turn_text(self, turn_id: TurnId, user_text: str) -> None: ...
    async def set_turn_route(self, turn_id: TurnId, route: Route) -> None: ...

class TurnObserver(Protocol):               # s15 evals capture; production passes NullTurnObserver
    async def on_step(self, turn_id: TurnId, step: StepName, result: StepSuccess[object] | StepFailure,
                      usage: StepUsage | None, duration_ms: int) -> None: ...

class ImageGenerator(Protocol):            # Muse Image (s10b khoj card, C6)
    async def generate(self, prompt: RenderedPrompt, size: Literal["1024x1024"]) -> tuple[ImageClip, StepUsage]: ...

class ObjectCount(BaseModel):
    phrase: str                              # the noun phrase asked for, e.g. "leaf"
    count: int

class ImageSegmenter(Protocol):             # SAM 3.1 (s10b activity photos, C7)
    async def count(self, image: ImageClip, phrases: Sequence[str]) -> tuple[list[ObjectCount], StepUsage]: ...

class ActivitySource(Protocol):             # s10b: catalogue now, guarded generation later
    async def candidates(self, learner: Learner, today: date, recent_ids: Sequence[str]) -> list["Activity"]: ...

```

**Clock** (`app/core/clock.py`, not `ports.py`: `api` and `core` need it and may not import
`providers`; `SystemClock` is the only `datetime.now` in the app):

```python
class Clock(Protocol):
    def now(self) -> datetime: ...           # aware UTC
```

**Signed tokens** (`app/core/sessions.py`, owned by s14, also used by s13), stdlib only:

```python
class VerifiedToken(BaseModel):
    payload: dict[str, JsonValue]
    issued_at: datetime
    expires_at: datetime
    needs_refresh: bool                      # older than the refresh age, or signed with the previous key

class SignedTokenCodec:
    def __init__(self, key: SecretStr, previous_key: SecretStr | None, clock: Clock) -> None: ...
    def issue(self, purpose: str, payload: Mapping[str, JsonValue], ttl_s: int) -> str: ...
    def verify(self, token: str, purpose: str) -> VerifiedToken | None: ...
```

HMAC-SHA256 over `"<purpose>." + body`, so a token minted for one purpose never verifies for
another. Purposes: `"demo_session"` (s14 web cookie, payload `{"sid": …}`) and `"dash"` (s13
dashboard links, payload `DashboardClaims`).

**Orchestrator entry point** (s05 implements, s04 calls):
`async def run_turn(ctx: TurnContext, recorder: StepRecorder, observer: TurnObserver) -> TurnOutcome`.
**Single-turn entry point** (s04 implements, the worker and s15 evals call):
`async def process_user_turn(user_hash: UserHash, observer: TurnObserver = NullTurnObserver()) -> TurnId | None`.

Test fakes for every port live in `tests/fakes/` and are the only way unit tests satisfy these.

---

## 4. Errors — `app/core/errors.py`

Every exception raised by our code is a `MargError`. Each carries a message naming *what*
failed (provider, step, table, field), never user content.

```
MargError
├── ConfigError                     settings missing or invalid at startup
├── ProviderError                   (provider: str, retryable: bool)
│   ├── ProviderTimeout             retryable
│   ├── ProviderRateLimited         retryable; carries retry_after: float | None
│   ├── ProviderUnavailable         5xx / connection failure; retryable
│   ├── ProviderRejected            4xx other than 429; not retryable (bad request, auth)
│   └── ProviderResponseInvalid     unparseable or schema-invalid response; retryable once
├── SafetyUnavailable               safety classifier failed after retries → fail closed
├── MediaError
│   ├── MediaTooLarge               → UNSUPPORTED_INPUT
│   ├── MediaUnsupported            → UNSUPPORTED_INPUT
│   ├── TranscodeFailed             → UNSUPPORTED_INPUT (TIMEOUT when ffmpeg timed out)
│   └── TtsTextInvalid              → INVALID_RESPONSE (text-only reply)
├── ChannelError
│   ├── SignatureInvalid            → 401
│   ├── PayloadInvalid              → 200 + logged (WhatsApp) / 422 (web)
│   ├── InvalidAddressCiphertext    decrypt failed; outbox part fails
│   └── DeliveryFailed              outbox send failed after retries
├── DomainError
│   ├── InvalidTransition           conversation state machine
│   └── InvalidProfileValue         e.g. grade 13, birth year out of range
├── StoreError
│   ├── LeaseLost                   another worker owns the user, or expected_state changed; abandon without writing
│   └── NotFound
├── CorpusValidationError           corpus / curriculum / activity catalogue file invalid (startup or ingest)
├── GoldenCaseInvalid               evals file invalid
├── LinkInvalid                     dashboard token rejected → 401
├── BudgetExceeded                  daily cost cap reached (demo, search grounding)
└── RateLimited                     our own limits (demo) → 429
```

Mapping to `FailureKind` (used to build `StepFailure`): `ProviderTimeout→TIMEOUT`,
`ProviderRateLimited→RATE_LIMITED`, `ProviderUnavailable→UNAVAILABLE`, `ProviderRejected→INTERNAL`,
`ProviderResponseInvalid→INVALID_RESPONSE`, `BudgetExceeded→BUDGET_EXCEEDED`, `MediaError` as listed above.

---

## 5. Retry policy — `app/providers/http.py`

One deadline-aware `RetryPolicy`, used by every adapter. No ad-hoc loops, no `tenacity`.

| Setting | Default |
|---|---|
| attempts (including the first) | 3 |
| backoff | exponential, base 0.5 s, factor 2, full jitter, capped at 4 s |
| `Retry-After` | honoured when present, if it's within the step's remaining time budget |
| retried | `ProviderTimeout`, `ProviderRateLimited`, `ProviderUnavailable`; `ProviderResponseInvalid` once |
| never retried | `ProviderRejected` |

No retry is attempted if it can't finish before the step's deadline (s05 §4.5).

---

## 6. Fixed replies — `app/pipeline/fixed_reply_service.py`, `app/safety/crisis.py`, `app/layers/onboarding_copy.py`

Fixed replies are code constants keyed by `(FixedReplyKind, FixedReplyVariant, Language)` (or
`CopyKey` for onboarding), each with a `version`. They're never generated, never translated, and
pass `safety_out` through `SafetyGate.clear_fixed`. `CRISIS` texts and helpline numbers are copied
from official sources ([corpus/SOURCES.md](../../corpus/SOURCES.md), safety section), each with
`source_url` and `retrieved_on`. Every key must exist in every language, which a startup check
and a unit test enforce. When the user's language is unknown, the Hinglish version is used.

---

## 7. Settings — `app/core/config.py`

`pydantic-settings`, read from the environment (and `.env` locally). Startup fails with
`ConfigError` naming every missing or invalid setting (names only, never values). Secrets are `SecretStr`.

**Core and identity**

| Setting | Type | Default |
|---|---|---|
| `ENVIRONMENT` | `Literal["local","test","staging","prod"]` | `local` |
| `DATABASE_URL` | `SecretStr` | — |
| `PUBLIC_BASE_URL` | `HttpUrl` | — |
| `USER_HASH_SALT` | `SecretStr` (≥ 32 bytes hex) | — |
| `ADDRESS_ENCRYPTION_KEY` | `SecretStr` (32 bytes, base64) | — |
| `SESSION_SIGNING_KEY` / `SESSION_SIGNING_KEY_PREVIOUS` | `SecretStr` / `SecretStr \| None` | — / None |
| `LOG_LEVEL` | `str` | `INFO` |

**Models and providers**

| Setting | Type | Default |
|---|---|---|
| `MODEL_API_BASE_URL` | `HttpUrl` | `https://api.meta.ai/v1` |
| `MODEL_API_KEY` | `SecretStr` | — |
| `MODEL_TEXT` / `MODEL_AUDIO` / `MODEL_JUDGE` | `str` | `muse-spark-1.3` / `muse-spark-1.2` / `muse-spark-1.3` |
| `MODEL_STT` | `str` | `muse-voice-transcribe-1.0` |
| `OPEN_MODEL_BASE_URL` / `OPEN_MODEL_API_KEY` / `OPEN_MODEL` | `HttpUrl` / `SecretStr` / `str` | Baseten / — / `meta-models/muse-spark-open-1026` (C9) |
| `OPEN_MODEL_ROUTES` | `frozenset[str]` | `{"parent_reflection", "curiosity_extract"}`: prompt ids served by Muse Spark Open; any failure falls back to `MODEL_TEXT` |
| `SAFETY_BASE_URL` / `SAFETY_API_KEY` / `SAFETY_MODEL` | `HttpUrl` / `SecretStr` / `str` | host decided in S2 |
| `SAFETY_POLICY_MODEL_ENABLED` | `bool` | `true` |
| `SIDECAR_BASE_URL` / `SIDECAR_TOKEN` | `HttpUrl` / `SecretStr` | — |
| `STT_FALLBACK_ENABLED` | `bool` | `false` |
| `SEARCH_GROUNDING_ENABLED` | `bool` | `false` (stays off for the MVP) |
| `QUERY_REWRITE_ENABLED` | `bool` | `false` (on only if the S11 retrieval eval shows ≥ +0.05 recall@5) |
| `USER_SLOT_MAX_CHARS` | `int` | 4000 |
| `PROMPT_CANARY` | `SecretStr` | — |

**WhatsApp**

| Setting | Type | Default |
|---|---|---|
| `WHATSAPP_GRAPH_BASE_URL` | `HttpUrl` | — (set to `https://graph.facebook.com/v26.0`; docs/decisions/0008) |
| `TIMEOUT_WHATSAPP_S` | `float` | 5.0 (one Graph API call) |
| `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_APP_SECRET` / `WHATSAPP_VERIFY_TOKEN` | `SecretStr` | — |
| `WHATSAPP_PHONE_NUMBER_ID` | `str` | — |
| `WEBHOOK_MAX_BODY_BYTES` | `int` | 5_000_000 |
| `CHANNEL_SINK_ENABLED` | `bool` | `false`; refused when `ENVIRONMENT=prod` (s16 load tests) |

**Turn engine (s04, s05)**

| Setting | Default | | Setting | Default |
|---|---|---|---|---|
| `TURN_BUDGET_S` | 25 | | `LEASE_DURATION_S` | 60 (startup check: ≥ 2 × `TURN_BUDGET_S`) |
| `TURN_DEBOUNCE_MS` | 1000 | | `WORKER_CONCURRENCY` | 8 |
| `MAX_MESSAGES_PER_TURN` | 5 | | `MAX_TURN_ATTEMPTS` | 3 |
| `STALE_MESSAGE_HOURS` | 23 | | `RECENT_EXCHANGES` | 6 |
| `OUTBOX_CONCURRENCY` | 4 | | `OUTBOX_MAX_ATTEMPTS` | 5 |
| `OUTBOX_SENDING_STUCK_S` | 60 | | `POLL_INTERVAL_S` | 2 |
| `MAINTENANCE_INTERVAL_S` | 30 | | `SHUTDOWN_GRACE_S` | 20 |
| `PURGE_SWEEP_AFTER_S` | 600 | | | |

Per-step timeouts `TIMEOUT_<STEP>_S`: `FETCH_MEDIA` 5, `TRANSCRIBE` 8, `SAFETY_IN` 3, `ROUTE` 4,
`GENERATE` 12, `TRANSLATE` 8, `SAFETY_OUT` 3, `SYNTHESIZE` 8, `EXTRACT_SIGNALS` 6,
`UPDATE_MEMORY` 6, plus `TIMEOUT_EMBED_S` 5 (inside `GENERATE`).

**Voice (s06)**

`MAX_INBOUND_AUDIO_BYTES` 5_242_880 · `MIN_VOICE_NOTE_MS` 700 · `MIN_VOICED_MS` 300 ·
`MAX_VOICE_NOTE_SECONDS` 180 · `TRANSCODE_TIMEOUT_S` 5 · `STT_MAX_KEYWORDS` 100 ·
`TTS_MAX_SENTENCE_CHARS` 250 · `TTS_MAX_SPOKEN_CHARS` 1200 · `REPLY_AUDIO_FOR_TEXT_INPUT` false

**Retrieval (s11)**: `RETRIEVAL_TOP_K` 5 · `RETRIEVAL_MIN_SIMILARITY` 0.80 (calibrated in S11)

**Images (s10b, C6–C7)**: `MODEL_IMAGE` `muse-image-1.0` · `MODEL_SEGMENT` `sam-3.1` · `TTS_ENGINE` `Literal["mms","indic_parler"]` (C8) ·
`KHOJ_CARD_ENABLED` true · `PHOTO_INPUT_ENABLED` true · `MAX_INBOUND_IMAGE_BYTES` 5_242_880 ·
`TIMEOUT_FETCH_IMAGE_S` 5 · `TIMEOUT_ANALYZE_IMAGE_S` 6 · `TIMEOUT_MAKE_CARD_S` 20

**Child talk (s10b, C13)**: `CHILD_TALK_ENABLED` true · `CHILD_SESSION_MAX_TURNS` 6 ·
`CHILD_SESSION_MAX_MINUTES` 10 · `CHILD_SESSION_COOLDOWN_MINUTES` 30

**Parent journey (s10b)**: `NUDGE_TEMPLATE_NAME` (str, approved in WhatsApp Manager) ·
`NUDGE_QUIET_START` 20:00 / `NUDGE_QUIET_END` 07:00 (IST) · `NUDGE_DAILY_LIMIT` 200 (below the
250/day unverified cap) · `ACTIVITY_REPEAT_DAYS` 30

**Web demo (s14)**: `DEMO_RATE_LIMIT_PER_HOUR` 30 · `DEMO_IP_RATE_LIMIT_PER_HOUR` 90 ·
`DEMO_MAX_AUDIO_BYTES` 1_000_000 · `DEMO_SSE_MAX_S` 600 · `DEMO_SSE_MAX_CONNECTIONS` 200 ·
`DEMO_CAPTCHA_ENABLED` false · `TURNSTILE_SECRET` (`SecretStr | None`)

**Costs, telemetry, retention**: `DAILY_COST_CAP_USD` 5 (web only; IST day) ·
`DASHBOARD_LINK_TTL_S` 900 · `DASHBOARD_COOKIE_TTL_S` 7200 · `K_ANONYMITY_FLOOR` 5 ·
`RETENTION_TURN_TEXT_DAYS` 90 · `RETENTION_RAW_PAYLOAD_DAYS` 7

**Evals (s15)**: `EVAL_DATABASE_ADMIN_URL` (`SecretStr`) · `EVAL_CONCURRENCY` 4

---

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-27 | `OutputCheck.overruled: tuple[SafetyCategory, ...]` (Llama Guard codes a second opinion cleared) | s07 log: second opinion on reply flags | owner |
| 2026-10-27 | `InputCheck.guard_down` and `OutputCheck.guard_down`; `SafetyGate(classifier, policy, *, guard_timeout)`; `ReplyPolicyCheck` and the `reply_policy` prompt; settings `TIMEOUT_GUARD_S` (1.5) and `TIMEOUT_SAFETY_OUT_S` default 6 | Muse Spark as the Llama Guard backup (s07 log) | owner |
| 2026-10-27 | S8: enums `Role`, `ConsentEventKind`, `LearnerRelation`, `CopyKey`; `Learner` (`app/domain/models/learner.py`, with `child_talk_consented_at`); `UserProfile` onboarding fields; `TurnContext.learners`; `TurnWrite` variants `ProfileChange`, `LearnerUpsert`, `MarkPurgeAfterDelivery`, `ChildTalkConsent` in `app/domain/models/writes.py`; `TurnOutcome.writes`; `TurnRouter.decide(profile, user_text, interactive_ids)`; settings `WHATSAPP_DISPLAY_NUMBER`, `PURGE_SWEEP_AFTER_S` | S8 build | owner |
| 2026-10-27 | Safety on input (spike B): `SafetyGate(classifier, policy: DomainPolicy)`; `InputCheck.usage` is `StepUsage | None` (None when the phrase rules decide alone); `StepUsage.total` joins several calls into one `turn_steps` row (`provider` `llama_guard+meta_model_api`); `CrisisLexicon` in `app/domain/models/safety.py`; `MinorPolicyCheck.harm_kind`; settings `SAFETY_POLICY_MODEL_ENABLED` (s07 C16) and `TIMEOUT_SAFETY_IN_S` default 5 | S5 build, owner decisions after spike B | owner |
| 2026-10-27 | S5 additions: setting `MODEL_REASONING_EFFORT` (`ReasoningEffort` literal in `app/core/types.py`); ports `LanguageModel`, `GenerationRequest`/`GenerationResult`, `RenderedPrompt`, `SafetyClassifier`, `SafetyRequest`; `CanonicalReply`; enum `Mode`; `InboxRepository.save` returns `SaveResult(stored, users_with_new_messages)` so the webhook wakes the dispatcher for exactly those users; `StepUsage` moves to `app/domain/models/usage.py` | S5 build | pending owner review (S5) |
| 2026-10-27 | **Code organisation (CLAUDE.md §7):** one main class per module, named after it, with a role suffix; behaviour in classes (stateless rules as `@staticmethod`s); domain data in `app/domain/models/<topic>.py`, pure rules in `app/domain/rules/`, constants and reviewed copy in `app/constants/`; repositories are `*Repository`. Renames: `split_for_channel` → `MessageSplitter.split`, `build_parts` → `ReplyPartsBuilder.build`, `localise_fixed` → `FixedReplyService.localise`, `SESSION_GAP`/`is_session_start` → `SessionRules`, turn rules → `TurnBatcher`, delivery rules → `DeliveryPlanner`, WhatsApp functions → `WebhookSignatureVerifier`, `WhatsAppWebhookParser`, `GraphMessageBuilder`, `GraphErrorClassifier`; `FixedReplyVariant` moves to `app/domain/enums.py`. Module paths in step docs updated; Phase 2 modules not yet built are named by the same rule when they are. `docs/code-map.md` lists every module | Owner: code must be readable without following the router | owner |
| 2026-10-27 | Staged types: `TurnContext`, `UserProfile`, `TurnOutcome` gain fields with the step that builds them (S8: writes, learners, profile; S10b/S12/S13 their fields and `post_turn`). `LocalisedReply.register` and `SafeReply.register` are named `reply_register` (pydantic reserves `register`; matches `TurnOutcome.reply_register`). `StepRecorder`/`TurnObserver` live in `app/pipeline/step_models.py`. `RetryPolicy` takes a `RetryTiming` (attempts 3, base 0.5 s, cap 4 s). `TurnId`, `SafetyVerdict` (`app/domain/safety.py`) and S4's settings added | S4 build (s04 log) | owner (S4 review) |
| 2026-10-25 | v1 written | foundation for the step docs | owner |
| 2026-10-25 | Consolidated the step docs' requests: `TurnOutcome`, `TurnWrite`, `PostTurnTask`, sealed `SafeReply`/`ReplyDelivery`, `StepRecorder`, `TurnObserver`, `ChannelSender.acknowledge` + `audio`, `ReplyAudioStore`, `semantic_check`, new enums, errors and settings | Five step docs needed them; conflicting names unified into one | owner (defaults 1–10) |
| 2026-10-25 | Parent journey: `Role.PARENT`, `Learner`, `LearnerRelation`, `AWAITING_CHILD`, `Route.JOURNEY`/`NUDGE`, `PartKind.TEMPLATE`, `CuriosityDomain`, `ActivitySource`, `d7 CHILD_PHYSICAL_HAZARD` | Owner decision: build a person from early childhood; learner-centred data model from inception | owner |
| 2026-10-25 | `Transcript.language` derived locally, `confidence` always None for Muse Voice Transcribe | The API returns neither (s06 §4.5) | owner (defaults) |
| 2026-10-25 | `TurnObserver.on_step` carries the step result; `process_user_turn` accepts an observer; `GoldenLearner`; `SignedTokenCodec`; `ExtractSignals`/`UpdateMemory` fields; writes applied in list order | Requested by s13 and s15 forks; needed for evals to capture replies and for the first-khoj handoff | pending owner review |
| 2026-10-25 | `CanonicalReply.spoken_text`; layers write in the user's register for the MVP | Decision C3c (direct localisation) | owner |
| 2026-10-25 | Safety ordering: generation may run concurrently with `safety_in`, used only on ALLOW | Decision C3a | owner |
| 2026-10-26 | `CHILD_TALK_NOT_ENABLED`, `CHILD_TALK_COOLDOWN`, `CHILD_SESSION_END` fixed replies; `kid:` and `onb:childtalk:` button namespaces; `ChildTalkConsent.granted` | Mechanical follow-ups from the child-talk fork | owner (C13) |
| 2026-10-26 | Child talk and curiosity moments: `Route.CHILD_TALK`, `Speaker`, `TurnContext.speaker/child_session`, `ChildTalkConsent`/`ChildSessionStart`/`ChildSessionEnd` writes, `SendChildSessionSummary`, `d8 CHILD_MANIPULATION`, `CHILD_TALK_CONSENT`, child-worded crisis texts, settings | Owner decisions C11–C13 | owner |
| 2026-10-26 | `OPEN_MODEL_*` settings: Muse Spark Open on Baseten for selected prompts | Decision C9 | owner |
| 2026-10-26 | Images: `MessageKind.IMAGE`, `PartKind.IMAGE`, `ImageClip`, `ImageGenerator` (Muse Image), `ImageSegmenter` (SAM 3.1), image safety in `SafetyRequest`, `MakeKhojCard` post-turn task, `Route.KHOJ_CARD`, image steps, settings | Owner decisions C6 (khoj card) and C7 (activity photos) after reading the Official Rules (Meta tooling is 25% of the score) | owner |
| 2026-10-26 | `MediaFetcher.fetch_image`, `ChannelSender.send(image=…)`, `TTS_ENGINE` | Mechanical consequences of C6–C8, requested by the image fork | owner (C6–C8) |
| 2026-10-27 | `Clock` lives in `app/core/clock.py`; `WHATSAPP_GRAPH_BASE_URL` pinned to `v26.0`; `TIMEOUT_WHATSAPP_S` added | S3 build: layering (api may not import providers), Day-1 version pin, the Graph client's timeout | owner |
| 2026-10-25 | `StepRecorder.record` gains `decision` | Needed to fill `turn_steps.decision` (s07 writes it, s14 trace reads it); requested by s05 C9 | pending owner review |
| 2026-10-25 | Trimmed: classroom codes, roadmap progress/check-ins, query rewriting default off | Fund the parent journey within 10 days | owner |
