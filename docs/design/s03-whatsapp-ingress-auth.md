# S3 — WhatsApp ingress, authentication and sending

> **Hackathon build level: Full.** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

> Draft v1, 2026-10-25. Reviewed and approved at the start of S3, before any code.

## 1. Purpose

Get a WhatsApp message from a real phone into our database **safely and within a second**, and
get a message from us back to that phone. This step owns:
- every form of "auth" on the WhatsApp side (Meta → us, us → Meta, who the user is)
- the typed parsing of Cloud API webhooks
- the WhatsApp implementation of `ChannelSender`

S4 builds the queue that connects the two. Until then, the exit check uses a CLI command to send
the reply.

## 2. Read first

- [00-overview.md](00-overview.md) §2–3: processes and the life of one message
- [contracts.md](contracts.md): §1 `Channel`, `MessageKind`, `OutboxStatus`; §2.1 `InboundMessage`, `MediaRef`; §3 `ChannelSender`, `ChannelAddress`, `DeliveryReceipt`; §4 `ChannelError` and `ProviderError`; §5 retry policy; §7 `WHATSAPP_*`, `USER_HASH_SALT`, `ADDRESS_ENCRYPTION_KEY`
- [data-model.md](data-model.md): `users`, `inbox_messages`, `outbox_messages` (status updates), §3 encryption
- [plan.md](../../plan.md) §4.1 (channel rules, number strategy), §5.1 (reliability)
- [CLAUDE.md](../../CLAUDE.md) §11 (safety and privacy), §12 (webhook acknowledges in under one second)

## 3. Scope

**In**
- `GET /webhooks/whatsapp`: the verification handshake
- `POST /webhooks/whatsapp`: signature check over the raw body, parsing, identity, inbox insert, `NOTIFY inbox_new`
- Typed models for the webhook envelope, messages (text, audio, interactive, button, unsupported), statuses and errors
- PII stripping for `raw_payload`
- User identity: `user_hash`, AES-GCM address encryption, users upsert, `last_inbound_at`
- `WhatsAppSender` (`ChannelSender`): text, interactive buttons, audio (media upload + send), images with a caption (khoj cards, C6), template messages (s10b nudges), plus `acknowledge` (mark read + typing indicator)
- Graph API error classification into `ProviderError` subclasses
- Parsing status webhooks, plus the `apply_status_update` repository function (wired up once `outbox_messages` exists in S4)
- CLI `marg whatsapp reply-latest`: an ops tool used for the exit check
- Alembic migration `s03_users_inbox`

**Out**
- Leases, turns, outbox delivery loop → S4
- Downloading inbound audio (`MediaFetcher`) → S6, which reuses the Graph client built here
- Producing reply audio → S6. This step only uploads and sends an `AudioClip` it's given.
- Splitting long text → `app/domain/text.py` (S5). The sender refuses text over 4096 characters and never truncates.
- Web channel → S14

## 4. Design

### 4.1 Request flow

```
Meta ──POST /webhooks/whatsapp──▶ api
  1. raw = await request.body()                    (cap: 5 MB → 413)
  2. verify_signature(raw, X-Hub-Signature-256)    (fail → 401, nothing parsed, nothing stored)
  3. body = WebhookBody.model_validate_json(raw)   (fail → log error, 200; see 4.4)
  4. for each entry[].changes[] with field == "messages"
     and value.metadata.phone_number_id == WHATSAPP_PHONE_NUMBER_ID:
       messages[] → InboundMessage + users upsert + inbox insert
       statuses[] → StatusUpdate → apply_status_update (S4 onwards)
       value.errors[] → log at error (account or app level problems)
  5. one DB transaction for the whole POST; pg_notify('inbox_new', '') if any row was inserted
  6. return 200 "ok"
```

The handler does nothing else. No model calls, no outbound HTTP. Read receipts and the typing
indicator are sent by the worker when it starts the turn (`acknowledge`, §5.4), because that's
when we know a reply is coming. Meta's guidance is to show the typing indicator only when we're
going to reply. It disappears when we reply or after 25 s.

### 4.2 Verification handshake (GET)

Meta calls `GET /webhooks/whatsapp?hub.mode=subscribe&hub.challenge=<n>&hub.verify_token=<t>` once,
when the callback URL is saved in the App Dashboard.

- `hub.mode == "subscribe"` and `hmac.compare_digest(token, WHATSAPP_VERIFY_TOKEN)` → `200`,
  `text/plain`, body = `hub.challenge` exactly as received.
- Anything else → `403`, empty body. Log a warning with no token value.

### 4.3 Signature check (POST)

Meta signs every POST: `X-Hub-Signature-256: sha256=<hex HMAC-SHA256(app_secret, body)>`.

- The HMAC is computed over the **raw request bytes**, read before any JSON parsing. Re-serialising
  parsed JSON changes whitespace and key order and breaks the signature.
- Header missing, not prefixed `sha256=`, or not 64 hex characters → `SignatureInvalid` → `401`.
- Comparison with `hmac.compare_digest` on the lowercase hex strings (constant time).
- `401` responses carry no detail. The log line says `signature_invalid` and the header's
  presence and length, never the body.
- Meta retries any non-200 for up to 7 days. A wrong app secret therefore produces a retry flood
  that's visible in logs, not lost messages. Once fixed, the retries deliver normally, and the
  unique `(channel, external_id)` stops duplicates.

mTLS for webhooks exists (configured per app) but is out of scope. The HMAC check is sufficient,
and TLS with a real certificate is required either way (Fly/Railway provide it).

### 4.4 Parsing rules

The webhook models are **external** models, so they're the one place `extra="ignore"` is used
instead of the default `extra="forbid"`. Meta adds fields without notice, and a new optional field
must not turn every webhook into a parse failure. They're still fully typed, and unknown
`type` values map to a typed "unknown" branch rather than being dropped.

| Situation | Response | What's stored |
|---|---|---|
| Valid signature, valid envelope | 200 | each message → inbox row |
| Valid signature, body isn't JSON / envelope invalid | 200 | nothing (no user to attach it to). Log `error` with `fbtrace`-free summary: size, first validation error path, no values |
| Envelope valid, one message fails its type-specific model | 200 | that message stored as `kind = UNSUPPORTED` with its stripped raw payload, so it's visible and gets the "I can only understand voice and text" reply |
| `object != "whatsapp_business_account"` or `field != "messages"` | 200 | nothing; log `info` |
| `phone_number_id` isn't ours | 200 | nothing; log `warning` (misrouted webhook or a second number on the app) |

Returning 200 for an authentic payload we can't parse is deliberate. A non-200 makes Meta retry
the same bytes for 7 days, which can't succeed and hides real traffic in noise.

Message `type` → `MessageKind`:

| Cloud API `type` | `MessageKind` | Fields used |
|---|---|---|
| `text` | `TEXT` | `text.body` → `text` |
| `audio` | `AUDIO` | `audio.id` → `MediaRef.provider_media_id`, `audio.mime_type`. `audio.voice` is logged as a dimension (voice note vs forwarded file). `audio.url` is ignored (rolling out since Nov 2025, and expires) |
| `interactive` + `button_reply` | `INTERACTIVE` | `button_reply.id` → `interactive_reply_id`, `button_reply.title` → `text` |
| `interactive` + `list_reply` | `INTERACTIVE` | `list_reply.id`, `list_reply.title` |
| `button` (template quick reply) | `INTERACTIVE` | `button.payload` → `interactive_reply_id`, `button.text` → `text`. This is how a parent's tap on the daily nudge template arrives: payload `jrn:today` → s05 routes it to `JOURNEY` (s10b §4.11) |
| `image` | `IMAGE` (decision C7) | `image.id` → `MediaRef.provider_media_id`, `image.mime_type`. `image.caption` → `text` (the parent may describe the photo). `image.url` and `image.sha256` are ignored here (the media fetch re-reads them). Only parents with an open activity get photo handling; everyone else gets `PHOTO_NOT_NEEDED` (s10b §4.14). The image itself is never stored |
| `video`, `document`, `sticker`, `location`, `contacts`, `unsupported`, unknown | `UNSUPPORTED` | none (the reply is `UNSUPPORTED_MEDIA`, S5) |
| `reaction` | not stored | an emoji reaction to our message isn't a request. Log at `debug` |
| `system` (user changed number) | not stored | log `info`. Number changes aren't followed in the MVP (open question 3) |

`timestamp` is Unix seconds as a string → `provider_sent_at` (aware UTC). `id` (`wamid.…`) → `external_id`.

### 4.5 User identity

```
wa_id (digits, no "+", from messages[].from)
  ├─ user_hash          = hex(HMAC-SHA256(USER_HASH_SALT, "whatsapp:" + wa_id))
  └─ address_ciphertext = nonce(12) ‖ AESGCM(ADDRESS_ENCRYPTION_KEY).encrypt(nonce, wa_id, aad=user_hash)
```

- The canonical address is the digits-only `wa_id` exactly as Meta sends it. It isn't
  re-formatted, so the same person always hashes the same way.
- The associated data is `user_hash`, which binds the ciphertext to its row: a ciphertext copied
  onto another user's row fails to decrypt rather than sending to the wrong person.
- `contacts[].profile.name` is never read into a domain object or stored.
- Upsert (inside the webhook transaction):

```sql
INSERT INTO users (user_hash, channel, address_ciphertext, state, last_inbound_at, created_at, updated_at)
VALUES (:user_hash, 'whatsapp', :address_ciphertext, 'new', :provider_sent_at, now(), now())
ON CONFLICT (user_hash) DO UPDATE
SET last_inbound_at = GREATEST(users.last_inbound_at, EXCLUDED.last_inbound_at),
    updated_at      = now();
```

An existing ciphertext is never overwritten by the upsert. `GREATEST` keeps `last_inbound_at`
correct when Meta delivers an older retry after a newer message.

### 4.6 Inbox insert

```sql
INSERT INTO inbox_messages
  (channel, external_id, user_hash, kind, text, media_provider_id, media_mime_type,
   interactive_reply_id, raw_payload, provider_sent_at)
VALUES ('whatsapp', :external_id, :user_hash, :kind, :text, :media_provider_id, :media_mime_type,
        :interactive_reply_id, :raw_payload, :provider_sent_at)
ON CONFLICT (channel, external_id) DO NOTHING
RETURNING id;
```

If at least one row is returned in the transaction, run `SELECT pg_notify('inbox_new', '')`
before commit. Postgres delivers notifications only on commit, so the worker never wakes for
a row it can't see.

### 4.7 PII stripping (`raw_payload`)

`raw_payload` is built from an **allowlist**, not by deleting known PII fields. An allowlist can't
leak a field Meta adds next year.

Kept: `id`, `timestamp`, `type`, the type sub-object (`text`, `audio` without `url`, `image`
with only `id` and `mime_type`, `interactive`, `button`, `errors`), and `context.id` (the message
being replied to). Dropped: `from`, `contacts`, `context.from`, `audio.url`, `image.url`,
`image.sha256`, **`image.caption`** (free text the parent wrote, which goes to `inbox_messages.text`
under turn-text retention instead), everything at envelope level.
A property test asserts the stripped payload never contains the `wa_id` string anywhere.

### 4.8 Status webhooks

`statuses[]` entries become `StatusUpdate(provider_message_id, status, timestamp, error_code, error_title)`.
`status` is one of `sent`, `delivered`, `read`, `played`, `failed`. `played` (a voice note was
played) is treated as `read`. `recipient_id` is never stored.

Status changes only move forward: `sent < delivered < read`. `failed` can arrive after `sent`.
A late `delivered` must not overwrite `read`:

```sql
UPDATE outbox_messages
SET status       = CASE
                     WHEN :status = 'failed' THEN 'failed'
                     WHEN array_position(ARRAY['pending','sending','sent','delivered','read'], status)
                          < array_position(ARRAY['pending','sending','sent','delivered','read'], :status)
                     THEN :status ELSE status END,
    delivered_at = CASE WHEN :status IN ('delivered','read') THEN COALESCE(delivered_at, :at) ELSE delivered_at END,
    read_at      = CASE WHEN :status = 'read' THEN COALESCE(read_at, :at) ELSE read_at END,
    last_error   = CASE WHEN :status = 'failed' THEN :error_summary ELSE last_error END
WHERE provider_message_id = :provider_message_id;
```

`outbox_messages` is created in S4. In S3, status updates are parsed, validated and logged, and
the repository function exists and is unit-tested. The webhook calls it from S4 onwards.
An unknown `provider_message_id` (not ours, or the row was deleted with its user) updates zero
rows and logs at `debug`.

### 4.9 Sending (`WhatsAppSender`)

All sends are `POST {WHATSAPP_GRAPH_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages`, with
`Authorization: Bearer <WHATSAPP_ACCESS_TOKEN>`.

| Part | Request body (abridged) | Limits enforced before sending |
|---|---|---|
| `TEXT` | `{"messaging_product":"whatsapp","recipient_type":"individual","to":<wa_id>,"type":"text","text":{"body":…,"preview_url":false}}` | 1 ≤ len(body) ≤ 4096, else `ValueError` (a bug upstream; never truncate) |
| `INTERACTIVE` | `…"type":"interactive","interactive":{"type":"button","body":{"text":…},"action":{"buttons":[{"type":"reply","reply":{"id":…,"title":…}}]}}` | 1–3 buttons, title ≤ 20 chars, id ≤ 256 chars, body ≤ 1024 chars |
| `AUDIO` | step 1: upload, `POST /{phone_number_id}/media` multipart `file`, `type=audio/ogg`, `messaging_product=whatsapp` → `{"id"}`; step 2: `…"type":"audio","audio":{"id":<media_id>}` | mime must be `audio/ogg; codecs=opus`, mono, ≤ 16 MB (plain `audio/ogg` without opus is rejected by Meta) |
| `IMAGE` (khoj card, C6) | step 1: upload, `POST /{phone_number_id}/media` multipart `file`, `type=image/png` (or `image/jpeg`), `messaging_product=whatsapp` → `{"id"}`; step 2: `…"type":"image","image":{"id":<media_id>,"caption":<part.text>}` (**verify in S3** against Meta's media and image-message references) | `part.image_blob_id` set and the bytes passed in as `image: ImageClip`; mime `image/png` or `image/jpeg`, ≤ 5 MB (WhatsApp image limit, verify); caption ≤ 1024 chars, else `ValueError` (never truncated). Free-form, so inside the 24-hour window only (the card follows a parent's report, s10b §4.13) |
| `TEMPLATE` | `…"type":"template","template":{"name":<TemplateRef.name>,"language":{"code":<TemplateRef.language_code>},"components":[{"type":"button","sub_type":"quick_reply","index":"0","parameters":[{"type":"payload","payload":<button_payloads[0]>}]}]}` (**verify in S3** against Meta's template-message reference; the exact component shape for quick-reply payloads is unverified) | `part.template` set and `text`/`audio` unset; the name must be an approved template (`NUDGE_TEMPLATE_NAME`); ≤ 3 payloads, matching the template's buttons. **Not subject to the 24-hour window**: the outbox loop skips its window check for `TEMPLATE` parts (s04, s10b §4.11) |

The response `{"messages":[{"id":"wamid…"}]}` → `DeliveryReceipt(provider_message_id, sent_at)`.

`preview_url` is false because link previews in a child's chat are content we didn't check.

The recipient comes from `ChannelAddress.address` (a `SecretStr`), decrypted from
`users.address_ciphertext` by the outbox loop just before sending (S4). It's never logged.

Whether an uploaded ogg/opus file shows as a **voice note** (waveform UI) or as an audio file
attachment needs checking on a real phone in S6. Both play; the voice-note look is better.

### 4.10 Graph API errors

Error body: `{"error":{"message","type","code","error_data":{"details"},"fbtrace_id"}}`. We
classify on `code` (Meta's guidance), with HTTP status as a fallback.

| Code(s) | Meaning | Raised as | Outbox effect (S4) |
|---|---|---|---|
| `4`, `80007`, `130429` | app / account / throughput rate limit | `ProviderRateLimited` | retry with backoff |
| `131056` | too many messages to this one user | `ProviderRateLimited` | retry with backoff |
| `131000`, `131016`, HTTP 5xx, timeout, connection error | unknown / service unavailable | `ProviderUnavailable` / `ProviderTimeout` | retry with backoff |
| `131047` | 24-hour window closed | `ProviderRejected` | `failed`, `last_error="window_closed"`. Only a template can reach the user; templates are used for parent nudges only (s10b) |
| `131026` | undeliverable (not on WhatsApp, old app, …) | `ProviderRejected` | `failed` |
| `131049` | held back for ecosystem engagement | `ProviderRejected` | `failed` (retrying within 24 h fails again) |
| `131051`, `131053`, `131008`, `131009`, `100` | our request is wrong (type, media, parameter) | `ProviderRejected` | `failed` + log `error`: this is a bug |
| `132000`–`132016` (template family: not found, not approved, parameter mismatch, paused; **verify codes in S3**) | the nudge template can't be sent | `ProviderRejected` | `failed` + log `error` `nudge_template_rejected`; the parent gets no nudge that day (s10b §8) |
| `0`, `190`, `131005` | token invalid / expired / missing permission | `ProviderRejected` | `failed` + log `error` `whatsapp_auth_failed`. **Every** send fails until the token is fixed |
| `131031`, `368`, `133010`, `131042` | account restricted / number not registered / billing | `ProviderRejected` | `failed` + log `error` |
| anything else 4xx | — | `ProviderRejected` | `failed` + log `error` with the code |

The same codes arrive asynchronously in `statuses[].errors[]` (§4.8), for failures that happen
after the API accepted the message.

### 4.11 Graph API version

`WHATSAPP_GRAPH_BASE_URL` pins the version (`…/v23.0` in contracts.md is a placeholder). In S3,
look up the current version in the App Dashboard, pin it, and record it in `docs/decisions/`.
Meta keeps each version for roughly two years, so one pin lasts the whole project.

## 5. Interfaces

### 5.1 `app/channels/whatsapp/signature.py`

```python
def verify_signature(raw_body: bytes, signature_header: str | None, app_secret: SecretStr) -> None:
    """Raise SignatureInvalid unless the header is a valid sha256 HMAC of raw_body."""

def verify_subscription(mode: str | None, token: str | None, expected: SecretStr) -> bool: ...
```

### 5.2 `app/channels/whatsapp/payloads.py` (external models, `extra="ignore"`, frozen)

```python
class WaMetadata(BaseModel):         display_phone_number: str; phone_number_id: str
class WaContactProfile(BaseModel):   name: str | None = None
class WaContact(BaseModel):          wa_id: str; profile: WaContactProfile | None = None
class WaText(BaseModel):             body: str
class WaAudio(BaseModel):            id: str; mime_type: str; sha256: str | None = None; voice: bool | None = None
class WaImage(BaseModel):            id: str; mime_type: str; sha256: str | None = None; caption: str | None = None
class WaButtonReply(BaseModel):      id: str; title: str
class WaListReply(BaseModel):        id: str; title: str; description: str | None = None
class WaInteractive(BaseModel):      type: Literal["button_reply", "list_reply"]
                                     button_reply: WaButtonReply | None = None
                                     list_reply: WaListReply | None = None
class WaButton(BaseModel):           payload: str; text: str
class WaContext(BaseModel):          id: str | None = None; from_: str | None = Field(None, alias="from")
class WaErrorData(BaseModel):        details: str | None = None
class WaError(BaseModel):            code: int; title: str | None = None; message: str | None = None
                                     error_data: WaErrorData | None = None
class WaMessage(BaseModel):          from_: str = Field(alias="from"); id: str; timestamp: str; type: str
                                     text: WaText | None = None; audio: WaAudio | None = None
                                     image: WaImage | None = None
                                     interactive: WaInteractive | None = None; button: WaButton | None = None
                                     context: WaContext | None = None; errors: list[WaError] = []
class WaStatus(BaseModel):           id: str; status: Literal["sent","delivered","read","played","failed"]
                                     timestamp: str; recipient_id: str; errors: list[WaError] = []
class WaValue(BaseModel):            messaging_product: Literal["whatsapp"]; metadata: WaMetadata
                                     contacts: list[WaContact] = []; messages: list[WaMessage] = []
                                     statuses: list[WaStatus] = []; errors: list[WaError] = []
class WaChange(BaseModel):           field: str; value: WaValue
class WaEntry(BaseModel):            id: str; changes: list[WaChange]
class WebhookBody(BaseModel):        object: str; entry: list[WaEntry]
```

`type` stays a `str` on `WaMessage` (not a `Literal`), so an unknown type validates and is then
mapped to `UNSUPPORTED` by `to_inbound`, instead of failing the whole envelope.

### 5.3 `app/channels/whatsapp/inbound.py`

```python
class StatusUpdate(BaseModel):       # frozen, extra="forbid"
    provider_message_id: str
    status: OutboxStatus             # played → READ
    at: datetime
    error_code: int | None
    error_title: str | None

class ParsedMessage(BaseModel):
    inbound: InboundMessage
    wa_id: SecretStr                 # for encryption only; never logged
    raw_payload: dict[str, JsonValue]  # already allowlisted (§4.7); JsonValue from pydantic

class ParsedWebhook(BaseModel):
    messages: list[ParsedMessage]
    statuses: list[StatusUpdate]
    ignored: int                     # reactions, system messages, foreign phone_number_id
    account_errors: list[WaError]

def parse_webhook(body: WebhookBody, own_phone_number_id: str, hasher: UserIdentity, received_at: datetime) -> ParsedWebhook: ...
def strip_message_payload(message: WaMessage) -> dict[str, JsonValue]: ...
```

### 5.4 `app/channels/whatsapp/client.py`

```python
class WhatsAppSender:                # implements ChannelSender
    channel: Channel = Channel.WHATSAPP
    def __init__(self, http: ProviderHttp, settings: WhatsAppSettings) -> None: ...
    async def send(self, part: OutboundPart, recipient: ChannelAddress, audio: AudioClip | None = None,
                   image: ImageClip | None = None) -> DeliveryReceipt: ...   # `image`: requested contract change (C6)
    async def acknowledge(self, external_id: str) -> None:
        """Mark read + typing indicator: {"messaging_product":"whatsapp","status":"read",
        "message_id": external_id, "typing_indicator": {"type": "text"}}"""
    async def upload_audio(self, clip: AudioClip) -> str: ...   # returns media id

def classify_graph_error(status_code: int, body: bytes) -> ProviderError: ...
```

`audio` is passed in by the outbox loop, which loads `media_blobs` for `part.audio_blob_id`. The
sender does no database access. `ProviderHttp` is the shared client with retry policy
from `app/providers/http.py` (S5 builds it fully; S3 uses its timeout and error mapping).

### 5.5 `app/core/identity.py`

```python
class UserIdentity:
    def __init__(self, salt: SecretStr, encryption_key: SecretStr) -> None: ...
    def user_hash(self, channel: Channel, address: str) -> UserHash: ...
    def encrypt_address(self, user_hash: UserHash, address: str) -> bytes: ...
    def decrypt_address(self, user_hash: UserHash, ciphertext: bytes) -> SecretStr: ...   # raises InvalidAddressCiphertext
```

### 5.6 `app/api/webhooks_whatsapp.py`

```python
router = APIRouter(prefix="/webhooks/whatsapp")

@router.get("")   async def verify(mode: str | None = Query(None, alias="hub.mode"), ...) -> PlainTextResponse: ...
@router.post("")  async def receive(request: Request, ingest: WhatsAppIngestDep) -> PlainTextResponse: ...
```

`WhatsAppIngest` (in `app/channels/whatsapp/ingest.py`) does steps 3–5 of §4.1, so the route stays
thin and the logic can be tested without HTTP.

### 5.7 Repositories

```python
# app/store/repositories/users.py
async def upsert_inbound_user(session: AsyncSession, user_hash: UserHash, channel: Channel,
                              address_ciphertext: bytes | None, last_inbound_at: datetime) -> None: ...
async def load_address(session: AsyncSession, user_hash: UserHash) -> bytes | None: ...

# app/store/repositories/inbox.py
async def insert_inbound(session: AsyncSession, message: InboundMessage,
                         raw_payload: dict[str, JsonValue] | None) -> bool: ...   # True if inserted
async def notify_inbox_new(session: AsyncSession) -> None: ...

# app/store/repositories/outbox.py
async def apply_status_update(session: AsyncSession, update: StatusUpdate) -> bool: ...  # True if a row matched
```

### 5.8 CLI (`app/cli.py`)

`marg whatsapp reply-latest --text "…"`: finds the newest WhatsApp inbox row, decrypts that
user's address, and sends the given text with `WhatsAppSender`. It's a permanent ops tool for
checking that sending works, not part of the pipeline. Default text:
`"Marg.ai received your <kind> message."`

## 6. Data

- **Migration `s03_users_inbox`** creates:
  - `users`: `user_hash`, `channel`, `address_ciphertext`, `state` (default `new`), `last_inbound_at`, `created_at`, `updated_at`
  - `inbox_messages`: every column in data-model.md except `attempts`, `available_at` and `turn_id` (S4) and `media_blob_id` (S6)
- **Writes:** `users` (upsert), `inbox_messages` (insert).
- **Reads:** `users.address_ciphertext` (CLI).
- **From S4:** updates `outbox_messages` delivery columns from status webhooks.

## 7. Configuration

`WHATSAPP_GRAPH_BASE_URL`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `USER_HASH_SALT`, `ADDRESS_ENCRYPTION_KEY`,
`DATABASE_URL`, `TIMEOUT_<…>` for the Graph client (5 s per call).
Requested: `WEBHOOK_MAX_BODY_BYTES` (default 5 MB). Meta batches up to 1000 updates per POST.

**Template setup** (S10b): `NUDGE_TEMPLATE_NAME` is created and approved in WhatsApp Manager in
Hindi, Hinglish and English, with one quick-reply button (s10b §4.11). The sender doesn't need
any other template setting.

**Dashboard setup** (done once, recorded in `docs/s0-setup.md`): callback URL
`https://<app-host>/webhooks/whatsapp`, verify token, subscribe the `messages` field. For local
testing, `scripts/dev_tunnel.sh` exposes the local API over a public HTTPS tunnel. Meta rejects
self-signed certificates.

## 8. Failure modes

| Failure | User sees | Recorded |
|---|---|---|
| Bad / missing signature | nothing (not from Meta) | `401`, log `warning signature_invalid` |
| Wrong app secret configured | nothing until fixed; Meta retries for 7 days, so messages arrive late rather than never | every POST is `401`; alert on more than 5 in 5 minutes |
| Body not JSON / envelope invalid | nothing | log `error` with validation path, `200` |
| One message unparseable | `UNSUPPORTED_MEDIA` reply (S5) | inbox row `kind=unsupported` |
| Database down during webhook | nothing yet; Meta retries | `503` from the handler (not 200: this one *should* be retried); log `error` |
| Duplicate delivery from Meta | one reply | `ON CONFLICT DO NOTHING`, no NOTIFY |
| Encryption key wrong at decrypt time | no reply | `InvalidAddressCiphertext`, outbox `failed`, log `error` |
| Graph API send failure | per §4.10 | `ProviderError` subclass, outbox status per §4.10 |
| `acknowledge` fails | no blue ticks or typing dots; the reply still arrives | log `warning`, turn continues |
| Message from a number on the test-number allow list only | nothing | send fails with a 4xx (test numbers only reach registered recipients); log `error` |

## 9. Tests

**Unit** (`tests/unit/channels/whatsapp/`)
- `test_verify_signature_accepts_valid_hmac`
- `test_verify_signature_rejects_missing_header`, `…_wrong_prefix`, `…_non_hex`, `…_wrong_length`, `…_wrong_secret`: each `pytest.raises(SignatureInvalid, match=...)`
- `test_verify_subscription_returns_challenge_only_for_subscribe_with_matching_token`
- Parsing, one test per row of §4.4's type table, from fixtures `tests/fixtures/whatsapp/*.json` (text, voice note, forwarded audio, button_reply, list_reply, template button, image, sticker, reaction, unsupported with `131051`, system, status sent/delivered/read/played/failed, account-level errors, a batch with 3 messages + 2 statuses)
- `test_unknown_message_type_becomes_unsupported_not_dropped`
- `test_image_message_maps_to_image_kind_with_media_id_and_caption_text` (C7); `test_video_still_unsupported`
- Sender: an `IMAGE` part uploads then sends `type=image` with the caption; a 1025-char caption → `ValueError`; an `IMAGE` part without bytes → `ValueError`
- `test_foreign_phone_number_id_is_ignored`
- `test_reaction_is_not_stored`
- `test_profile_name_never_reaches_inbound_message`
- `classify_graph_error`: one parametrized case per row of §4.10, asserting the exact exception class and `retryable`
- Sender: request bodies built for each part kind (text, interactive, audio, template), checked against recorded JSON (`respx`); `ValueError` for 0 and 4097-char text; 4 buttons; a 21-char title; non-opus audio mime; a `TEMPLATE` part with no `template`, or with `text` set
- `test_template_quick_reply_maps_to_interactive_with_payload`: a `button` message with payload `jrn:today` → `INTERACTIVE`, `interactive_reply_id="jrn:today"`
- `test_text_send_sets_preview_url_false`
- `test_acknowledge_body_contains_typing_indicator`

**Property** (`@pytest.mark.unit`, hypothesis)
- Signature: for any body bytes and secret, a correctly computed header verifies; flipping any single byte of the body or header fails (CLAUDE.md §3).
- `strip_message_payload`: for generated `WaMessage`s with arbitrary `from` / `context.from` / `audio.url` / `image.url` / `image.caption`, the serialised result never contains the `wa_id` string, any `url` key, or the caption text.
- `parse(serialize(m)) == m` for generated `WaMessage` → our parsed form (CLAUDE.md §3 payload property); unknown `type` strings always produce `UNSUPPORTED`.
- `UserIdentity`: `decrypt(encrypt(x)) == x`; decrypting with another row's `user_hash` as associated data always raises; the same address always gives the same hash; different channels give different hashes for the same address.
- Status ordering: applying any permutation of {sent, delivered, read} ends in `read` with both timestamps set (pure function extracted from the SQL `CASE`, plus the integration test below).

**Negative (route level, `httpx.AsyncClient` against the app)**
- Bad signature → `401`, empty body, **no** users row and **no** inbox row written.
- GET with wrong token → `403`; with `hub.mode=unsubscribe` → `403`.
- Valid signature + invalid JSON → `200`, no rows written, one `error` log line containing no body bytes.
- Body over `WEBHOOK_MAX_BODY_BYTES` → `413`.
- Database unavailable → `503`.

**Integration** (`@pytest.mark.integration`, docker-compose Postgres)
- The same webhook POSTed 3 times → 1 inbox row, 1 users row, 1 NOTIFY received.
- A message, then an older retry → `last_inbound_at` keeps the newer time.
- `apply_status_update` (from S4): delivered after read leaves `read`; failed after sent sets `failed` and `last_error`; unknown id updates nothing.
- The migration upgrades, downgrades and upgrades again.

## 10. Exit check

1. Deploy the api to Fly/Railway with the S3 settings; `/healthz` is 200.
2. Save the callback URL and verify token in the App Dashboard. The handshake succeeds (the dashboard shows "verified").
3. From your phone, send "hello" to the test number. Within 2 s an `inbox_messages` row appears
   (`kind=text`), and the `users` row has a 64-char hash and a non-null ciphertext. Check with
   `psql` that **no column anywhere contains your phone number**.
4. Send a voice note → row with `kind=audio`, a `media_provider_id`, `media_mime_type` starting with `audio/ogg`.
5. Send a sticker → row with `kind=unsupported`.
6. Run `marg whatsapp reply-latest`. The phone receives "Marg.ai received your unsupported message."
7. `curl` the webhook with a body and a wrong signature → `401`, and no row written.

## 11. Open questions

1. **Graph API version:** pin whatever the dashboard shows as current on Day 1. *Recommendation:* the newest stable version.
2. **Real number vs test number:** the sender doesn't care. Only `WHATSAPP_PHONE_NUMBER_ID` changes. *Recommendation:* start on the test number, switch once the display name is approved (plan.md §4.1).
3. **User changed their number** (`system` message): their history stays under the old hash.
   *Recommendation:* ignore for the MVP, and document it.
4. **Voice-note look for outbound audio:** confirm on a real phone in S6 (§4.9).

## Contract changes (resolved 2026-10-25)

- `ChannelSender.acknowledge(external_id)` and `send(part, recipient, audio)`: **applied** (contracts §3).
- `InvalidAddressCiphertext(ChannelError)`: **applied** (contracts §4).
- `WEBHOOK_MAX_BODY_BYTES = 5_000_000`: **applied** (contracts §7).
- `extra="ignore"` for the webhook models only: **applied** (contracts preamble).
- Added by the consolidation (decision B12): `PartKind.TEMPLATE` and `TemplateRef` (contracts §1,
  §2.6), and `outbox_messages.template` (data-model.md). The sender implements them in §4.9.

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-25 | Requested contract changes applied; added `TEMPLATE` part sending and the template quick-reply link for s10b nudges; template error codes marked for verification | Consolidation against the updated foundation docs; parent journey (B12) | owner |
| 2026-10-26 | WhatsApp `image` messages map to `MessageKind.IMAGE` (media id, mime, caption → text; url and caption never kept in `raw_payload`); `IMAGE` parts can be sent (upload, then `type=image` with a caption ≤ 1024 chars) | Owner decisions C6 (khoj card) and C7 (activity photos) | owner |
