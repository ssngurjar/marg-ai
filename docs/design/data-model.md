# Data model

Every table in one place. Step docs say which tables they read and write; the columns are
defined only here. A table is created by the Alembic migration of the step named in the
**Owner** column, and changed only by a later migration. A column that references a table created
in a later step (for example `inbox_messages.media_blob_id`) is added by that later step's migration.

PostgreSQL 16 with the `vector` extension. Conventions: `snake_case`; `timestamptz` for all
times (UTC); `numeric` for money; enums are stored as `text` with a `CHECK` constraint listing
the `StrEnum` values from [contracts.md](contracts.md) §1, and arrays of enum values use
`CHECK (col <@ ARRAY[...]::text[])`. Adding a value means a migration that updates the check,
which keeps Python and the database in step.

## 1. Overview

```
users ─┬─< inbox_messages >── turns ─┬─< turn_steps
       │                             ├─< outbox_messages
       │                             ├── aspiration_signals   (student turns)
       │                             └── curiosity_signals    (parent-journey turns)
       ├─< consent_events
       ├── profile_memory
       ├─< roadmaps ─< roadmap_steps
       ├─< media_blobs
       ├── nudge_subscriptions
       └─< learners ─< learner_activities
corpus_documents ─< corpus_chunks
rate_limit_counters
```

**The learner is the unit the journey tracks** (s10b). A parent's children and a student
themself are `learners`. Teachers have none. Each learner is owned by exactly one user in the MVP
(`owner_user_hash`). A second guide (a teacher, or the child's own number later) is a future link
table, not a change to this one.

`users.user_hash` is the key everything hangs off. **Deleting a user deletes every row that
references them**, directly or through `learners` (`ON DELETE CASCADE` on every foreign key to
`users` and `learners`). That's how delete-my-data works (s08), and an integration test checks
through `information_schema` that no table is missed.

## 2. Tables

### `users` (S3, extended in S4 and S8)

| Column | Type | Notes |
|---|---|---|
| `user_hash` | `text` PK | 64 hex chars. `HMAC-SHA256(USER_HASH_SALT, "<channel>:<address>")` |
| `channel` | `text` | `Channel` |
| `address_ciphertext` | `bytea` NULL | `nonce(12) ‖ AES-256-GCM(wa_id, aad=user_hash)`. NULL for web. See §3 |
| `state` | `text` | `ConversationState`, default `new` |
| `role` | `text` NULL | `Role` |
| `grade` | `smallint` NULL | `CHECK (grade BETWEEN 1 AND 12)`; students and teachers |
| `subject` | `text` NULL | teachers |
| `district` | `text` NULL | students and teachers, as said (2–60 chars); not asked of parents |
| `language` | `text` NULL | `Language` |
| `guardian_confirmed` | `boolean` | default false |
| `consented_at` | `timestamptz` NULL | |
| `pending_question` | `text` NULL | (S8) a question asked before onboarding finished; cleared on handoff. Personal data |
| `last_inbound_at` | `timestamptz` NULL | WhatsApp 24h window |
| `lease_owner` | `text` NULL | worker id holding the turn lease (S4) |
| `lease_expires_at` | `timestamptz` NULL | (S4) |
| `purge_after_turn_id` | `uuid` NULL | (S8) set by `MarkPurgeAfterDelivery`; the user is deleted once that turn's last part is delivered, or by the sweep after `PURGE_SWEEP_AFTER_S` |
| `created_at` / `updated_at` | `timestamptz` | |

Indexes: `(lease_expires_at)` partial `WHERE lease_owner IS NOT NULL`; `(purge_after_turn_id)`
partial `WHERE purge_after_turn_id IS NOT NULL`.

### `consent_events` (S8)

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` identity PK | |
| `user_hash` | `text` FK → users CASCADE | |
| `kind` | `text` | `ConsentEventKind` |
| `prompt_version` | `text` | version of the consent copy shown (`COPY_VERSION`) |
| `recorded_at` | `timestamptz` | |

### `learners` (S8 creates; used by S10b, S13)

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | `LearnerId` |
| `owner_user_hash` | `text` FK → users CASCADE | the parent, or the student themself |
| `relation` | `text` | `LearnerRelation` |
| `nickname` | `text` NULL | ≤ 20 chars, optional; never a full name (s10b §4.2) |
| `birth_year` | `smallint` | `CHECK (birth_year BETWEEN 2000 AND 2100)` as a sanity bound; the real range (age 2–19 today) is validated in code (`InvalidProfileValue`) |
| `child_talk_consented_at` | `timestamptz` NULL | the parent's one-time consent for direct child talk (C13); NULL = child talk off |
| `created_at` / `updated_at` | `timestamptz` | |

Constraints: at most 3 learners per owner, enforced by the repository inside the finalize
transaction, which already holds the user's row lock (it counts, then inserts);
`UNIQUE (owner_user_hash)` partial `WHERE relation = 'self'`. A student
gets their `self` learner when onboarding completes, with `birth_year` estimated from grade
(`current_year − grade − 6`, marked as an estimate in s08) so the trajectory spans ages from day one.

### `inbox_messages` (S3 creates, S4 adds processing columns, S6 adds `media_blob_id`)

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` identity PK | |
| `channel` | `text` | |
| `external_id` | `text` | wamid / web uuid |
| `user_hash` | `text` FK → users CASCADE | |
| `kind` | `text` | `MessageKind` |
| `text` | `text` NULL | |
| `media_provider_id` | `text` NULL | WhatsApp media id |
| `media_blob_id` | `uuid` NULL FK → media_blobs SET NULL | web upload (S6) |
| `media_mime_type` | `text` NULL | |
| `interactive_reply_id` | `text` NULL | |
| `raw_payload` | `jsonb` NULL | allowlisted, PII-free (s03 §4.7). Cleared after `RETENTION_RAW_PAYLOAD_DAYS` |
| `status` | `text` | `InboxStatus`, default `pending` |
| `attempts` | `smallint` | default 0 (S4) |
| `available_at` | `timestamptz` | default now(); pushed forward for retry backoff (S4) |
| `turn_id` | `uuid` NULL FK → turns SET NULL | set when combined into a turn (S4) |
| `provider_sent_at` | `timestamptz` | |
| `received_at` | `timestamptz` | default now() |

Constraints: `UNIQUE (channel, external_id)`. Indexes: `(status, available_at)` partial `WHERE
status = 'pending'`; `(user_hash, status)`.

### `turns` (S4)

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | `TurnId` |
| `user_hash` | `text` FK → users CASCADE | |
| `learner_id` | `uuid` NULL FK → learners SET NULL | `TurnContext.active_learner` (S10b adds) |
| `status` | `text` | `TurnStatus`. `completed` even with a fallback reply; `failed` = crashed or abandoned |
| `route` | `text` NULL | `Route`; written when known (via `StepRecorder.set_turn_route`) |
| `user_text` | `text` NULL | combined transcript/text, written after transcription. **Set to NULL at finalize for `fixed_reply_kind = 'crisis'`**. Otherwise cleared after `RETENTION_TURN_TEXT_DAYS` |
| `reply_text` | `text` NULL | `SafeReply.text`; same retention |
| `reply_register` | `text` NULL | `Language` |
| `fixed_reply_kind` | `text` NULL | `FixedReplyKind` |
| `prompt_versions` | `jsonb` | `{prompt_id: version}` |
| `failure_step` / `failure_kind` | `text` NULL | first failure, if any |
| `worker_id` | `text` | |
| `started_at` / `completed_at` | `timestamptz` | |

Indexes: `(user_hash, started_at DESC)`; `(started_at)`.

### `turn_steps` (S4 creates, written from S5)

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` identity PK | |
| `turn_id` | `uuid` FK → turns CASCADE | |
| `step` | `text` | `StepName` |
| `outcome` | `text` | `StepOutcome` |
| `failure_kind` | `text` NULL | `FailureKind` |
| `decision` | `text` NULL | `SafetyDecision`, for `safety_in`/`safety_out` rows only (s07, used by the s14 trace) |
| `detail` | `text` NULL | fixed vocabulary only, no PII |
| `provider` / `model` | `text` NULL | |
| `input_tokens` / `output_tokens` | `integer` NULL | |
| `audio_seconds` | `numeric(10,3)` NULL | |
| `cost_usd` | `numeric(12,6)` | default 0 |
| `started_at` | `timestamptz` | |
| `duration_ms` | `integer` | |

Indexes: `(turn_id)`, `(started_at)`. Each insert runs `pg_notify('turn_progress', '<turn_id>')` (s14).

### `outbox_messages` (S4)

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` identity PK | |
| `turn_id` | `uuid` FK → turns CASCADE | |
| `part_no` | `smallint` | |
| `user_hash` | `text` FK → users CASCADE | |
| `channel` | `text` | |
| `kind` | `text` | `PartKind` |
| `text` | `text` NULL | |
| `audio_blob_id` | `uuid` NULL FK → media_blobs SET NULL | |
| `image_blob_id` | `uuid` NULL FK → media_blobs SET NULL | khoj card (S10b) |
| `buttons` | `jsonb` | `list[ReplyButton]`, default `[]` |
| `template` | `jsonb` NULL | `TemplateRef` for `kind = 'template'` (S10b) |
| `status` | `text` | `OutboxStatus` |
| `attempts` | `smallint` | |
| `available_at` | `timestamptz` | backoff scheduling |
| `sending_since` | `timestamptz` NULL | set on claim; stuck-send recovery after `OUTBOX_SENDING_STUCK_S` |
| `provider_message_id` | `text` NULL UNIQUE | wamid, matched by status webhooks |
| `last_error` | `text` NULL | no PII |
| `created_at` / `sent_at` / `delivered_at` / `read_at` | `timestamptz` NULL | |

Constraints: `UNIQUE (turn_id, part_no)`. Index: `(status, available_at)` partial
`WHERE status IN ('pending','sending')`. Parts of one turn are delivered strictly in `part_no` order.
`mark_sent` for web parts also runs `pg_notify('turn_progress', turn_id)`.

### `media_blobs` (S6)

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `user_hash` | `text` FK → users CASCADE | |
| `purpose` | `text` | `MediaPurpose` |
| `mime_type` | `text` | |
| `data` | `bytea` | `CHECK (size_bytes <= 2097152)` |
| `size_bytes` | `integer` | |
| `created_at` / `expires_at` | `timestamptz` | inbound (web) audio: deleted by `DeleteInboundMedia` once transcribed, at most 24 h; inbound (web) photo: deleted by `DeleteInboundMedia` with the turn that looked at it, at most 10 minutes; reply audio: 24 h; khoj card: 7 days |

Index: `(expires_at)`. WhatsApp inbound audio and photos are never stored. **A photo is never kept beyond its turn on any channel** (s10b §4.14): a web visitor's photo waits here (purpose `inbound_photo`) only until its turn has looked at it, and is deleted in that turn's finalize, used or refused (owner, 2026-10-28).

### `profile_memory` (S12)

| Column | Type | Notes |
|---|---|---|
| `user_hash` | `text` PK FK → users CASCADE | |
| `summary` | `text` | ≤ 600 chars |
| `ambitions` / `constraints` | `text[]` | ≤ 5 each |
| `source_turn_id` | `uuid` NULL | |
| `prompt_version` | `text` | |
| `updated_at` | `timestamptz` | |

### `roadmaps` and `roadmap_steps` (S12)

`roadmaps`: `id uuid PK`, `user_hash FK CASCADE`, `goal text`, `status text (RoadmapStatus)`,
`prompt_version text`, `created_at`, `updated_at`. At most one `active` per user (partial unique index).

`roadmap_steps`: `id uuid PK`, `roadmap_id FK CASCADE`, `position smallint`, `action text`,
`timeframe text` (as spoken: "this week", "before March"), `cost_inr numeric(12,2) NULL`,
`source_url text NULL`, `status text (RoadmapStepStatus)`, `completed_at timestamptz NULL`.
`UNIQUE (roadmap_id, position)`. (Progress updates are deferred; steps stay `todo` in the MVP.)

### `learner_activities` (S10b)

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `learner_id` | `uuid` FK → learners CASCADE | |
| `activity_id` | `text` | catalogue slug (`content/activities/*.yaml`) |
| `activity_version` | `text` | catalogue entry version at the time it was offered |
| `offered_turn_id` | `uuid` FK → turns CASCADE | |
| `status` | `text` | `ActivityStatus` |
| `child_response_summary` | `text` NULL | ≤ 200 chars, from the parent's report; cleared after `RETENTION_TURN_TEXT_DAYS` |
| `photo_findings` | `jsonb` NULL | `list[ObjectCount]` from a photo of what the child made or collected (counts only, never the image) |
| `card_blob_id` | `uuid` NULL FK → media_blobs SET NULL | the khoj card, if one was made |
| `offered_at` / `reported_at` | `timestamptz` | |

Index: `(learner_id, offered_at DESC)`.

### `child_sessions` (S10b, C13)

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `learner_id` | `uuid` FK → learners CASCADE | |
| `user_hash` | `text` FK → users CASCADE | the parent's account the child is using |
| `started_at` / `ended_at` | `timestamptz` | `ended_at` NULL while open |
| `turns_count` | `smallint` | |
| `end_reason` | `text` NULL | `ChildSessionEndReason` |
| `topics` | `text[]` | `CuriosityDomain` values touched, for the parent summary (no transcripts) |
| `summary_sent_at` | `timestamptz` NULL | |

Indexes: `(learner_id, started_at DESC)`; at most one open session per learner (partial unique
index `WHERE ended_at IS NULL`).

### `nudge_subscriptions` (S10b)

| Column | Type | Notes |
|---|---|---|
| `user_hash` | `text` PK FK → users CASCADE | parents on WhatsApp only |
| `enabled` | `boolean` | |
| `local_time` | `time` | IST, chosen by the parent ("subah 8", "shaam 6") |
| `next_due_at` | `timestamptz` | |
| `last_sent_at` | `timestamptz` NULL | |
| `opted_in_at` / `opted_out_at` | `timestamptz` NULL | |

Index: `(next_due_at)` partial `WHERE enabled`.

### `aspiration_signals` (S13)

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` identity PK | |
| `turn_id` | `uuid` UNIQUE FK → turns CASCADE | one per student turn |
| `learner_id` | `uuid` FK → learners CASCADE | the student's `self` learner |
| `fields` | `text[]` | `AspirationField` values, ≤ 3 |
| `specificity` | `smallint` | `CHECK (specificity BETWEEN 0 AND 4)` |
| `constraints` | `text[]` | `ConstraintKind` values, ≤ 3 |
| `sentiment` | `text` | `Sentiment` |
| `prompt_version` | `text` | |
| `extracted_at` | `timestamptz` | |

Index: `(learner_id)`.

### `curiosity_signals` (S13, for parent-journey turns)

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` identity PK | |
| `turn_id` | `uuid` UNIQUE FK → turns CASCADE | one per parent report turn |
| `learner_id` | `uuid` FK → learners CASCADE | the child |
| `domains` | `text[]` | `CuriosityDomain` values, ≤ 3: what the child engaged with |
| `engagement` | `smallint` | `CHECK (engagement BETWEEN 0 AND 3)`: 0 no response · 1 brief · 2 engaged · 3 extended or new idea |
| `child_asked_question` | `boolean` | the child asked their own question, the key early-curiosity signal |
| `prompt_version` | `text` | |
| `extracted_at` | `timestamptz` | |

Index: `(learner_id)`.

### `corpus_documents` and `corpus_chunks` (S11)

`corpus_documents`: `id uuid PK`, `path text UNIQUE` (repo-relative), `title`, `source_url`,
`retrieved_on date`, `topic text`, `language text NOT NULL DEFAULT 'english'`, `grades smallint[]`,
`keywords text[]` (stored upper-cased), `content_sha256 text`, `ingested_at`.

`corpus_chunks`: `id uuid PK`, `document_id FK CASCADE`, `position smallint`, `heading_path text NOT NULL`,
`text`, `embedding vector(384)`, `tsv tsvector` (generated, `simple` config),
`UNIQUE (document_id, position)`. Indexes: HNSW on `embedding vector_cosine_ops`; GIN on `tsv`.

These aren't user data: no `user_hash`, and they survive user deletion. `corpus/curriculum/`
(s10) and `content/activities/` (s10b) are loaded at startup from files and never ingested here.

### `rate_limit_counters` (S14)

`key text`, `window_start timestamptz`, `count integer`, `PRIMARY KEY (key, window_start)`.
Keys: `demo:session:<user_hash>`, `demo:ip:<HMAC(salt, ip)>`, `demo:session-create:<ip hash>`.
Old windows are pruned by maintenance.

### View `turn_metrics` (S13)

One row per turn: `turn_id`, `user_hash`, `route`, `status`, `fixed_reply_kind`, `failure_step`,
`failure_kind`, `started_at`, first inbound `received_at`, first outbound `sent_at`,
`user_latency_ms`, summed `cost_usd`, `served_ok`. Exact SQL in s13 §4.1.

## 3. Personal data and encryption (decision A1, approved)

- Replying on WhatsApp needs the real phone number. `users.address_ciphertext` holds it encrypted
  with **AES-256-GCM** (`ADDRESS_ENCRYPTION_KEY`, a random 96-bit nonce per row, `user_hash` as
  associated data so a ciphertext copied to another row fails to decrypt). It's decrypted only by
  the outbox loop just before sending, into a `SecretStr`.
- Lookups use `user_hash` only. Logs, telemetry, `turn_steps.detail` and `raw_payload` never
  contain the number.
- **Children's data** (s10b): only an optional nickname (≤ 20 chars) and a birth year. No school
  name, no full name, no exact date of birth. A child's voice in a parent's voice note is
  transcribed and never stored (WhatsApp audio is never persisted). **Photos (C7):** a parent may
  send a photo of what the child made or collected. It is checked for people **first**; a photo
  containing a person is rejected and dropped without any other processing. Otherwise only object
  counts are kept. **No photo is ever kept beyond its turn** (a web photo waits in `media_blobs`
  until its turn has looked at it, at most 10 minutes). Khoj cards are generated illustrations with no
  photo of the child. `child_response_summary` is
  capped at 200 characters and follows turn-text retention.
- Personal data here: `address_ciphertext`, `pending_question`, `turns.user_text`, `turns.reply_text`,
  `media_blobs`, `profile_memory`, `roadmaps`, `learners`, `learner_activities.child_response_summary`.
  All of it cascades on deletion and is subject to retention.

## 4. Retention (worker maintenance loop, S4 + S16)

| Data | Kept for |
|---|---|
| Inbound audio (web `media_blobs` `inbound_audio`) | Until transcribed, at most 24 h |
| Reply audio | 24 h |
| `inbox_messages.raw_payload` | `RETENTION_RAW_PAYLOAD_DAYS` (7), then NULL |
| `turns.user_text`, `reply_text`, `learner_activities.child_response_summary` | `RETENTION_TURN_TEXT_DAYS` (90), then NULL |
| Crisis-turn `user_text` | never stored (NULL at finalize) |
| Telemetry (`turn_steps`, `aspiration_signals`, `curiosity_signals`) | kept; contains no text |
| Everything for a user | deleted after a confirmed delete-my-data, once the confirmation is delivered (sweep after 10 min at most) |

## 5. Migrations

One Alembic revision per step that changes the schema, named `sNN_<what>` (e.g.
`s04_queue_tables`, `s10b_journey`). Every migration has a working `downgrade`. CI runs
upgrade → downgrade → upgrade against `docker-compose.test.yml`.

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-27 | `s04_queue_tables`: `turns`, `turn_steps`, `outbox_messages`, inbox `attempts`/`available_at`/`turn_id`. Under E1 the `users` lease columns aren't added (Phase 2). `outbox_messages.audio_blob_id`/`image_blob_id` get their FK to `media_blobs` in S6, which creates that table | Exception E1; staged tables | owner (S4 review) |
| 2026-10-25 | v1 written | foundation | owner |
| 2026-10-25 | Added `users.pending_question`, `users.purge_after_turn_id`, `outbox_messages.sending_since`, `outbox_messages.template`, `turn_steps.decision`, `corpus_chunks.heading_path`, `corpus_documents.language`, the `turn_metrics` view; crisis `user_text` NULL | Requested by s04, s07, s08, s11, s13, s14 | owner (defaults 1–10) |
| 2026-10-25 | Added `learners`, `learner_activities`, `nudge_subscriptions`, `curiosity_signals`, `turns.learner_id`; `aspiration_signals` keyed by `learner_id` | Parent journey and learner-centred model | owner |
| 2026-10-26 | `child_sessions`, `learners.child_talk_consented_at` | Owner decision C13 (direct child talk) | owner |
| 2026-10-26 | `outbox_messages.image_blob_id`, `learner_activities.photo_findings` and `card_blob_id`, `media_blobs` purpose `khoj_card`; the photo rules in §3 | Owner decisions C6, C7 | owner |
| 2026-10-25 | Dropped the proposed `classrooms` table and `users.classroom_id` | Classroom codes trimmed; teachers see district aggregates | owner |
| 2026-10-27 | `s10b_child_sessions`: the partial unique index is on `user_hash` (one open session per account), not `learner_id` | One phone, one child talking at a time | pending owner review |
| 2026-10-27 | `s13_curiosity_signals`: adds `source` (parent_report, child_words, relayed_question) so child-talk and relayed questions can be told apart from reports | S13 build | pending owner review |
| 2026-10-27 | `s10b_khoj_cards`: `learner_activities.card_blob_id` (FK media_blobs SET NULL); card images kept 7 days | S10b build | pending owner review |
| 2026-10-27 | `s14_web_demo`: `inbox_messages.media_blob_id` (web voice notes) and `rate_limit_counters` | S14 build | pending owner review |
| 2026-10-28 | `s10b_photos`: `learner_activities.photo_findings` (jsonb, `list[ObjectCount]`) and the `media_blobs` purpose `inbound_photo`; the photo rule becomes "never kept beyond its turn": a web photo is held until its turn has looked at it (≤ 10 min) and deleted in that turn's finalize | Owner decision (web photos, 2026-10-28) | owner |
| 2026-10-28 | `s13_turn_metrics`: the `turn_metrics` view (s13 §4.1), read by `/status` | S13 build | pending owner review |
| 2026-10-28 | `s11_corpus_tables` (pgvector, HNSW cosine + GIN tsv; keywords upper-cased) and `s12_roadmaps_memory` (one active roadmap per user by a partial unique index; cascades) | S11, S12 build | pending owner review |
