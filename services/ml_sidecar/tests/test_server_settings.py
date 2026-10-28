"""The sidecar refuses to start with a bad environment."""

import pytest

from sidecar.server_settings import ServerSettings, SettingsInvalid

pytestmark = pytest.mark.unit

SHARED_KEY = "test-sidecar-token-0123"


def test_reads_the_engine_token_and_device() -> None:
    settings = ServerSettings.from_environment(
        {"TTS_ENGINE": "mms", "SIDECAR_TOKEN": SHARED_KEY, "TTS_DEVICE": "mps"},
        cuda_available=False,
    )
    assert settings == ServerSettings(engine="mms", token=SHARED_KEY, device="mps")


def test_speech_defaults_to_the_gpu_when_there_is_one() -> None:
    settings = ServerSettings.from_environment(
        {"TTS_ENGINE": "mms", "SIDECAR_TOKEN": SHARED_KEY}, cuda_available=True
    )
    assert settings.device == "cuda"


@pytest.mark.parametrize("engine", ["", "kokoro", "indic_parler", "MMS"])
def test_an_unknown_engine_stops_startup(engine: str) -> None:
    with pytest.raises(SettingsInvalid, match="TTS_ENGINE must be one of"):
        ServerSettings.from_environment(
            {"TTS_ENGINE": engine, "SIDECAR_TOKEN": SHARED_KEY}, cuda_available=False
        )


@pytest.mark.parametrize("token", [None, "", "x" * 15])
def test_a_missing_or_short_token_stops_startup(token: str | None) -> None:
    environment = {"TTS_ENGINE": "mms"}
    if token is not None:
        environment["SIDECAR_TOKEN"] = token
    with pytest.raises(SettingsInvalid, match="SIDECAR_TOKEN must be set"):
        ServerSettings.from_environment(environment, cuda_available=False)


def test_a_token_of_exactly_sixteen_characters_is_enough() -> None:
    settings = ServerSettings.from_environment(
        {"TTS_ENGINE": "mms", "SIDECAR_TOKEN": "x" * 16}, cuda_available=False
    )
    assert settings.token == "x" * 16
