# ML sidecar

Marg's voice and search vectors, behind the contracts in
[`docs/design/s06-voice.md`](../../docs/design/s06-voice.md) §4.9 and
[`s11-rag.md`](../../docs/design/s11-rag.md) §4.4:

| Endpoint | Model | What it does |
|---|---|---|
| `POST /tts` | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) | A reply's prepared sentences as one 16-bit mono WAV. Hindi and Hinglish: the `hf_alpha` and `hf_beta` voices blended, at 1.1× speed; English: `af_heart` |
| `POST /embed` | [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) (MIT) | 384-number, L2-normalised vectors for the corpus and for questions |
| `GET /healthz` | | The engine and the models loaded |

Every endpoint but `/healthz` needs `Authorization: Bearer <SIDECAR_TOKEN>`. Requests are
validated strictly: over-limit input gets 422, never cut.

It has its own Python 3.12 environment, because Kokoro supports up to 3.12 and the main
service (3.13) never carries PyTorch. From the repository root:

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
