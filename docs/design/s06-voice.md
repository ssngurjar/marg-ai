# S6 — Voice: media, transcoding, speech-to-text, text-to-speech

> **Hackathon build level: Full.** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

## 1. Purpose

S6 makes Marg.ai voice-first:
1. A WhatsApp voice note (or a web recording) is fetched and checked for duration and silence.
2. It's converted to the WAV format Muse Voice Transcribe requires, then transcribed.
3. The reply's `spoken_text` is synthesized with Meta MMS-TTS on the ML sidecar.
4. The result is converted to OGG/Opus, stored briefly, and delivered as a voice note **before** the text.

**Exit:** a voice note in gets a voice note back, followed by the text.

## 2. Read first

- [00-overview.md](00-overview.md): §2 (the ML sidecar), §4 (steps `fetch_media`, `transcribe`, `synthesize`)
- [contracts.md](contracts.md): `MediaRef`, `AudioClip`, `Transcript`, the ports `MediaFetcher`,
  `Transcriber`, `Synthesizer`, `Embedder`, `TranscriptionHints`, `StepUsage`; enums `MediaPurpose`,
  `FailureKind`; §7 settings `MODEL_STT`, `SIDECAR_*`, `STT_FALLBACK_ENABLED`
- [data-model.md](data-model.md): `media_blobs`, `inbox_messages.media_*`, retention §4
- [s05-llm-orchestrator.md](s05-llm-orchestrator.md): §4.5 (flow and budgets), §4.7 (`build_parts`, AUDIO is part 0), `TurnWrite`
- [s03-whatsapp-ingress-auth.md](s03-whatsapp-ingress-auth.md): the Graph API client and media upload at send time
- [s09-translation.md](s09-translation.md): `spoken_text`. The script rule in §4.6 below is a requirement on S9
- plan.md §4.2 (voice), §0 (Muse Voice Transcribe, MMS-TTS); CLAUDE.md §12 (subprocess rules)

## 3. Scope

**In S6:**
- `app/channels/whatsapp/media.py`: `WhatsAppMediaFetcher`
- `app/providers/speech/blob_fetcher.py`: `BlobMediaFetcher` (web uploads)
- `app/providers/speech/composite_fetcher.py`: chooses between the two
- `app/audio/transcode.py`, `app/audio/analysis.py`: duration and voice-activity checks
- `app/providers/speech/muse_transcribe.py`, `whisper_sidecar.py`, `fallback.py`
- `app/providers/speech/mms_tts.py`
- `app/audio/tts_text.py`: preparing text for TTS. It replaces `audio/transliterate.py` (renamed
  in plan.md §9 and CLAUDE.md §3); see §4.6
- `app/domain/language.py`: `detect_register`, the **single** register detector. s08 (first
  contact) and s09 (register choice) import it from here; nothing else defines one
- `app/audio/keywords.py`: speech-recognition keyword hints
- `services/ml_sidecar/app.py`: `/tts`, `/embed` (used by S11), and `/stt` (fallback)
- the `media_blobs` table, and the `inbox_messages.media_blob_id` column (migration `s06_media_blobs`)
- the step functions `fetch_media`, `transcribe`, `synthesize` registered in `PipelineSteps`

**Out:**
| Item | Owner |
|---|---|
| Uploading reply audio to WhatsApp (`POST /{phone_number_id}/media`) and sending the audio message | S3's sender, called by S4's outbox delivery |
| Web recording, upload and audio playback | S14 (it writes `media_blobs` `INBOUND_AUDIO` and serves `REPLY_AUDIO`) |
| Writing `spoken_text` | S9 |
| Embeddings use | S11 (S6 only builds and deploys the `/embed` endpoint) |

## 4. Design

### 4.1 Voice turn sequence

```
worker / run_turn                     WhatsApp Graph            ml-sidecar (Modal)     Model API
 │ fetch_media(ref)                       │                          │                    │
 │──GET /{media_id} (Bearer) ───────────▶│                          │                    │
 │◀─{url, mime_type, sha256, file_size}──│                          │                    │
 │──GET url (Bearer, ≤ 5 min validity) ─▶│                          │                    │
 │◀─ogg/opus bytes ──────────────────────│                          │                    │
 │ check size, sha256                                                │                    │
 │ transcribe(clip)                                                  │                    │
 │   to_stt_wav (ffmpeg) → analyse (duration, voice activity)       │                    │
 │──POST /v1/asr/transcribe (multipart: request JSON + WAV) ─────────────────────────────▶│
 │◀─{sessionId, transcript, audioDurationMs, turns[]} ───────────────────────────────────│
 │ detect_register(transcript)                                       │                    │
 │ … safety_in ‖ route → generate → translate …                      │                    │
 │ synthesize(spoken_text)   (speculative, alongside safety_out)     │                    │
 │   prepare_tts_text → sentences                                    │                    │
 │──POST /tts {sentences, language} (Bearer SIDECAR_TOKEN) ────────▶│                    │
 │◀─audio/wav (16-bit mono) ─────────────────────────────────────────│                    │
 │   to_voice_note (ffmpeg → ogg/opus mono 48 kHz)                                         │
 │   save media_blobs REPLY_AUDIO (expires 24 h) → blob_id                                 │
 │ build_parts: part 0 AUDIO(blob_id), parts 1.. TEXT                                       │
```

If `safety_out` blocks, the speculative audio is never delivered (s05 §4.5). Its blob is deleted
in the same turn: no `media_blobs` row is created until safety has passed, and the clip stays in
memory until then.

### 4.2 Fetching media

`WhatsAppMediaFetcher.fetch(ref)` (verified against Meta's media reference on 2026-10-25):
1. `GET {WHATSAPP_GRAPH_BASE_URL}/{ref.provider_media_id}` with `Authorization: Bearer
   WHATSAPP_ACCESS_TOKEN` → `{url, mime_type, sha256, file_size, id}`. Parse into a private
   Pydantic model `MediaInfo`.
2. Refuse before downloading if `file_size > MAX_INBOUND_AUDIO_BYTES` (default 5 MB; WhatsApp
   allows up to 16 MB, but a 3-minute voice note is well under 1 MB) →
   `MediaTooLarge` → `FailureKind.UNSUPPORTED_INPUT`.
3. `GET url` with the same Bearer header (the download fails without it). The URL expires after
   5 minutes. On `404`, re-query step 1 once, then fail.
4. Stream the download and stop reading past `MAX_INBOUND_AUDIO_BYTES`, so a wrong `file_size`
   can't exhaust memory.
5. Check the SHA-256 against `sha256`. A mismatch → `ProviderResponseInvalid(retryable=True)`.
6. Return `AudioClip(data, mime_type, duration_ms=None)`.

Errors map through the shared HTTP layer (contracts §4). Webhook media ids expire after 7 days.
That's irrelevant for live turns, but it means a replay of an old inbox row fails cleanly with `ProviderRejected`.

`BlobMediaFetcher.fetch(ref)` reads `media_blobs` by `ref.blob_id`. If the row is missing →
`NotFound` → `FailureKind.EMPTY_INPUT` (it was expired or deleted).

`CompositeMediaFetcher` dispatches on which of `provider_media_id` / `blob_id` is set. The
`MediaRef` validator guarantees exactly one.

### 4.3 Transcoding (`app/audio/transcode.py`)

All ffmpeg calls use `asyncio.create_subprocess_exec` with an argument list (never
`shell=True`), stdin and stdout pipes, and `proc.communicate(input=data)` inside
`asyncio.timeout(TRANSCODE_TIMEOUT_S)` (default 5 s). On timeout: `proc.kill()`, `await
proc.wait()`, raise `TranscodeFailed("ffmpeg timed out")`. A non-zero exit raises
`TranscodeFailed` with the **last 300 bytes of stderr** (ffmpeg's error text says nothing about
the audio content). Input arrives on `pipe:0` and output leaves on `pipe:1`, so there are no
temp files. stdin is the data itself, so `-nostdin` isn't used.

| Function | Purpose | Exact arguments |
|---|---|---|
| `to_stt_wav(clip) -> AudioClip` | Any input (ogg/opus from WhatsApp, webm/opus from browsers, wav) → what `/v1/asr/transcribe` requires: RIFF/WAVE, mono, 16-bit PCM, 16 kHz | `ffmpeg -hide_banner -loglevel error -i pipe:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le -f wav pipe:1` |
| `to_voice_note(clip) -> AudioClip` | Sidecar WAV → WhatsApp voice-note format (`audio/ogg`, Opus codec, mono) | `ffmpeg -hide_banner -loglevel error -i pipe:0 -vn -ac 1 -ar 48000 -c:a libopus -b:a 24k -application voip -f ogg pipe:1` |

- `to_stt_wav` output is checked with the standard-library `wave` module: 1 channel, sample
  width 2, rate 16000. Anything else → `TranscodeFailed`.
- `to_voice_note` output has its mime type set to `"audio/ogg; codecs=opus"`.
- 16 kHz is used rather than 24 kHz because both are accepted, and 16 kHz is a third smaller with
  no loss for speech that came in as low-bitrate Opus.
- **Startup readiness** (S16's `/readyz` calls this): `ffmpeg -hide_banner -encoders` must list
  `libopus` and `pcm_s16le`. If it doesn't → `ConfigError("ffmpeg lacks libopus")`.
- `WhatsApp → browser` playback (S14) uses the same OGG/Opus. All current browsers except older
  Safari play it; S14 decides whether it needs an MP3 variant.

### 4.4 Duration and voice-activity checks (`app/audio/analysis.py`)

These are pure functions over the 16 kHz mono PCM from `to_stt_wav`. They use the standard
library only: `array('h')` and `math`, because `audioop` was removed in Python 3.13.

```python
@dataclass(frozen=True)
class AudioStats:
    duration_ms: int
    voiced_ms: int              # sum of 20 ms frames whose RMS is above the threshold
    peak_dbfs: float

def analyse_pcm16(pcm: bytes, sample_rate: int) -> AudioStats: ...
def admissible(stats: AudioStats, settings: Settings) -> AudioVerdict: ...
```

`AudioVerdict` is `OK` / `TOO_SHORT` / `SILENT` / `TOO_LONG`:

| Condition | Verdict | Step result | Reply |
|---|---|---|---|
| `duration_ms < MIN_VOICE_NOTE_MS` (700) | `TOO_SHORT` | `StepFailure(TRANSCRIBE, EMPTY_INPUT)` | `REPEAT_PLEASE` |
| `voiced_ms < MIN_VOICED_MS` (300), i.e. silence, or just a fan | `SILENT` | `StepFailure(TRANSCRIBE, EMPTY_INPUT)` | `REPEAT_PLEASE` |
| `duration_ms > MAX_VOICE_NOTE_SECONDS × 1000` (180 s) | `TOO_LONG` | `StepFailure(TRANSCRIBE, UNSUPPORTED_INPUT, detail="duration cap")` | `TOO_LONG` (C5 in s05) |
| otherwise | `OK` | continue to the API | — |

- The frame threshold is −45 dBFS RMS. It starts as a constant and is calibrated on the S0
  samples in S2: sample-10 (silence) must be `SILENT`, and samples 1–9 must be `OK`.
- The check runs **before** the API call, so silent notes cost nothing and reply faster.
- Long notes are refused, not truncated (CLAUDE.md §4). The `TOO_LONG` reply asks the user to
  send a shorter message, or to split it into two.

### 4.5 Speech-to-text

**`MuseVoiceTranscriber`** (`app/providers/speech/muse_transcribe.py`) satisfies `Transcriber`.
Verified against the dev.meta.ai voice docs on 2026-10-25:

- `POST {MODEL_API_BASE_URL}/asr/transcribe?sessionId=<turn_id>` (the turn id isn't PII, and it
  correlates with Meta's server logs for support).
- Headers: `Authorization: Bearer MODEL_API_KEY`, `Accept: application/json`.
- `multipart/form-data` with two parts:
  - `request` (`application/json`):
    `{"model": MODEL_STT, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK", "keywords": hints.keywords, "languageBias": ["Hindi", "English"]}`
  - `audio` (`audio/wav`): the 16 kHz mono PCM16 WAV.
- Limits: 10 minutes of audio, 32 MB body. Our 180-second cap is far inside both.
- Response (`TranscribeResponse`): `sessionId: str`, `transcript: str`, `audioDurationMs: int`,
  `turns: list[Turn]` (empty in `PUSH_TO_TALK`). Parse into a private model with `extra="ignore"`:
  this is a provider response, so new fields must not break us. Only these four fields are read.
- **The response has no language and no confidence field.** `Transcript.language` comes from
  `detect_register(transcript)` (below), and `Transcript.confidence` is always `None` for this provider.
- An empty or whitespace-only `transcript` → `StepFailure(EMPTY_INPUT)` → `REPEAT_PLEASE`.
- Error statuses: `400` (unsupported WAV or too long) → `ProviderRejected`; `406`, `413` →
  `ProviderRejected`; `429` → `ProviderRateLimited`; `500` → `ProviderUnavailable`. All go
  through the shared retry policy.
- **Usage:** `audio_seconds = Decimal(audioDurationMs // 1000)`. The pricing page says audio is
  billed rounded down to whole seconds. `cost_usd = audio_seconds × Decimal("0.18") / 3600`,
  rounded to 6 places. `provider="meta_model_api"`, `model=MODEL_STT`.

**Hints** (`app/audio/keywords.py`):
- `STT_KEYWORDS`: a reviewed, versioned tuple of exam, scheme and institution names, e.g. "NEET",
  "JEE", "CUET", "NMMS", "Navodaya", "Sainik School", "UPSC", "Khelo India", "Agniveer", "ITI",
  "PMKVY", "Atal Tinkering Lab", "INSPIRE", "NIOS", "scholarship".
- From S11, the hints are extended with the `keywords` frontmatter of corpus documents, deduplicated.
- Capped at `STT_MAX_KEYWORDS` (100; the API's limit isn't documented, so verify in S2).
- `languageBias` is always `["Hindi", "English"]`, which covers Hinglish code-switching.
  Supported languages (confirmed 2026-10-26) include Hindi, Bengali, Marathi, Tamil, Telugu and Kannada; Hinglish code-switching quality is measured in S2. Phase 2 languages need only `languageBias`, translation rules and a TTS voice.

**Register detection** (`app/domain/language.py`, pure; S9 may reuse it):

```python
def detect_register(text: str) -> Language | None: ...
```

- Letters are counted, ignoring digits, punctuation and emoji.
- Devanagari letters ≥ 60 % → `HINDI`.
- Latin letters ≥ 60 % → `HINGLISH` if at least two tokens are in `HINGLISH_MARKERS` (a short
  reviewed set of very common romanised Hindi words: "hai", "kya", "mujhe", "nahi", "kaise",
  "banna", "karna", "aur", "ka", "ki", "ke", "hoon", "mein"…), otherwise `ENGLISH`.
- Anything else, or fewer than 3 letters → `None`.

Whether Muse Voice Transcribe writes Hindi speech in Devanagari or in Latin script is **unknown
until the S2 spike**. Both outputs are handled by this function.

**Fallback.** `FallbackTranscriber(primary, fallback, enabled)`:
- On a `ProviderError` from the primary, if `STT_FALLBACK_ENABLED`, it calls the fallback.
- An *empty* transcript does **not** trigger the fallback; it's a valid "nothing said" result.
- The `StepUsage` reports whichever provider produced the result, and the step `detail` records
  `fallback=whisper` when it was used.
- `WhisperSidecarTranscriber` posts the same WAV to the sidecar's `/stt` endpoint.

### 4.6 Preparing text for TTS (`app/audio/tts_text.py`)

`facebook/mms-tts-hin` reads Hindi text, and a romanised Hinglish sentence ("mujhe doctor banna
hai") will be mispronounced. Three options for converting it:

| Option | Quality | Cost |
|---|---|---|
| A. **S9's translation layer writes `spoken_text` in Devanagari script** whenever the reply register is `HINDI` or `HINGLISH`, with English loanwords written phonetically ("डॉक्टर") and numbers spelled out as words | High: the model knows context and colloquial spellings | Nothing extra: it's part of a call we already make |
| B. The rule-based `indic-transliteration` library | Poor for informal Hinglish spellings ("hai" / "hain" / "h") | New dependency |
| C. AI4Bharat IndicXlit model on the sidecar | Good | Heavy sidecar dependencies, another network hop |

**Option A is adopted.** It adds no dependency and gives the best quality. The rule is now part of
the contract (contracts §2.6, `LocalisedReply.spoken_text`): Devanagari script when `register ∈
{HINDI, HINGLISH}`, plain English when `register == ENGLISH`. s09 writes it that way.

`app/audio/tts_text.py` is the deterministic gate between `spoken_text` and the sidecar:

```python
@dataclass(frozen=True)
class TtsText:
    voice: Literal["hin", "eng"]
    sentences: tuple[str, ...]           # each ≤ TTS_MAX_SENTENCE_CHARS

def prepare_tts_text(spoken_text: str, register: Language) -> TtsText: ...
```

1. Pick the voice: `hin` for `HINDI` and `HINGLISH`; `eng` for `ENGLISH` (`facebook/mms-tts-eng`).
2. NFC normalise, and collapse whitespace.
3. Remove characters the voice can't speak: emoji, symbols, markdown remnants, URLs. This is
   documented behaviour: the text is only for the synthesizer, and the user still gets the full
   text message.
4. **Script check:** for `hin`, Latin letters remaining → raise `TtsTextInvalid("latin letters
   in hindi spoken_text")` → `StepFailure(SYNTHESIZE, INVALID_RESPONSE)` → a text-only reply
   (DEGRADED). We don't synthesize garbled audio. The rate is tracked, and if S9's output trips
   it, that's an S9 prompt bug, which should show up in evals.
5. Split into sentences on `।`, `?`, `!`, `.`, and newlines. A sentence longer than
   `TTS_MAX_SENTENCE_CHARS` (250) is split further at commas or whitespace. Longer VITS inputs
   degrade quality and memory use.
6. If the total is longer than `TTS_MAX_SPOKEN_CHARS` (1200, roughly 75 s of audio), raise
   `TtsTextInvalid("spoken_text too long")` → a text-only reply. It isn't silently cut. S9's
   prompt is responsible for keeping `spoken_text` short.

These are the replacement for CLAUDE.md §3's "audio/transliterate" properties; see §9.

### 4.7 Text-to-speech adapters (`app/providers/speech/mms_tts.py`, `indic_parler_tts.py`)

**Engine choice (decision C8).** Two adapters implement the same `Synthesizer` port and call the
same sidecar `/tts` endpoint shape. `app/wiring.py` picks one by the setting
`TTS_ENGINE: Literal["mms", "indic_parler"]` (**requested**, not yet in contracts §7):

| Engine | Model | Licence | Hardware | Used when |
|---|---|---|---|---|
| `mms` | `facebook/mms-tts-hin`, `facebook/mms-tts-eng` | CC-BY-NC 4.0 (non-commercial) | CPU | the organisers confirm on Discord that it's fine for a hackathon submission (C8) |
| `indic_parler` | `ai4bharat/indic-parler-tts` (Hindi and English speakers) | Apache 2.0 | GPU (L4/A10G) | otherwise; also the commercial-safe path for Phase 2 |

The S2 spike C findings decide the default and record the organisers' answer. Everything above the
port (`prepare_tts_text`, `to_voice_note`, storage, the step) is identical for both engines.

`MmsTtsSynthesizer.synthesize(text, language)`:
- calls `prepare_tts_text`
- posts `{"voice": "hin", "sentences": [...]}` to `{SIDECAR_BASE_URL}/tts` with
  `Authorization: Bearer SIDECAR_TOKEN`
- receives `audio/wav`, then runs `to_voice_note`

The sidecar returns `X-Audio-Duration-Ms`. `StepUsage(provider="ml_sidecar",
model="facebook/mms-tts-hin" | "facebook/mms-tts-eng", audio_seconds=duration/1000,
cost_usd=Decimal("0"))`. Modal compute is billed to credits, not per request, so the cost is
recorded as 0, and Modal's own usage page is the source for that spend.

`IndicParlerSynthesizer.synthesize(text, language)` is the same flow with `{"engine":
"indic_parler", "voice": "hin" | "eng", "sentences": [...]}`; the sidecar adds the fixed speaker
description recorded in spike C, so outputs are consistent across turns. `StepUsage.model =
"ai4bharat/indic-parler-tts"`. Its devanagari input expectation is confirmed in spike C; the
`prepare_tts_text` script check applies unchanged.

**Storing reply audio.** After `safety_out` passes:
- the orchestrator saves the clip through the `ReplyAudioStore` port (contracts §3):
  `save(user_hash, clip) -> UUID`, implemented by `app/store/repositories/media_blobs.py`
- the row has `purpose=REPLY_AUDIO`, `expires_at = now + 24 h`, and `size_bytes`
- a clip over 2 MB, the table's limit, raises `MediaTooLarge` → DEGRADED text-only
- the save runs in its own short transaction before `TurnOutcome` is returned; if the turn is
  later lost, the blob simply expires

**When audio is produced:**
- for generated replies, when the turn contained at least one AUDIO message: the reply matches
  how the user spoke
- for fixed replies in voice turns too, including `REPEAT_PLEASE` and `CRISIS`
- text-only turns get text only, unless `REPLY_AUDIO_FOR_TEXT_INPUT` is true (C9, default false)

### 4.8 `media_blobs` lifecycle

| Purpose | Created by | Deleted |
|---|---|---|
| `INBOUND_AUDIO` | S14 (web upload) | through the `TurnWrite` variant `DeleteInboundMedia(blob_id)` (contracts §2.4, owned by S6), applied by S4 in finalize once transcription has succeeded. Expired rows are pruned by the worker's maintenance loop after 24 h |
| `REPLY_AUDIO` | S6 (`ReplyAudioStore`) | maintenance loop after `expires_at` (24 h). The WhatsApp sender uploads the bytes to Meta and keeps only the media id; the web plays it from `/demo/audio/{id}` until it expires |

WhatsApp inbound audio is **never stored**. It's fetched, transcribed and dropped from memory
within the turn (data-model.md §4).

### 4.9 The ML sidecar (`services/ml_sidecar/app.py`)

A Modal app serving one FastAPI ASGI app. It's deployed separately with `modal deploy
services/ml_sidecar/app.py`.

| Endpoint | Request | Response |
|---|---|---|
| `POST /tts` | JSON `{"engine": "mms" \| "indic_parler", "voice": "hin" \| "eng", "sentences": [str] (1–20 items, each 1–250 chars)}`. The sidecar loads only the engine it's deployed with and returns `422` for the other | `audio/wav`: 16-bit mono at the model's `config.sampling_rate` (read at runtime; MMS checkpoints are 16 kHz, verify in S2). 250 ms of silence between sentences. Header `X-Audio-Duration-Ms` |
| `POST /embed` | JSON `{"purpose": "query" \| "passage", "texts": [str] (1–64 items, each ≤ 2000 chars)}` | JSON `{"model": "intfloat/multilingual-e5-small", "dimensions": 384, "vectors": [[float]]}`. The sidecar adds the e5 prefixes `"query: "` / `"passage: "` and L2-normalises |
| `POST /stt` (only when the fallback is enabled) | multipart `audio` (16 kHz mono PCM16 WAV, ≤ 180 s) | JSON `{"transcript": str, "audio_duration_ms": int, "language": str \| null}` |
| `GET /healthz` | — | `{"status": "ok", "models_loaded": [...]}` |

- **Auth.** Every endpoint except `/healthz` requires `Authorization: Bearer <SIDECAR_TOKEN>`,
  compared with `hmac.compare_digest`. A wrong or missing token → `401`, logged without the
  token. The token is a Modal Secret.
- **Validation.** Requests are Pydantic models with `extra="forbid"`. Over-limit input → `422`,
  never truncated.
- **Hardware.** MMS-TTS (VITS, about 36M parameters) and e5-small both run comfortably on CPU, which
  avoids CUDA images and GPU cold starts. So with `TTS_ENGINE=mms`, `/tts` and `/embed` share one
  **CPU** class (4 vCPU, 8 GB). With `TTS_ENGINE=indic_parler` (about 0.9B parameters), `/tts` runs
  in a separate **GPU** class (L4 or A10G, per spike C), and `min_containers=1` during demos and
  judging matters even more because of GPU cold starts. Whisper `large-v3-turbo` for `/stt` needs a GPU. It's a separate class on an L4,
  deployed only if S2 decides the fallback is needed.
- **Cold starts.**
  - Model weights are downloaded **at image build time** with `Image.run_function`, so a cold
    start only loads them from disk.
  - Models are loaded once per container in `@modal.enter()`.
  - Normally `min_containers=0` and `scaledown_window=600`.
  - **For the judging window (Nov 4–8) and demos, set `min_containers=1`** on the CPU class.
  - S2 measures cold and warm latency. If warm `/tts` for a 3-sentence reply exceeds 1.5 s,
    revisit the GPU decision.
- **Licence (decision C8, superseding B10).** `facebook/mms-tts-hin` is **CC-BY-NC 4.0**
  (non-commercial), and the Official Rules require every open-source licence to be followed. MMS is
  used only if the organisers confirm it's acceptable; otherwise Indic Parler-TTS (Apache 2.0). Either
  way MMS is replaced before any commercial use, and the README states the licences of every model.
  The sidecar's `/tts` interface stays the same when the engine changes.
- **Typing.** CLAUDE.md §6 applies here too. `torch` and `transformers` objects stay inside small
  typed wrapper functions, because those libraries are partially untyped. Dependencies live in
  the sidecar image definition, never in the API image (CLAUDE.md §8).

### 4.10 Latency budget (voice turn, warm sidecar)

| Stage | p50 target |
|---|---|
| Webhook → worker claim | 0.3 s |
| `fetch_media` (2 Graph calls) | 0.5 s |
| `to_stt_wav` + analysis | 0.15 s |
| `transcribe` (15 s note) | 1.0 s |
| `safety_in` ‖ `route` | 0.6 s |
| `generate` | 2.5 s |
| `translate` | 1.5 s |
| `safety_out` ‖ `synthesize` (+ `to_voice_note`) | 1.2 s |
| Save blob, enqueue, WhatsApp upload + send audio, send text | 0.9 s |
| **Total** | **≈ 8.6 s** |

This is slightly over the 8 s p50 target in plan.md §4.2. In order of preference, the
remaining levers are:
1. merge translate into generate for single-step layers (S9's decision)
2. start the WhatsApp media upload while the text part is prepared
3. stream TTS per sentence (stretch goal)

The typing indicator sent at claim time (S3) covers the wait. S16 measures the real numbers.

## 5. Interfaces

```python
# app/channels/whatsapp/media.py
class WhatsAppMediaFetcher:                       # satisfies MediaFetcher (provider_media_id refs)
    def __init__(self, *, graph_base_url: str, access_token: SecretStr, http: httpx.AsyncClient,
                 retry: RetryPolicy, max_bytes: int) -> None: ...
    async def fetch(self, ref: MediaRef) -> AudioClip: ...

# app/providers/speech/blob_fetcher.py, composite_fetcher.py
class BlobMediaFetcher: async def fetch(self, ref: MediaRef) -> AudioClip: ...
class CompositeMediaFetcher: async def fetch(self, ref: MediaRef) -> AudioClip: ...

# app/audio/transcode.py
async def to_stt_wav(clip: AudioClip, timeout_s: float) -> AudioClip: ...
async def to_voice_note(clip: AudioClip, timeout_s: float) -> AudioClip: ...
async def check_ffmpeg() -> None: ...                                  # raises ConfigError

# app/audio/analysis.py
def analyse_pcm16(pcm: bytes, sample_rate: int) -> AudioStats: ...
def admissible(stats: AudioStats, *, min_ms: int, min_voiced_ms: int, max_ms: int) -> AudioVerdict: ...

# app/providers/speech/*.py
class MuseVoiceTranscriber:      async def transcribe(self, clip: AudioClip, hints: TranscriptionHints) -> tuple[Transcript, StepUsage]: ...
class WhisperSidecarTranscriber: async def transcribe(self, clip: AudioClip, hints: TranscriptionHints) -> tuple[Transcript, StepUsage]: ...
class FallbackTranscriber:       async def transcribe(self, clip: AudioClip, hints: TranscriptionHints) -> tuple[Transcript, StepUsage]: ...
class MmsTtsSynthesizer:         async def synthesize(self, text: str, language: Language) -> tuple[AudioClip, StepUsage]: ...
class SidecarEmbedder:           dimensions: int; async def embed(self, texts: Sequence[str], purpose: EmbedPurpose) -> list[list[float]]: ...

# app/audio/tts_text.py, app/domain/language.py
def prepare_tts_text(spoken_text: str, register: Language) -> TtsText: ...
def detect_register(text: str) -> Language | None: ...

# app/pipeline/steps.py: step functions registered in PipelineSteps (s05)
async def fetch_media_step(msg: InboundMessage, fetcher: MediaFetcher) -> StepResult[AudioClip]: ...
async def transcribe_step(clip: AudioClip, transcriber: Transcriber, hints: TranscriptionHints, settings: Settings) -> StepResult[Transcript]: ...
async def synthesize_step(reply: LocalisedReply, synthesizer: Synthesizer) -> StepResult[AudioClip]: ...
```

`transcribe_step` runs `to_stt_wav`, then `analyse_pcm16`/`admissible`, then the transcriber.
The transcode and checks are part of the `TRANSCRIBE` step's timing; there's no separate step name.

## 6. Data

- **Migration `s06_media_blobs`:**
  - creates `media_blobs` as in data-model.md, with `CHECK (size_bytes <= 2097152)` and an index
    on `(expires_at)`
  - adds `inbox_messages.media_blob_id uuid NULL REFERENCES media_blobs ON DELETE SET NULL`
- **Reads:** `media_blobs` (web inbound audio).
- **Writes:** `media_blobs` (`REPLY_AUDIO`), and deletes (`DeleteInboundMedia` via S4, plus
  expiry in the maintenance loop).

## 7. Configuration

Existing: `MODEL_API_BASE_URL`, `MODEL_API_KEY`, `MODEL_STT`, `WHATSAPP_GRAPH_BASE_URL`,
`WHATSAPP_ACCESS_TOKEN`, `SIDECAR_BASE_URL`, `SIDECAR_TOKEN`, `STT_FALLBACK_ENABLED`,
`TIMEOUT_FETCH_MEDIA_S`, `TIMEOUT_TRANSCRIBE_S`, `TIMEOUT_SYNTHESIZE_S`.

New (C9):

| Setting | Default |
|---|---|
| `MAX_INBOUND_AUDIO_BYTES` | 5242880 |
| `MIN_VOICE_NOTE_MS` | 700 |
| `MIN_VOICED_MS` | 300 |
| `MAX_VOICE_NOTE_SECONDS` | 180 |
| `TRANSCODE_TIMEOUT_S` | 5 |
| `STT_MAX_KEYWORDS` | 100 |
| `TTS_MAX_SENTENCE_CHARS` | 250 |
| `TTS_MAX_SPOKEN_CHARS` | 1200 |
| `REPLY_AUDIO_FOR_TEXT_INPUT` | false |

Requested (C8, not yet in contracts §7): `TTS_ENGINE: Literal["mms", "indic_parler"]`, default set
from spike C's outcome.

**Images reuse the media fetcher (C7, s10b §4.14).** The `FETCH_IMAGE` step uses
`WhatsAppMediaFetcher` (and the web path in s14) with the same two-step download, Bearer auth,
streaming cap and SHA-256 check, but capped at `MAX_INBOUND_IMAGE_BYTES` and returning an
`ImageClip` (mime `image/jpeg`, `image/png` or `image/webp`; anything else → `MediaUnsupported`).
The image is held in memory for the turn only and **never written to `media_blobs` or anywhere
else**. A small `fetch_image(ref) -> ImageClip` method is added beside `fetch` (or a second port
method; recorded as a requested contract change on `MediaFetcher`).

## 8. Failure modes

| Failure | User sees | Recorded |
|---|---|---|
| Media lookup or download fails after retries | `REPEAT_PLEASE` | `fetch_media` FAILED (`UNAVAILABLE` / `TIMEOUT`) |
| Media URL expired (404) | re-queried once silently; then `REPEAT_PLEASE` | retry noted in `detail` |
| File larger than the cap | `UNSUPPORTED_MEDIA` | `UNSUPPORTED_INPUT`, "size cap" |
| SHA-256 mismatch | retried once, then `REPEAT_PLEASE` | `INVALID_RESPONSE` |
| Corrupt or unknown audio (ffmpeg exits non-zero) | `UNSUPPORTED_MEDIA` | `UNSUPPORTED_INPUT`, stderr tail |
| ffmpeg hangs | `REPEAT_PLEASE` | `TIMEOUT`, "ffmpeg timed out" |
| Note under 0.7 s, or silent | `REPEAT_PLEASE` (no API call) | `EMPTY_INPUT`, "too_short" / "silent" |
| Note over 180 s | `TOO_LONG` ("send a shorter message") | `UNSUPPORTED_INPUT`, "duration cap" |
| STT returns an empty transcript | `REPEAT_PLEASE` | `EMPTY_INPUT` |
| STT down, fallback disabled | `REPEAT_PLEASE` | `UNAVAILABLE` |
| STT down, fallback enabled and works | normal reply | `detail="fallback=whisper"` |
| Sidecar cold start makes TTS miss its budget | text-only reply | `synthesize` FAILED `TIMEOUT`, turn DEGRADED |
| Latin letters left in Hindi `spoken_text` | text-only reply | `INVALID_RESPONSE`, "latin letters" (an S9 bug signal) |
| `spoken_text` too long | text-only reply | `INVALID_RESPONSE`, "too long" |
| Reply audio over 2 MB | text-only reply | `UNSUPPORTED_INPUT`, "size cap" |
| Sidecar token wrong | text-only replies on every turn | `ProviderRejected` → `INTERNAL`; `/readyz` reports the sidecar not ready |
| A `safety_out` block after speculative TTS | `REFUSE` (no audio) | the audio is never stored |

## 9. Tests

**Unit.**

*`WhatsAppMediaFetcher` (respx):*
- the two-step flow sends a Bearer header on both calls
- a 404 on download → re-query once → success
- `file_size` over the cap → no download made
- a body longer than its declared size → stops at the cap with `MediaTooLarge`
- a SHA-256 mismatch → `ProviderResponseInvalid`
- a 401 → `ProviderRejected`

*Fetchers:*
- `BlobMediaFetcher` with a missing row → `NotFound`
- `CompositeMediaFetcher` dispatches on which field of the ref is set

*Transcode (runs real ffmpeg on tiny generated inputs; requires ffmpeg on the CI image):*
- an ogg/opus fixture → WAV with 1 channel, 16-bit, 16 kHz
- a webm/opus fixture → the same
- WAV → OGG output whose header says Opus, 1 channel
- random bytes → `TranscodeFailed` with stderr in the message
- a fake binary that sleeps → timeout → the process is killed (assert `returncode` is set)
- `check_ffmpeg` fails when `libopus` is missing from a faked `-encoders` output

*`analyse_pcm16` / `admissible` (synthetic PCM):*
- silence → `SILENT`; 600 ms of tone → `TOO_SHORT`; 2 s of tone → `OK`; 181 s → `TOO_LONG`
- exactly 700 ms and exactly 180 s are `OK` (boundaries); 699 ms and 180.001 s are not

*`MuseVoiceTranscriber` (respx):*
- the multipart has a `request` part with the exact JSON keys and `audioEncoding: "WAV"`, and an
  `audio` part with `audio/wav`
- `sessionId` equals the turn id
- `Accept: application/json` is sent
- a 400 / 406 / 413 → `ProviderRejected`; a 429 with `Retry-After`; a 500 → `ProviderUnavailable`
- `transcript: "  "` → `EMPTY_INPUT`
- cost for `audioDurationMs=15999` is 15 s × 0.18 / 3600
- extra response fields are ignored

*`FallbackTranscriber`:*
- primary `ProviderUnavailable` with the fallback enabled → the fallback's result, with the provider recorded
- fallback disabled → the error propagates
- an empty primary transcript → the fallback is **not** called

*`detect_register`:*
- `"मुझे डॉक्टर बनना है"` → `HINDI`; `"mujhe doctor banna hai"` → `HINGLISH`;
  `"I want to be a doctor"` → `ENGLISH`; `"👍👍"` → `None`; `"ok"` → `None`
- mixed `"मुझे doctor बनना है"` → `HINDI` (Devanagari ≥ 60 %)

*`prepare_tts_text`:*
- a URL or emoji is removed
- Latin letters with `HINGLISH` register → `TtsTextInvalid`
- 1,201 characters → `TtsTextInvalid`
- a 300-character sentence → split at a comma into pieces of ≤ 250
- English register → voice `eng`, Latin letters allowed

*`MmsTtsSynthesizer` (respx):*
- the request body has `voice` and `sentences`
- a 401 → `ProviderRejected`
- a WAV response → OGG/Opus clip, with `audio_seconds` taken from the header

*Steps:* a 700 ms silent clip → `transcribe_step` returns `EMPTY_INPUT`, and the transcriber is
never called (check the fake's call count).

**Property (`hypothesis`).**

| Subject | Invariant |
|---|---|
| `analyse_pcm16` | `0 ≤ voiced_ms ≤ duration_ms`; `duration_ms == len(samples) × 1000 // rate`; all-zero PCM → `voiced_ms == 0` |
| `prepare_tts_text` (`hin`) | output sentences contain only Devanagari, Devanagari digits, ASCII digits, whitespace and `।?!,.`; each ≤ 250 characters; no sentence empty; idempotent: preparing the joined output gives the same sentences; Devanagari-only input keeps its letter sequence unchanged (only whitespace and removed symbols differ) |
| `detect_register` | the result for a text equals the result for the text with extra whitespace and punctuation added; pure Devanagari strings of ≥ 3 letters are always `HINDI` |
| `to_stt_wav` → `analyse_pcm16` (small generated tone or silence WAVs, real ffmpeg, few examples) | duration is preserved within ±40 ms through the transcode |

**Negative and edge cases:**
- a WhatsApp `MediaInfo` with a missing `url`, or `file_size` as a string
- a `MediaRef` with both or neither id set (validation error)
- a web blob with `mime_type="video/mp4"` (ffmpeg extracts no audio stream with `-vn` →
  `TranscodeFailed` → `UNSUPPORTED_MEDIA`)
- a stereo 44.1 kHz WAV input (downmixed to mono, which is documented behaviour, and asserted)

**Integration (`@pytest.mark.integration`):**
- the `s06_media_blobs` migration upgrades, downgrades and upgrades again
- inserting a blob over 2 MB fails the `CHECK`
- the `DeleteInboundMedia` write applied by S4 removes the row
- the maintenance loop deletes expired `REPLY_AUDIO` rows only
- deleting a user cascades to their blobs

**Sidecar (in `services/ml_sidecar/tests/`, run locally with a tiny model, or skipped in CI with
an explicit reason in `pytest.ini` markers, not via `skip` in code):**
- a missing or wrong token → 401
- 21 sentences, or a 251-character sentence → 422
- `/embed` returns 384-dimension unit vectors

## 10. Exit check

1. Run the S2 samples through `marg replay-audio ~/marg-samples/sample-0N.ogg`:
   - samples 1–9 return transcripts
   - sample 10 (silence) returns `REPEAT_PLEASE` without an API call (no `transcribe` usage row)
2. On the phone, send a Hinglish voice note: "Mujhe doctor banna hai, kya karna padega?"
   - Within about 10 s, a **voice note** arrives first, playing Hindi speech that matches the
     text, then the text message.
3. Send a 1-second silent note → a voice and text `REPEAT_PLEASE` arrives.
4. Stop the sidecar (or set a bad token) and send a voice note → a text-only reply arrives, with
   `synthesize` FAILED in `turn_steps`.
5. `media_blobs` holds the reply audio with `expires_at` 24 h out. No row exists for the
   WhatsApp inbound audio.
6. The verification loop is green, including the ffmpeg-backed tests.

## 11. Open questions

| # | Question | Recommendation |
|---|---|---|
| Q1 | Does Muse Voice Transcribe write Hindi speech in Devanagari or Latin script, and how well does it handle Hinglish code-switching? | Measure in S2 on the 10 samples (word error rate against the typed ground truth). If the error rate is above about 25 %, enable the Whisper fallback as primary. |
| Q2 | Does `facebook/mms-tts-hin` need uroman romanisation, or does it take Devanagari directly? | Check the tokenizer vocabulary in S2. If it needs uroman, the sidecar runs `uroman` server-side (a sidecar-only dependency), and option A still holds for the API side. |
| Q3 | Is MMS-TTS Hindi quality good enough to demo? | B10 fixes MMS-TTS as the hackathon voice; quality is still measured in the S2 listening test with 3 local listeners. Only if it fails does Indic Parler-TTS (same sidecar interface) go to the owner as a change. |
| Q4 | A CPU or GPU sidecar for TTS? | CPU unless warm 3-sentence `/tts` exceeds 1.5 s in S2. |
| Q5 | Should text-input users also get audio? | No by default (cost and latency); `REPLY_AUDIO_FOR_TEXT_INPUT` exists for the demo if wanted. |
| Q7 | Enable Zero Data Retention for Muse Voice Transcribe? How (console, header, approval)? | Yes if available; asked on Discord (s0-setup). Until answered, Standard mode applies (no training on our content). |
| Q6 | WhatsApp has no documented "voice note" flag for audio messages. Will OGG/Opus mono render as a playable voice bubble? | Confirm in S3/S6 on a real phone. |

## Contract changes (resolved 2026-10-25)

| # | Request | Resolution |
|---|---|---|
| C2 | `TurnWrite` variant `DeleteInboundMedia(blob_id)` | **Applied** (contracts §2.4) |
| C5 | `FixedReplyKind.TOO_LONG` | **Applied** (contracts §1) |
| C9 | Voice settings | **Applied** (contracts §7, "Voice (s06)") |
| C10 | `ReplyAudioStore` port | **Applied** (contracts §3) |
| C11 | `spoken_text` in Devanagari for `HINDI`/`HINGLISH` | **Applied** (contracts §2.6; s09 implements it) |
| C12 | `MediaError` family and its `FailureKind` mapping | **Applied** (contracts §4) |
| C13 | `Transcript.language` from `detect_register`, `confidence` always `None` here | **Applied** (contracts §2.1) |
| C14 | `transliterate.py` → `tts_text.py` in plan.md §9 and CLAUDE.md §3 | **Applied** by the parent |

## Speech-to-text doc check (2026-10-26, https://dev.meta.ai/docs/speech-to-text)

Confirms this design: multipart `request` (JSON) + `audio` (mono 16-bit WAV, 16 or 24 kHz),
10 minutes / 32 MB, response `sessionId`, `transcript`, `audioDurationMs`, `turns` (empty in
`PUSH_TO_TALK`), no confidence and no detected-language field, `languageBias` is a hint, keywords
bias but don't guarantee spelling (no documented maximum), 429s and failures before a transcript
aren't billed. New points:
- **24 kHz is the native rate**; 16 kHz is resampled server-side. Spike A compares word error
  rate at 16 and 24 kHz on the village samples; the default stays 16 kHz unless 24 kHz is measurably better.
- **`500` means "processing budget exceeded: retry once"**. The shared retry policy already
  retries `ProviderUnavailable`; for this endpoint it's capped at one retry.
- **Zero Data Retention (ZDR)** exists for Muse Voice Transcribe at Standard price, but how to
  enable it isn't documented. Open question Q7 (asked on Discord, see s0-setup); recommendation:
  enable it if available, since the audio includes children's voices.
- Standard mode content isn't used to train Meta models (pricing page). We never use Contributor mode.

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-25 | All requested contract changes applied; `detect_register` has one home (`app/domain/language.py`); MMS-TTS licence handled by B10 | Consolidation against the updated foundation docs | owner (defaults, B10) |
| 2026-10-26 | Two TTS adapters behind `Synthesizer` (`mms`, `indic_parler`) chosen by `TTS_ENGINE`; MMS only if the organisers confirm its licence, else Indic Parler on a GPU class; image fetch reuses the media fetcher (`FETCH_IMAGE`, `MAX_INBOUND_IMAGE_BYTES`, never persisted) | Owner decisions C8 (TTS licence) and C7 (activity photos) | owner |
