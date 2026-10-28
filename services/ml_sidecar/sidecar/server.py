"""The sidecar's HTTP app: `/tts` (s06 §4.9), `/embed` (s11 §4.4) and `/healthz`.

Every endpoint but /healthz needs `Authorization: Bearer <SIDECAR_TOKEN>`. Models load once at
startup; one request at a time runs on each model, because they aren't safe to share across
threads.

Run from services/ml_sidecar (`make sidecar` from the repo root does this with .env):
    TTS_ENGINE=kokoro SIDECAR_TOKEN=... .venv/bin/uvicorn sidecar.server:build_app --factory
"""

import asyncio
import hmac
import logging
import os
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

import torch
from fastapi import Depends, FastAPI, Header, HTTPException, Response

from sidecar.api_models import EmbedRequest, EmbedResponse, HealthResponse, TtsRequest
from sidecar.kokoro_engine import KokoroEngine
from sidecar.server_settings import ServerSettings
from sidecar.speech_engine import Engine, SpeechEngine, SpeechFailed, Voice, Waveform
from sidecar.text_embedder import Embedder, TextEmbedder
from sidecar.wav_builder import WavBuilder

log = logging.getLogger("marg_sidecar")

type EngineLoader = Callable[[str], SpeechEngine]

# Where a new speech model plugs in (see speech_engine.py).
ENGINES: dict[Engine, EngineLoader] = {"kokoro": KokoroEngine.load}


@dataclass(frozen=True, slots=True)
class SidecarModels:
    engine: SpeechEngine
    embedder: Embedder
    embed_model: str


type ModelLoader = Callable[[ServerSettings], SidecarModels]


def load_models(settings: ServerSettings) -> SidecarModels:
    return SidecarModels(
        engine=ENGINES[settings.engine](settings.device),
        embedder=TextEmbedder.load(settings.embed_device),
        embed_model=TextEmbedder.MODEL,
    )


class _LoadedModels:
    def __init__(self) -> None:
        self.models: SidecarModels | None = None

    def get(self) -> SidecarModels:
        if self.models is None:
            raise HTTPException(status_code=503, detail="models are still loading")
        return self.models


def create_app(settings: ServerSettings, load: ModelLoader = load_models) -> FastAPI:
    loaded = _LoadedModels()
    speech_lock = asyncio.Lock()
    embed_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        loaded.models = await asyncio.to_thread(load, settings)
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
        models = loaded.get()
        return HealthResponse(
            status="ok",
            engine=models.engine.name,
            models_loaded=[*models.engine.models_loaded(), models.embed_model],
        )

    @app.post("/tts", dependencies=[Depends(require_token)])
    async def tts(request: TtsRequest) -> Response:
        models = loaded.get()
        if request.engine != models.engine.name:
            raise HTTPException(
                status_code=422,
                detail=f"this server runs {models.engine.name}, not {request.engine}",
            )
        async with speech_lock:
            try:
                pieces = await asyncio.to_thread(
                    _speak_all, models.engine, request.sentences, request.voice
                )
            except SpeechFailed as exc:
                log.exception("speech failed", exc_info=exc)
                raise HTTPException(status_code=500, detail="speech failed") from exc
        audio = WavBuilder.join(pieces, models.engine.sampling_rate)
        return Response(
            content=audio.wav_bytes,
            media_type="audio/wav",
            headers={"X-Audio-Duration-Ms": str(audio.duration_ms)},
        )

    @app.post("/embed", dependencies=[Depends(require_token)])
    async def embed(request: EmbedRequest) -> EmbedResponse:
        models = loaded.get()
        async with embed_lock:
            vectors = await asyncio.to_thread(models.embedder.embed, request.texts)
        return EmbedResponse(
            model=models.embed_model, dimensions=models.embedder.dimensions, vectors=vectors
        )

    return app


def build_app() -> FastAPI:
    """uvicorn's factory: settings from the environment, the real models."""
    settings = ServerSettings.from_environment(os.environ, cuda_available=torch.cuda.is_available())
    return create_app(settings)


def _speak_all(engine: SpeechEngine, sentences: Sequence[str], voice: Voice) -> list[Waveform]:
    return [engine.speak(sentence, voice) for sentence in sentences]
