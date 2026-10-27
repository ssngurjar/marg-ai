"""Typed settings, read once at startup (contracts.md §7).

Each build step adds its own fields here, under a comment naming the step, in the same commit as
the code that reads them, and adds them to `.env.example`.
"""

from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigError

ASYNCPG_SCHEME = "postgresql+asyncpg://"

type Environment = Literal["local", "test", "staging", "prod"]


class DatabaseSettings(BaseSettings):
    """The one setting migrations need, so `alembic` runs without the app's other secrets."""

    # Written inline (not shared through a variable) so the pydantic mypy plugin sees `frozen`.
    # Settings inherits it.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,  # a secret that fails validation must not reach a log
    )

    database_url: SecretStr

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg_scheme(cls, database_url: SecretStr) -> SecretStr:
        if not database_url.get_secret_value().startswith(ASYNCPG_SCHEME):
            raise ValueError(f"must use the {ASYNCPG_SCHEME} scheme")
        return database_url


class Settings(DatabaseSettings):
    """Every setting the app reads. Secrets are `SecretStr` and never printed."""

    # S1, plus the inherited database URL
    environment: Environment = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Added in S3 for identity and WhatsApp
    user_hash_salt: SecretStr
    address_encryption_key: SecretStr
    whatsapp_graph_base_url: HttpUrl
    whatsapp_access_token: SecretStr
    whatsapp_app_secret: SecretStr
    whatsapp_verify_token: SecretStr
    whatsapp_phone_number_id: str = Field(min_length=1)
    webhook_max_body_bytes: int = Field(default=5_000_000, gt=0)
    timeout_whatsapp_s: float = Field(default=5.0, gt=0)

    # Added in S4 for the turn engine (contracts §7; exception E1: one process, no leases)
    turn_debounce_ms: int = Field(default=1000, ge=0)
    max_messages_per_turn: int = Field(default=5, ge=1)
    max_turn_attempts: int = Field(default=3, ge=1)
    stale_message_hours: int = Field(default=23, ge=1)
    recent_exchanges: int = Field(default=6, ge=0)
    turn_budget_s: float = Field(default=25.0, gt=0)
    outbox_max_attempts: int = Field(default=5, ge=1)
    maintenance_interval_s: float = Field(default=30.0, gt=0)
    shutdown_grace_s: float = Field(default=20.0, ge=0)
    retention_turn_text_days: int = Field(default=90, ge=1)
    retention_raw_payload_days: int = Field(default=7, ge=1)


def load_settings() -> Settings:
    """Read settings from the environment (and `.env` locally).

    Raises ConfigError listing every invalid field by name with the reason, never the value.
    """
    return _load(Settings)


def load_database_settings() -> DatabaseSettings:
    """Only DATABASE_URL, for migrations. Same errors as load_settings()."""
    return _load(DatabaseSettings)


def _load[SettingsModel: BaseSettings](settings_class: type[SettingsModel]) -> SettingsModel:
    try:
        return settings_class()
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
