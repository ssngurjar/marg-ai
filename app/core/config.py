"""Typed settings, read once at startup (contracts.md §7).

Each build step adds its own fields here, under a comment naming the step, in the same commit as
the code that reads them, and adds them to `.env.example`.
"""

from typing import Literal

from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigError

ASYNCPG_SCHEME = "postgresql+asyncpg://"

type Environment = Literal["local", "test", "staging", "prod"]


class Settings(BaseSettings):
    """Every setting the app reads. Secrets are `SecretStr` and never printed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,  # a secret that fails validation must not reach a log
    )

    # S1
    environment: Environment = "local"
    database_url: SecretStr
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg_scheme(cls, database_url: SecretStr) -> SecretStr:
        if not database_url.get_secret_value().startswith(ASYNCPG_SCHEME):
            raise ValueError(f"must use the {ASYNCPG_SCHEME} scheme")
        return database_url


def load_settings() -> Settings:
    """Read settings from the environment (and `.env` locally).

    Raises ConfigError listing every invalid field by name with the reason, never the value.
    """
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError(f"invalid settings: {describe_validation_errors(exc)}") from exc


def describe_validation_errors(error: ValidationError) -> str:
    """Summarise as 'DATABASE_URL (field required), ENVIRONMENT (input should be …)'.

    Field names and reasons only; input values are never included.
    """
    problems: list[str] = []
    for problem in error.errors(include_input=False, include_url=False):
        field_name = ".".join(str(part) for part in problem["loc"]).upper() or "SETTINGS"
        reason = problem["msg"].removeprefix("Value error, ")
        problems.append(f"{field_name} ({reason[:1].lower()}{reason[1:]})")
    return ", ".join(problems)
