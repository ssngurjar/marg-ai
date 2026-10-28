"""The sidecar's HTTP contract (s06 §4.9) over a fake speech model."""

import io
import wave
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from sidecar.server import create_app
from sidecar.server_settings import ServerSettings
from tests.fakes import FakeEngine

pytestmark = pytest.mark.unit

SHARED_KEY = "test-sidecar-token-0123"
AUTH = {"Authorization": f"Bearer {SHARED_KEY}"}
SETTINGS = ServerSettings(engine="mms", token=SHARED_KEY, device="cpu")


class Sidecar:
    def __init__(self, client: TestClient, engine: FakeEngine) -> None:
        self.client = client
        self.engine = engine


def running(engine: FakeEngine) -> Iterator[Sidecar]:
    def load(_: ServerSettings) -> FakeEngine:
        return engine

    with TestClient(create_app(SETTINGS, load)) as client:
        yield Sidecar(client, engine)


@pytest.fixture
def sidecar() -> Iterator[Sidecar]:
    yield from running(FakeEngine())


@pytest.fixture
def failing_sidecar() -> Iterator[Sidecar]:
    yield from running(FakeEngine(fail=True))


def tts_body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "engine": "mms",
        "voice": "hin",
        "sentences": ["वाह! परछाई घूमती है!", "कल सुबह देखो।"],
    }
    body.update(changes)
    return body


def test_healthz_names_the_engine_and_models_without_a_token(sidecar: Sidecar) -> None:
    response = sidecar.client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "engine": "mms",
        "models_loaded": ["fake/speech"],
    }


def test_tts_returns_one_wav_with_silence_between_sentences(sidecar: Sidecar) -> None:
    response = sidecar.client.post("/tts", json=tts_body(), headers=AUTH)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    # two 0.1 s sentences and 0.25 s of silence between them
    assert response.headers["x-audio-duration-ms"] == "450"
    with wave.open(io.BytesIO(response.content)) as wav_file:
        assert (wav_file.getnchannels(), wav_file.getsampwidth()) == (1, 2)
        assert wav_file.getframerate() == FakeEngine.sampling_rate
        assert wav_file.getnframes() == 450
    assert sidecar.engine.spoken == [("वाह! परछाई घूमती है!", "hin"), ("कल सुबह देखो।", "hin")]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token-0000000"}, {"Authorization": SHARED_KEY}],
    ids=["missing", "wrong", "no-bearer"],
)
def test_tts_refuses_a_missing_or_wrong_token(sidecar: Sidecar, headers: dict[str, str]) -> None:
    response = sidecar.client.post("/tts", json=tts_body(), headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorised"}
    assert sidecar.engine.spoken == []


@pytest.mark.parametrize(
    "changes",
    [
        {"engine": "kokoro"},
        {"engine": ""},
        {"voice": "braj"},
        {"sentences": []},
        {"sentences": [""]},
        {"sentences": ["क" * 251]},
        {"sentences": ["ठीक है।"] * 21},
        {"sentences": "एक वाक्य"},
        {"sentences": [42]},
        {"speed": 2.0},
    ],
    ids=[
        "other-engine",
        "empty-engine",
        "unknown-voice",
        "no-sentences",
        "empty-sentence",
        "sentence-251-chars",
        "21-sentences",
        "string-not-list",
        "number-not-string",
        "unknown-field",
    ],
)
def test_tts_refuses_invalid_requests_without_speaking(
    sidecar: Sidecar, changes: dict[str, object]
) -> None:
    response = sidecar.client.post("/tts", json=tts_body(**changes), headers=AUTH)
    assert response.status_code == 422
    assert sidecar.engine.spoken == []


def test_tts_accepts_the_limits_exactly(sidecar: Sidecar) -> None:
    response = sidecar.client.post("/tts", json=tts_body(sentences=["क" * 250] * 20), headers=AUTH)
    assert response.status_code == 200
    assert len(sidecar.engine.spoken) == 20


def test_tts_reports_a_model_that_made_no_audio_as_a_server_error(
    failing_sidecar: Sidecar,
) -> None:
    response = failing_sidecar.client.post("/tts", json=tts_body(), headers=AUTH)
    assert response.status_code == 500
    assert response.json() == {"detail": "speech failed"}
