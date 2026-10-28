"""The sidecar's HTTP app: `/tts` (s06 §4.9) and `/healthz`.

`/tts` needs `Authorization: Bearer <SIDECAR_TOKEN>`. The speech model loads once at startup;
one request at a time runs on it, because it isn't safe to share across threads.

Run from services/ml_sidecar (`make sidecar` from the repo root does this with .env):
    TTS_ENGINE=mms SIDECAR_TOKEN=... .venv/bin/uvicorn sidecar.server:build_app --factory
"""

import asyncio
import hmac
import logging
import os
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Annotated

import torch
from fastapi import Depends, FastAPI, Header, HTTPException, Response

from sidecar.api_models import HealthResponse, TtsRequest
from sidecar.mms_engine import MmsEngine
from sidecar.server_settings import ServerSettings
from sidecar.speech_engine import Engine, SpeechEngine, SpeechFailed, Voice, Waveform
from sidecar.wav_builder import WavBuilder

log = logging.getLogger("marg_sidecar")

type EngineLoader = Callable[[ServerSettings], SpeechEngine]


def load_mms(settings: ServerSettings) -> SpeechEngine:
    return MmsEngine.load(settings.device)


# Where a new speech model plugs in (see speech_engine.py).
ENGINES: dict[Engine, EngineLoader] = {"mms": load_mms}


class _LoadedEngine:
    def __init__(self) -> None:
        self.engine: SpeechEngine | None = None

    def get(self) -> SpeechEngine:
        if self.engine is None:
            raise HTTPException(status_code=503, detail="the speech model is still loading")
        return self.engine


def create_app(settings: ServerSettings, load: EngineLoader | None = None) -> FastAPI:
    """`load` replaces the engine named by TTS_ENGINE (tests pass a fake)."""
    loader = load if load is not None else ENGINES[settings.engine]
    loaded = _LoadedEngine()
    speech_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        loaded.engine = await asyncio.to_thread(loader, settings)
        log.warning("sidecar ready: tts %s on %s", settings.engine, settings.device)
        yield

    app = FastAPI(title="marg-ai ml sidecar", lifespan=lifespan)
    expected_authorization = f"Bearer {settings.token}".encode()

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if authorization is None or not hmac.compare_digest(
            authorization.encode(), expected_authorization
        ):
            log.warning("sidecar request refused: missing or wrong token")
            raise HTTPException(status_code=401, detail="unauthorised")

    @app.get("/healthz")
    async def healthz() -> HealthResponse:
        engine = loaded.get()
        return HealthResponse(status="ok", engine=engine.name, models_loaded=engine.models_loaded())

    @app.post("/tts", dependencies=[Depends(require_token)])
    async def tts(request: TtsRequest) -> Response:
        engine = loaded.get()
        if request.engine != engine.name:
            raise HTTPException(
                status_code=422, detail=f"this server runs {engine.name}, not {request.engine}"
            )
        async with speech_lock:
            try:
                pieces = await asyncio.to_thread(
                    _speak_all, engine, request.sentences, request.voice
                )
            except SpeechFailed as exc:
                log.exception("speech failed", exc_info=exc)
                raise HTTPException(status_code=500, detail="speech failed") from exc
        audio = WavBuilder.join(pieces, engine.sampling_rate)
        return Response(
            content=audio.wav_bytes,
            media_type="audio/wav",
            headers={"X-Audio-Duration-Ms": str(audio.duration_ms)},
        )

    return app


def build_app() -> FastAPI:
    """uvicorn's factory: settings from the environment, the real model."""
    settings = ServerSettings.from_environment(os.environ, cuda_available=torch.cuda.is_available())
    return create_app(settings)


def _speak_all(engine: SpeechEngine, sentences: Sequence[str], voice: Voice) -> list[Waveform]:
    return [engine.speak(sentence, voice) for sentence in sentences]
