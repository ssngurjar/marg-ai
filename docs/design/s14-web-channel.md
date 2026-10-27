# S14 — Web channel and `/demo`

> **Hackathon build level: Exception E2. Polling until the upgrade trigger fires (mvp-scope.md §4.6).** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

> Draft v1, 2026-10-25. Reviewed and approved at the start of S14, before any code.

## 1. Purpose

Give judges, and anyone without one of our 5 WhatsApp test slots, a link where they can talk
to Marg.ai by voice or text, and **watch the pipeline work**: transcript, safety verdict, route,
sources, timings and cost per step, then the reply as text and audio.

It's a second channel on the same engine (decision A2). It has no separate code path: inbound
messages go into `inbox_messages`, the worker runs the same orchestrator, and replies go through
`outbox_messages`. Only the edges differ: how the visitor is identified, how a reply reaches them,
and the page.

## 2. Read first

- [00-overview.md](00-overview.md) §3 (life of a message: web is asynchronous too)
- [contracts.md](contracts.md): §1 `Channel.WEB`, `MediaPurpose`, `StepName`; §2.1 `InboundMessage`, `MediaRef`; §3 `ChannelSender`; §4 `RateLimited`, `BudgetExceeded`, `PayloadInvalid`; §7 `SESSION_SIGNING_KEY`, `DEMO_RATE_LIMIT_PER_HOUR`, `DAILY_COST_CAP_USD`
- [data-model.md](data-model.md): `users`, `inbox_messages`, `media_blobs`, `turns`, `turn_steps`, `outbox_messages`, `rate_limit_counters`
- [s03-whatsapp-ingress-auth.md](s03-whatsapp-ingress-auth.md) §4.5 (identity), §4.6 (inbox insert): the web ingest mirrors these
- [s04-queue-worker.md](s04-queue-worker.md) §4.6 (`StepRecorder`, `NOTIFY turn_progress`), §4.10 (outbox loop)
- s06 (audio formats and transcoding), s08 (onboarding state machine, deletion)
- [plan.md](../../plan.md) §4.7

## 3. Scope

**In**
- Visitor identity: a signed, HttpOnly session cookie (no login); web `user_hash`
- `GET /demo`, `GET /demo/session`, `POST /demo/messages`, `GET /demo/events` (SSE),
  `GET /demo/turns/{turn_id}`, `GET /demo/audio/{blob_id}`, `POST /demo/reset`
- `WebSender` (`ChannelSender` for `Channel.WEB`)
- Abuse controls: per-session and per-IP rate limits, a daily cost cap for web traffic, an optional CAPTCHA
- The static page `app/static/demo/`: chat, mic recording, and the pipeline trace panel
- Alembic migration `s14_rate_limits`

**Out**
- Onboarding logic → s08 (the same state machine; only the consent wording differs, §4.9)
- Transcoding webm/mp4 to what STT accepts → s06
- The dashboard → s13 (it reuses the cookie-signing helper)

## 4. Design

### 4.1 Flow

```
Browser                                   api                                          worker
  │ GET /demo                             │ serve index.html
  │ GET /demo/session ───────────────────▶│ no valid cookie → new session id, Set-Cookie
  │◀── {state, language} ─────────────────│ upsert users (channel=web, no address)
  │ new EventSource('/demo/events') ─────▶│ subscribe(user_hash); replay the latest turn if < 2 min old
  │ POST /demo/messages (text|audio|button) ▶│ cookie → user_hash; origin check; rate limits; cost cap
  │                                       │ media_blobs (audio) + inbox_messages; NOTIFY inbox_new
  │◀── 202 {message_id} ──────────────────│
  │                                       │                                             claim user → turn
  │◀── event: turn.started ───────────────│◀── NOTIFY turn_progress ── recorder.record ──│ steps …
  │◀── event: step (× n) ─────────────────│◀── NOTIFY turn_progress ─────────────────────│
  │                                       │                                             finalize → outbox
  │                                       │◀── NOTIFY turn_progress ── WebSender.send ───│ OutboxLoop
  │◀── event: turn.completed ─────────────│ read outbox parts + turn
  │ GET /demo/audio/{blob_id} ───────────▶│ owner + expiry check → audio bytes
```

**Why the stream is per session, not per turn.** `POST` can't return a `turn_id`: the turn
doesn't exist yet. The worker creates it when it claims the user, and with debouncing it may
combine this message with the next one (s04 §4.4). So `POST` returns the `message_id`, and one
long-lived stream per session delivers events for whichever turns that visitor's messages end up
in. `turn.started` lists the message ids it covers, so the page can match them. 00-overview.md §3
describes it this way.

### 4.2 Session cookie (visitor identity)

The cookie is a token from the shared `SignedTokenCodec` (`app/core/sessions.py`, also used by
s13's dashboard links), with purpose `"demo_session"`:

```
Cookie:  marg_session=<body>.<sig>
  body = base64url(JSON {"v": 1, "payload": {"sid": <base64url(16 random bytes)>}, "iat": <unix s>, "exp": <unix s>})
  sig  = base64url(HMAC-SHA256(SESSION_SIGNING_KEY, "demo_session." + body))
  issued with ttl_s = 2592000 (30 days)
Attributes: HttpOnly; SameSite=Lax; Path=/demo; Max-Age=2592000; Secure when ENVIRONMENT in {staging, prod}
```

- Built with stdlib `hmac`, `hashlib`, `secrets`, `base64`, `json`. No new dependency.
- The purpose is part of the signed string, so a dashboard token (purpose `"dash"`, s13)
  can never be accepted as a session cookie, and the reverse.
- Verification (`codec.verify(token, "demo_session")`): split on the last `.`, recompute the
  signature with the current key (then the previous key), `hmac.compare_digest`, require `v == 1`,
  reject `iat` in the future (> 5 min of clock skew) or `exp` passed. Any failure is treated as "no
  cookie" and gets a fresh session. It never errors at the visitor.
- **Sliding refresh:** `VerifiedToken.needs_refresh` is true when `iat` is older than 7 days or the
  token was signed with the previous key. The cookie is then re-issued with the same `sid`. The
  visitor keeps their conversation.
- **Key rotation:** `SESSION_SIGNING_KEY_PREVIOUS` (optional) is accepted for verification only.
  Rotating means: set PREVIOUS = old, set new, deploy.
- **Identity:** `user_hash = HMAC-SHA256(USER_HASH_SALT, "web:" + sid)` (s03 `UserIdentity.user_hash(Channel.WEB, sid)`).
  `users.channel = 'web'`, `address_ciphertext = NULL`. The `sid` itself is never stored. Only
  the cookie holds it, so a database leak can't be turned into a live session.
- **CSRF:** `SameSite=Lax` stops browsers sending the cookie on cross-site POSTs. As a second
  layer, `POST`s also require `Origin` (or `Referer`) to match `PUBLIC_BASE_URL` → otherwise `403`.

### 4.3 `POST /demo/messages`

`multipart/form-data` with **exactly one** of:

| Field | Meaning | Limits |
|---|---|---|
| `text` | typed message | 1–1000 chars after trimming; not only whitespace |
| `audio` | recorded clip | ≤ `DEMO_MAX_AUDIO_BYTES` (1 MB, about 60 s of opus); declared type one of `audio/webm`, `audio/ogg`, `audio/mp4` (codecs param allowed); **magic bytes** must agree: webm `1A 45 DF A3`, ogg `OggS`, mp4 `ftyp` at offset 4 |
| `button_id` | tap on a reply button | must match `^[a-z0-9:_-]{1,256}$` and must be a button id offered in this user's latest reply (prevents forging onboarding answers) |
| `image` | a photo of what the child made or collected (C7, s10b §4.14) | only for a `parent` with an **open activity** (else `422 photo_not_accepted`); ≤ `MAX_INBOUND_IMAGE_BYTES`; declared type `image/jpeg`, `image/png` or `image/webp`; **magic bytes** must agree: JPEG `FF D8 FF`, PNG `89 50 4E 47`, WebP `RIFF`…`WEBP`. An optional `text` caption may accompany it (the one exception to "exactly one field") |

Processing, in order:
1. Cookie → `user_hash`. Missing or invalid → `401 {"error": "no_session"}` (the page calls `/demo/session` first).
2. Origin check → `403 {"error": "bad_origin"}`.
3. Rate limits (§4.6) → `429`.
4. Daily web cost cap (§4.7) → `503`.
5. Validate the fields → `422 {"error": "invalid_message", "field": "audio", "reason": "unsupported_type"}`.
   Reasons: `none_provided`, `multiple_provided`, `too_long`, `too_large`, `unsupported_type`,
   `type_mismatch`, `empty`, `unknown_button`.
6. One transaction:
   - audio → `INSERT media_blobs (purpose='inbound_audio', expires_at = now() + 24h)`
   - image → **never written to the database** (data-model §3, C7). See "Photos never touch the
     database" below. The inbox row gets `kind='image'`, `media_mime_type`, and no media reference
   - upsert `users` (s03 §4.5 query, `channel='web'`, ciphertext NULL)
   - `INSERT inbox_messages (channel='web', external_id=<uuid4>, provider_sent_at=now(), …)`,
     with `media_blob_id` / `media_mime_type` for audio and `raw_payload = NULL` (nothing external to keep)
   - `pg_notify('inbox_new', '')`
7. `202 {"message_id": "<uuid>"}`.

Audio **duration** isn't checked here: the browser's claim can't be trusted, and parsing
containers in the API is S6's job. `fetch_media`/`transcode` reject clips over 60 s with
`UNSUPPORTED_INPUT`, and the visitor gets the `REPEAT_PLEASE`-style fallback.

Safari records `audio/mp4` (AAC), not opus. It's accepted here, and S6 must transcode it.

**Photos never touch the database (C7; design point for the owner's review).** The photo rule
forbids storing a photo anywhere, even briefly, so a `media_blobs` row deleted at turn end isn't
allowed. Under exception E1 the API and the turn dispatcher are **one process** (mvp-scope.md §4.1),
so the upload is handed over in memory:
- the API puts the bytes in an in-process `PendingImages` map keyed by `message_id`, with a
  **60-second TTL**, then wakes the dispatcher for that user
- the `FETCH_IMAGE` step for a web `IMAGE` message takes the bytes out of the map (removing them);
  the person check, safety and counting run; the bytes are dropped at the end of the turn
- if the entry has expired or the process restarted, the step fails with `EMPTY_INPUT` and the
  parent gets a fixed "please send the photo again" reply; nothing else is lost
- when E1's upgrade (separate worker processes) is built, this hand-off needs a new design (for
  example, the API runs the person check itself before enqueueing), because memory isn't shared.
  That's recorded as a known limit of the in-memory approach.

### 4.4 `GET /demo/events` (Server-Sent Events)

- Requires a valid cookie (`401` otherwise). The stream only carries events for the session's `user_hash`.
- `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- Heartbeat comment `: ping` every 15 s (keeps proxies from closing idle connections).
- Server closes the stream after `DEMO_SSE_MAX_S` (600 s). `EventSource` reconnects automatically.
- On connect (and reconnect): replay every event of the user's most recent turn if it started
  within the last 2 minutes. The page de-duplicates by `(turn_id, step)` and `turn.completed`, so
  replays are harmless. No `Last-Event-ID` bookkeeping is needed.
- Limits: at most 2 open streams per session (the third gets `429`), and at most
  `DEMO_SSE_MAX_CONNECTIONS` (200) per API process.

Events (each `data` is JSON):

| `event` | When | `data` |
|---|---|---|
| `turn.started` | the first `turn_steps` row of a new turn appears | `{"turn_id", "message_ids": [..]}` |
| `step` | each `turn_steps` row | `{"turn_id", "step", "outcome", "duration_ms", "provider", "model", "cost_usd", "failure_kind", "info"}` |
| `turn.completed` | all outbox parts of the turn are `sent` or `failed` | `{"turn_id", "route", "register", "fixed_reply_kind", "text", "citations": [{"title", "url"}], "buttons": [{"id", "title"}], "audio_url", "total_ms", "total_cost_usd"}` |
| `error` | the stream itself has a problem | `{"error": "stream_limit" \| "server_shutdown"}` |

`info` holds step-specific details for the trace panel, built from data the visitor already owns:
- `transcribe` → `{"transcript": turns.user_text}`
- `safety_in` / `safety_out` → `{"decision": "allow" | "block" | "crisis"}`, read from
  `turn_steps.decision` (written by s07)
- `route` → `{"route": turns.route}`
- `generate` → `{"sources": <count>}` once citations exist
- all others → `{}`

The transcript is personal data, but it belongs to this visitor and is only sent to their own
cookie-authenticated stream. It never goes into `turn_steps`.

**How events reach the right stream.** Each API process holds **one** listener connection
(asyncpg) on `turn_progress`. The notification payload is a `turn_id`. The dispatcher:
1. looks up `turns.user_hash` for that `turn_id` (cached for the turn's life)
2. if no local subscriber has that `user_hash`, drops it (the visitor is connected to another process, or isn't a web user)
3. otherwise reads the new `turn_steps` rows for the turn (`WHERE turn_id = :t AND id > :last_seen`),
   builds the events, and puts them on each subscriber's `asyncio.Queue` (bounded at 100; a full
   queue closes that stream, and the client reconnects and replays)
4. detects completion: when every outbox part of the turn is `sent`/`failed` (S4's `WebSender`
   notifies after each part), it reads the parts and the turn and emits `turn.completed` once

The listener reconnects with backoff like S4's. While it's down, open streams fall back to polling
their user's latest turn every 2 s.

### 4.5 Snapshot and audio endpoints

- `GET /demo/turns/{turn_id}` → the same JSON as `turn.completed`, plus `steps: [...]`. `404`
  if the turn doesn't exist **or belongs to someone else**. The same status for both, so turn ids
  can't be probed. The page uses it when SSE is unavailable.
- `GET /demo/audio/{blob_id}` → audio bytes. Conditions: the cookie's `user_hash` equals
  `media_blobs.user_hash`, `purpose = 'reply_audio'`, `expires_at > now()`. Otherwise `404`.
  Headers: the stored `Content-Type`, `Cache-Control: private, max-age=3600`, `Content-Length`.
  Range requests aren't supported (clips are under 1 MB).

### 4.6 Rate limits

Two counters per message, in the request's transaction, using hourly windows:

```sql
INSERT INTO rate_limit_counters (key, window_start, count)
VALUES (:key, date_trunc('hour', now()), 1)
ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limit_counters.count + 1
RETURNING count;
```

| Key | Limit |
|---|---|
| `demo:session:<user_hash>` | `DEMO_RATE_LIMIT_PER_HOUR` (30) |
| `demo:ip:<HMAC(USER_HASH_SALT, client_ip)>` | `DEMO_IP_RATE_LIMIT_PER_HOUR` (90; a classroom shares one IP) |
| `demo:session-create:<ip hash>` | 20 new sessions per hour (stops cookie-clearing from resetting the per-session limit) |

- Over the limit → `429`, `Retry-After: <seconds to the next hour>`,
  body `{"error": "rate_limited", "scope": "session" | "ip", "retry_after_s": n}`. The transaction
  is rolled back, so an over-limit request writes nothing, counter included.
- `client_ip` is the platform's client-IP header (`Fly-Client-IP` on Fly), trusted only when
  `ENVIRONMENT=prod` behind the platform proxy. Otherwise the socket peer address is used. The raw IP is never stored.

### 4.7 Daily cost cap (web only)

s13's cost-today query (IST day, decision B8), filtered to web users. It's the same query
function (`TelemetryRepository.cost_today_usd(channel=Channel.WEB)`), so the day boundary is
defined once:

```sql
SELECT COALESCE(SUM(s.cost_usd), 0)
FROM turn_steps s
JOIN turns t ON t.id = s.turn_id
JOIN users u ON u.user_hash = t.user_hash
WHERE u.channel = 'web'
  AND s.started_at >= (date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata');
```

- Cached in-process for 30 s. At or over `DAILY_COST_CAP_USD` → `503`,
  `Retry-After: <seconds to the next 00:00 IST>`, body `{"error": "daily_budget_reached"}`. The page
  shows "The demo has reached today's limit. Please try again tomorrow, or watch the video."
- WhatsApp users aren't capped here. They're real users on a 5-recipient (or display-name-gated) number.
- Search grounding has its own cap (s10/s12). This is the outer limit.

### 4.8 `WebSender`

```python
class WebSender:                      # implements ChannelSender for Channel.WEB
    channel = Channel.WEB
    async def send(self, part: OutboundPart, recipient: ChannelAddress, audio: AudioClip | None = None) -> DeliveryReceipt:
        return DeliveryReceipt(provider_message_id=None, sent_at=self._clock.now())
    async def acknowledge(self, external_id: str) -> None:
        return None                   # the trace panel already shows progress
```

There's no external call. "Delivery" means the outbox loop marks the part `sent`, and in the
same transaction (inside `mark_sent` when `channel = 'web'`) runs `pg_notify('turn_progress', turn_id)`
so the API can emit `turn.completed`. The outbox loop passes
`ChannelAddress(channel=WEB, address=SecretStr(user_hash))`. Web needs no real address.

Web parts therefore follow the same order, retry and failure rules as WhatsApp. In practice they
never fail, which is fine: one code path.

### 4.9 Onboarding and reset on the web

- The same s08 state machine. The only difference is the consent text variant for
  `Channel.WEB`: it says this is a demo, that a cookie identifies the browser, that no phone number
  or name is collected, and that "Reset" deletes everything. s08 owns the wording, and keys it by channel.
- **Parents on the web:** onboarding offers the parent role, like WhatsApp (s08). There are no
  nudges on the web (no proactive channel), so every parent-journey reply carries an
  **"Aaj ki khoj"** button (`jrn:today`) that starts flow A of s10b (s10b Q4). This is how judges
  see the parent journey without a WhatsApp number.
- **Child talk on the web (C13):** a parent can enable child talk with the `onb:childtalk:yes` button, then press **"Main bachcha hoon 🙋"** (`kid:start`). The page switches to a child view: a large mic button, voice replies played automatically, minimal text, and a visible **session timer and exchange counter** (`CHILD_SESSION_MAX_MINUTES`, `CHILD_SESSION_MAX_TURNS`). When the session ends, the view returns to the parent and shows the topic summary. The same safeguards as WhatsApp apply (s10b §4.16, s07): consent required, no personal questions, no secrecy language, child-worded crisis replies, cooldown between sessions. The trace panel marks child turns with `speaker = learner`.
- Buttons from replies are rendered as real buttons, and a tap posts `button_id`.
- `POST /demo/reset` (rate-limited like a message): runs the s08 deletion for this `user_hash`
  directly (no confirmation turn: the click is the confirmation), clears the cookie, and returns
  `204`. Judges can replay onboarding from the start.

### 4.10 The page (`app/static/demo/`)

Files: `index.html`, `demo.js`, `demo.css`. Vanilla JS, no build step, no framework, no external
CDN. FastAPI serves them with `StaticFiles` at `/demo/static/`, and `GET /demo` returns `index.html`.

Layout (desktop: two columns; phone: the trace collapses under the chat):

```
┌───────────────────────── Marg.ai ─────────────────────────┬──────── Pipeline trace ─────────┐
│ [bot]  Namaste! …   ▶ 0:07  [Haan] [Nahi]                  │ turn 3f2a… · 6.8 s · $0.0041    │
│                                        [you] 🎤 0:05        │ ✓ fetch_media      120 ms       │
│ [bot]  Doctor banne ke liye NEET-UG …  ▶ 0:21               │ ✓ transcribe       910 ms       │
│        Sources: NEET-UG (nta) ↗                             │   "mujhe doctor banna hai"      │
│                                                             │ ✓ safety_in        340 ms allow │
│                                                             │ ✓ route            780 ms mentor│
│                                                             │ ✓ generate        2.4 s 3 src   │
│                                                             │ ✓ translate        900 ms       │
│                                                             │ ✓ safety_out       310 ms allow │
│                                                             │ ✓ synthesize       1.1 s        │
│ [ type a message…            ] [🎤 hold to talk] [send]    │ ✓ enqueue_reply     12 ms       │
└─────────────────────────────────────────────────────────────┴─────────────────────────────────┘
```

Behaviour:
- **Recording:** `MediaRecorder` with the first supported of `audio/webm;codecs=opus`,
  `audio/ogg;codecs=opus`, `audio/mp4`. Hold to talk on touch, click to toggle on desktop. Hard
  stop at 60 s with a visible countdown. Microphone permission denied → the text box stays usable,
  with a one-line explanation.
- **Sending:** `fetch('/demo/messages', {method: 'POST', body: FormData})`. The message bubble
  shows "sending…" until `202`, then "processing…" until its `turn.started`.
- **Trace:** one row per `StepName` in pipeline order, filled from `step` events: icon by outcome
  (`ok` ✓, `degraded` ◐, `failed` ✗, `skipped` –), duration, provider/model on hover, `info` inline.
  Header: total time and cost from `turn.completed`.
- **Reply:** the text with citations as links, an `<audio>` element for `audio_url`, and buttons.
- **Photos (parents with an open activity):** a "Photo bhejiye" button opens the file picker or
  camera (`<input type="file" accept="image/*" capture="environment">`), with a one-line reminder:
  "Sirf banayi ya ikatthi cheezein, bachche ki photo nahi." A rejected photo shows the fixed
  `PHOTO_HAS_PERSON` reply like any other message.
- **Khoj card (C6):** shown in the chat as an image with its caption and a **Download** button
  (an `<a download>` pointing at the reply's image URL, served like reply audio: owner check,
  `purpose='khoj_card'`, expiry).
- **Image steps in the trace:** `fetch_image`, `analyze_image` (with the counts as `info`, e.g.
  `{"leaf": 7}`) and `make_card` rows appear like every other step.
- **Errors:** `429`/`503` bodies shown as friendly banners; SSE disconnects show a small
  "reconnecting" pill (EventSource handles the retry).
- **Accessibility:** buttons have labels, the trace is an ordered list, and colour is never the only signal.
- **Security headers** on `/demo*`: `Content-Security-Policy: default-src 'self'; media-src 'self' blob:; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`. Citations open with `rel="noopener noreferrer"`.

### 4.11 Optional CAPTCHA

Off by default (`DEMO_CAPTCHA_ENABLED=false`). If abuse appears, enable Cloudflare Turnstile on
**session creation only**: the page renders the widget, and `/demo/session` verifies the token
server-side over httpx before issuing a cookie. No new package. Turning it on requires loading
the Turnstile script, which loosens the CSP for one origin. That's a reason to keep it off unless needed.

## 5. Interfaces

```python
# app/core/sessions.py   (shared with s13 dashboard links)
class SignedTokenCodec:
    def __init__(self, key: SecretStr, previous_key: SecretStr | None, clock: Clock) -> None: ...
    def issue(self, purpose: str, payload: Mapping[str, JsonValue], ttl_s: int) -> str: ...
    def verify(self, token: str, purpose: str) -> VerifiedToken | None: ...
    # HMAC-SHA256 over "<purpose>." + body; current key, then SESSION_SIGNING_KEY_PREVIOUS for verify

class VerifiedToken(BaseModel):    # frozen
    payload: dict[str, JsonValue]
    issued_at: datetime
    expires_at: datetime
    needs_refresh: bool            # older than 7 days, or signed with the previous key

# app/api/demo.py
router = APIRouter(prefix="/demo")
@router.get("")                         async def page() -> FileResponse: ...
@router.get("/session")                 async def session(...) -> SessionResponse: ...
@router.post("/messages", status_code=202) async def post_message(...) -> MessageAccepted: ...
@router.get("/events")                  async def events(...) -> EventSourceResponse: ...   # StreamingResponse
@router.get("/turns/{turn_id}")         async def turn_snapshot(turn_id: UUID, ...) -> TurnSnapshot: ...
@router.get("/audio/{blob_id}")         async def audio(blob_id: UUID, ...) -> Response: ...
@router.post("/reset", status_code=204) async def reset(...) -> None: ...

# app/channels/web/adapter.py
class WebIngest:
    async def accept(self, session: AsyncSession, user_hash: UserHash, submission: WebSubmission) -> UUID: ...
class WebSender: ...                    # §4.8

# app/channels/web/models.py   (frozen, extra="forbid")
class WebSubmission(BaseModel):    text: str | None; audio: UploadedAudio | None; button_id: str | None
class UploadedAudio(BaseModel):    data: bytes; mime_type: str
class SessionResponse(BaseModel):  state: ConversationState; language: Language | None
class MessageAccepted(BaseModel):  message_id: UUID
class StepEvent(BaseModel):        turn_id: TurnId; step: StepName; outcome: StepOutcome; duration_ms: int
                                   provider: str | None; model: str | None; cost_usd: Decimal
                                   failure_kind: FailureKind | None; info: StepInfo
class StepInfo(BaseModel):         transcript: str | None = None; decision: SafetyDecision | None = None
                                   route: Route | None = None; sources: int | None = None
class TurnCompletedEvent(BaseModel): turn_id: TurnId; route: Route | None; register: Language | None
                                   fixed_reply_kind: FixedReplyKind | None; text: str
                                   citations: list[CitationView]; buttons: list[ReplyButton]
                                   audio_url: str | None; total_ms: int; total_cost_usd: Decimal
class CitationView(BaseModel):     title: str; url: HttpUrl
class TurnSnapshot(TurnCompletedEvent): steps: list[StepEvent]

# app/api/sse.py
class TurnProgressHub:                  # one per API process
    async def run(self, stop: asyncio.Event) -> None: ...           # LISTEN turn_progress
    def subscribe(self, user_hash: UserHash) -> Subscription: ...   # async iterator of SSE events
# app/store/repositories/rate_limits.py
async def hit(session: AsyncSession, key: str, limit: int) -> RateDecision: ...
# app/store/repositories/costs.py
async def web_cost_today(session: AsyncSession) -> Decimal: ...
```

## 6. Data

- **Migration `s14_rate_limits`:** creates `rate_limit_counters`.
- **Writes:** `users` (web rows), `inbox_messages`, `media_blobs` (`inbound_audio`), `rate_limit_counters`.
- **Reads:** `turns`, `turn_steps`, `outbox_messages`, `media_blobs` (`reply_audio`).
- **Deletes** (reset): everything for the user via s08's deletion.
- **Listens:** `turn_progress`. **Notifies:** `inbox_new`.

## 7. Configuration

From contracts.md: `SESSION_SIGNING_KEY`, `USER_HASH_SALT`, `DEMO_RATE_LIMIT_PER_HOUR`,
`DAILY_COST_CAP_USD`, `ENVIRONMENT`.

Requested: `SESSION_SIGNING_KEY_PREVIOUS: SecretStr | None`, `PUBLIC_BASE_URL: HttpUrl`,
`DEMO_IP_RATE_LIMIT_PER_HOUR` (90), `DEMO_MAX_AUDIO_BYTES` (1_000_000), `DEMO_SSE_MAX_S` (600),
`DEMO_SSE_MAX_CONNECTIONS` (200), `DEMO_CAPTCHA_ENABLED` (false), `TURNSTILE_SECRET: SecretStr | None`.

## 8. Failure modes

| Failure | Visitor sees | Recorded |
|---|---|---|
| Cookie missing / tampered / expired | a fresh session (new conversation) | log `info session_reset` (no token values) |
| Cross-site POST | nothing happens | `403`, log `warning` |
| Over a rate limit | "Too many messages, try again in N minutes" | `429`, counter row |
| Daily cost cap reached | "Today's demo limit is reached" | `503`, log `warning` once per hour |
| Bad upload (type, size, magic bytes) | "That recording didn't work, please try again" | `422` with reason |
| Clip over 60 s / unreadable | the fixed repeat-please reply | turn `failed` at `fetch_media`/`transcribe` (S6) |
| SSE listener down | trace updates every 2 s instead of live | log `warning`, reconnect attempts |
| SSE connection dropped | a "reconnecting" pill; events replayed | — |
| Worker down | "processing…" for longer; the reply arrives when it recovers | S4 handles it |
| Reply audio expired (24 h) | the audio control shows unavailable; the text remains | `404` |
| Browser can't play the audio format | text only (see open question 1) | — |

## 9. Tests

**Unit**
- `SignedTokenCodec`: issue → verify round trip; a tampered body / sig → `None`; a future `iat` beyond skew → `None`; past `exp` → `None`; signed with the previous key → valid with `needs_refresh=True`; another key → `None`; a `"dash"` token verified as `"demo_session"` → `None`.
- Submission validation: one parametrized case per `422` reason, asserting the exact `field` and `reason`.
- Magic-byte checks: webm / ogg / mp4 headers accepted; a webm header declared as `audio/ogg` → `type_mismatch`; random bytes → `unsupported_type`.
- `button_id` not in the latest reply's buttons → `unknown_button`.
- Event builders: a `turn_steps` row plus turn → the exact `StepEvent` JSON per step (including `info` for transcribe, safety, route); the `turn.completed` builder with and without audio, with a fixed reply.
- `WebSender.send` returns a receipt with no provider id and makes no I/O; `acknowledge` is a no-op.
- `client_ip` selection: the platform header is trusted only in prod.

**Property** (hypothesis)
- Cookie codec: for any JSON-safe payload, purpose and key, `verify(issue(p, payload, ttl), p).payload == payload`; flipping any character of the token makes `verify` return `None`; verifying under a different purpose returns `None`.
- Rate limiter (pure model of the counter logic): for any sequence of n requests in one window, exactly `min(n, limit)` are allowed, and they're the first ones.
- Hub routing: for any interleaving of notifications across users, a subscriber only ever receives events whose `turn_id` belongs to its `user_hash`.

**Negative (route level)**
- `POST /demo/messages` without a cookie → `401 {"error":"no_session"}`, no rows written.
- Wrong `Origin` → `403`, no rows, counter not incremented.
- Over the session limit → `429` with `Retry-After`, and the inbox has no new row.
- Cost cap reached (seeded `turn_steps`) → `503 {"error":"daily_budget_reached"}`, no rows.
- Cost-cap day boundary: web steps at 18:29 UTC and 18:31 UTC fall on different IST days.
- `text` + `audio` together → `422 multiple_provided`; empty / whitespace text → `422 empty`; a 1,000,001-byte clip → `422 too_large`.
- `GET /demo/turns/{id}` for another session's turn → `404`, identical to a non-existent id.
- `GET /demo/audio/{id}` for another session's blob, an expired blob, or an `inbound_audio` blob → `404`.
- A third SSE connection on one session → `429`.

**Integration** (real Postgres, api + worker with the fake orchestrator)
- Text message → `202` → SSE delivers `turn.started`, one `step` per recorded step in order, then exactly one `turn.completed` whose `text` matches the outbox part.
- Two messages 300 ms apart → one `turn.started` listing both message ids.
- Reconnect mid-turn → replayed events; the page model de-duplicates to one row per step.
- Two browsers (two cookies) → each stream only sees its own turns.
- Reset → the users row and every dependent row are gone; the cookie is cleared; the next `/demo/session` starts at `new`.
- Audio round trip with a real webm fixture → `media_blobs` row with `inbound_audio` → (S6 present) transcript in the `transcribe` event.

**Manual browser checks** (listed in the exit check): Chrome desktop, Android Chrome, iOS Safari.

## 10. Exit check

1. Open `https://<host>/demo` in a private window on a phone you haven't used before.
2. Complete onboarding with the buttons (web consent text shown).
3. Hold the mic, say "mujhe doctor banna hai", release. The trace fills live, step by step;
   the transcript appears after `transcribe`; the reply plays as audio, with the text and a cited
   source. Total time is shown.
4. Repeat on iOS Safari (mp4 recording path) and desktop Chrome.
5. Send 31 messages in an hour from one session → the 31st gets the rate-limit banner.
6. Set `DAILY_COST_CAP_USD=0.0001` on staging → the next message gets the daily-limit banner.
7. Press Reset → onboarding starts again, and the old rows are gone in `psql`.

## 11. Open questions

1. **Reply audio format for browsers:** S6 produces ogg/opus for WhatsApp. Chrome, Firefox and
   recent Safari play ogg/opus, but older iOS Safari may not. *Recommendation:* test on a real iPhone
   in S14. If it fails, S6 also produces an `audio/mp4` (AAC) copy for web turns only (one extra ffmpeg call).
2. ~~**Safety decision in the trace**~~ **Resolved (defaults approved, B1):** `turn_steps.decision`
   exists (data-model.md) and is written by s07; the trace reads it.
3. **CAPTCHA:** keep it off for judging week unless abuse shows up in `/status`.
4. **Demo for multiple judges on one network:** the per-IP limit of 90/hour should cover a judging
   room. Raise it on finals day if needed.

## Contract changes (resolved 2026-10-25)

- **00-overview.md §3** web ingress ("202 + message id; events on the session's SSE stream"): **applied**.
- **Settings** in §7: **applied** (contracts §7, "Web demo (s14)", plus `SESSION_SIGNING_KEY_PREVIOUS`, `PUBLIC_BASE_URL`).
- **`ChannelSender`** `acknowledge` and `audio`: **applied** (contracts §3); `WebSender` implements both.
- **`mark_sent` notifies `turn_progress` for web parts:** **applied** (data-model.md `outbox_messages`; s04 implements).
- **`turn_steps.decision`:** **applied** (data-model.md, and `StepRecorder.record(..., decision=...)` in contracts §3); written by s07.
- **`SignedTokenCodec` shared with s13:** **applied** here with the purpose-based API above; s13 uses purpose `"dash"`.

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-25 | Session cookie on the shared purpose-based `SignedTokenCodec`; web cost cap on the IST day via s13's query; trace reads `turn_steps.decision`; parent role and the "Aaj ki khoj" button on the web | Consolidation against the updated foundation docs (A2, B1, B8, B12) | owner |
| 2026-10-26 | Web image upload for parents with an open activity (jpeg/png/webp, magic bytes, size cap), handed to the in-process dispatcher in memory with a 60 s TTL and never stored; khoj card shown with a download button; image steps in the trace | Owner decisions C6, C7; the in-memory hand-off is a design point for the owner's review | pending owner review |
| 2026-10-26 | Child talk on the web: enable via `onb:childtalk:yes`, "Main bachcha hoon" button, child view with session timer and exchange counter, summary back to the parent, same safeguards | Owner decision C13 | owner |
| 2026-10-27 | **Web demo built (E2: polling).** Messages are **JSON** (a voice note as base64) rather than multipart: FastAPI's form parsing needs `python-multipart`, a new dependency; the size and magic-byte checks apply to the decoded audio. The page polls `GET /demo/messages/{id}` every second (status, steps, parts with media URLs) instead of SSE. The origin check compares the Origin's host with the request's own Host (no `PUBLIC_BASE_URL` setting, which would change with every tunnel). Behind the local cloudflared tunnel the visitor's IP is Cloudflare's `CF-Connecting-IP` when the socket peer is loopback; only a keyed hash of it is stored. `GET /demo/session` creates the web visitor's user row, so a first message that is a voice note can be stored. A heard web voice note is deleted with the turn (`DeleteInboundMedia`). Photos (C7) and the admin dashboard are not in this build | Build choices; avoid a dependency | pending owner review |
