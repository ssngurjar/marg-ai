# ML sidecar

Marg's voice for replies, behind the contract in
[`docs/design/s06-voice.md`](../../docs/design/s06-voice.md) §4.9:

| Endpoint | Model | What it does |
|---|---|---|
| `POST /tts` | Meta's MMS-TTS: [`facebook/mms-tts-hin`](https://huggingface.co/facebook/mms-tts-hin), [`facebook/mms-tts-eng`](https://huggingface.co/facebook/mms-tts-eng) (CC-BY-NC 4.0) | A reply's prepared sentences as one 16-bit mono WAV |
| `GET /healthz` | | The engine and the models loaded |

**Off by default.** Every model Marg calls must be a Meta model (organisers, 2026-10-29), and
MMS-TTS is Meta's only speech model for Hindi. Its licence is non-commercial, and the organisers
are still ruling on whether that fits a prize submission, so the app runs with
`VOICE_REPLIES_ENABLED=false` (text replies) and never calls this service. Switching it on is
that one setting plus `make sidecar`.

`/tts` needs `Authorization: Bearer <SIDECAR_TOKEN>`. Requests are validated strictly:
over-limit input gets 422, never cut.

It has its own Python 3.12 environment, so the main service (3.13) never carries PyTorch. From
the repository root:

```sh
make sidecar-setup    # once
make sidecar          # serves :8100 with the repo's .env (TTS_ENGINE, SIDECAR_TOKEN)
make sidecar-check    # strict mypy and the tests (fake models, no downloads)
```

**Plugging in another speech model:** a class that satisfies `SpeechEngine`
([`sidecar/speech_engine.py`](sidecar/speech_engine.py)), its name in `Engine` and
`KNOWN_ENGINES`, an entry in `ENGINES` in [`sidecar/server.py`](sidecar/server.py), and the same
name in the app's `TtsEngine` (`app/core/types.py`) and `SidecarSynthesizer.MODELS`. The app's
`TTS_ENGINE` setting then picks it.
