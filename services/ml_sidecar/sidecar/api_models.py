"""Request and response bodies of the sidecar's HTTP API (s06 §4.9, s11 §4.4).

Validated strictly: unknown fields and over-limit input are refused with 422, never cut.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sidecar.speech_engine import Engine, Voice

type SpokenSentence = Annotated[str, StringConstraints(min_length=1, max_length=250)]
type EmbedText = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class TtsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: Engine
    voice: Voice
    sentences: Annotated[list[SpokenSentence], Field(min_length=1, max_length=20)]


class EmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    texts: Annotated[list[EmbedText], Field(min_length=1, max_length=32)]


class EmbedResponse(BaseModel):
    model: str
    dimensions: int
    vectors: list[list[float]]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    engine: Engine
    models_loaded: list[str]
