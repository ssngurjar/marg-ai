"""ServerSettings: the sidecar's environment, read once at startup."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from sidecar.speech_engine import KNOWN_ENGINES, Engine


class SettingsInvalid(RuntimeError):
    """The environment can't start the sidecar."""


@dataclass(frozen=True, slots=True)
class ServerSettings:
    engine: Engine  # TTS_ENGINE, the same value as the app's
    token: str  # SIDECAR_TOKEN, the same value as the app's
    device: str  # TTS_DEVICE
    embed_device: str  # EMBED_DEVICE

    MIN_TOKEN_CHARS: ClassVar[int] = 16

    @staticmethod
    def from_environment(
        environment: Mapping[str, str], *, cuda_available: bool
    ) -> "ServerSettings":
        engine_name = environment.get("TTS_ENGINE", "")
        engine = KNOWN_ENGINES.get(engine_name)
        if engine is None:
            raise SettingsInvalid(
                f"TTS_ENGINE must be one of {sorted(KNOWN_ENGINES)}, got {engine_name!r}"
            )
        token = environment.get("SIDECAR_TOKEN", "")
        if len(token) < ServerSettings.MIN_TOKEN_CHARS:
            raise SettingsInvalid(
                f"SIDECAR_TOKEN must be set (at least {ServerSettings.MIN_TOKEN_CHARS} characters)"
            )
        default_device = "cuda" if cuda_available else "cpu"
        return ServerSettings(
            engine=engine,
            token=token,
            device=environment.get("TTS_DEVICE", default_device),
            embed_device=environment.get("EMBED_DEVICE", "cpu"),
        )
