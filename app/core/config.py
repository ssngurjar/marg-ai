"""Typed settings, read once at startup (contracts.md §7).

Each build step adds its own fields here, under a comment naming the step, in the same commit as
the code that reads them, and adds them to `.env.example`.
"""

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, HttpUrl, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigError
from app.core.types import ReasoningEffort, TtsEngine

ASYNCPG_SCHEME = "postgresql+asyncpg://"
LOCAL_BASE_URL = "http://127.0.0.1:8000"

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
    # The business's public number, digits only: the teacher invite's wa.me link (s08). Public.
    whatsapp_display_number: str = Field(pattern=r"^\d{10,15}$")
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
    purge_sweep_after_s: int = Field(default=600, ge=60)  # s08 §4.10: purge even if undelivered

    # Added with E1's upgrade (s04 §4.3 to §4.11): several workers share the queue through leases
    lease_duration_s: float = Field(default=60.0, gt=0)  # at least twice TURN_BUDGET_S
    worker_concurrency: int = Field(default=8, ge=1)
    outbox_concurrency: int = Field(default=4, ge=1)
    outbox_sending_stuck_s: float = Field(default=60.0, gt=0)
    poll_interval_s: float = Field(default=2.0, gt=0)  # the fallback when a NOTIFY is missed
    # false: the api only stores messages and `python -m app.worker` runs the turns
    run_worker_in_api: bool = True
    # LISTEN needs a session-level connection: on Neon, the direct (unpooled) URL.
    # Blank: DATABASE_URL.
    database_listen_url: SecretStr | None = None

    # Added in S5 for the model, prompts and the safety core (contracts §7)
    model_api_base_url: HttpUrl
    model_api_key: SecretStr
    model_text: str = Field(default="muse-spark-1.3", min_length=1)
    model_reasoning_effort: ReasoningEffort = "minimal"
    # Muse Spark Open on Baseten (C9): the reflection prompt; Spark 1.3 is its fallback.
    open_model_base_url: HttpUrl
    open_model_api_key: SecretStr
    open_model: str = Field(min_length=1)
    # then fall back to Spark 1.3 (owner, 2026-10-27); spike E: 2-4 s, no quality loss
    timeout_open_model_s: float = Field(default=7.0, gt=0)
    activity_repeat_days: int = Field(default=30, ge=1)  # s10b §4.6
    safety_base_url: HttpUrl
    safety_api_key: SecretStr
    safety_model: str = Field(min_length=1)
    safety_policy_model_enabled: bool = True  # s07 C16: the Muse Spark policy check on input
    user_slot_max_chars: int = Field(default=4000, ge=100)
    # 5 s: the policy check is a Muse Spark call (spike E: 2.3 s p50, 3.2 s p95 at minimal)
    timeout_safety_in_s: float = Field(default=5.0, gt=0)
    timeout_route_s: float = Field(default=4.0, gt=0)
    timeout_generate_s: float = Field(default=12.0, gt=0)
    # Llama Guard's own limit inside a safety check: past it, the Muse Spark backup decides.
    timeout_guard_s: float = Field(default=1.5, gt=0)
    # 6 s: Llama Guard (≤ 1.5 s), then the Muse Spark backup reply check when it's down (~2.5 s)
    timeout_safety_out_s: float = Field(default=6.0, gt=0)

    # Added in S6 for voice (s06 §7). TTS_ENGINE picks the voice server's model: mms on the Mac
    # for testing, indic_parler on a GPU for the demo and final tests (owner, 2026-10-27).
    model_stt: str = Field(default="muse-voice-transcribe-1.0", min_length=1)
    tts_engine: TtsEngine = "mms"
    sidecar_base_url: HttpUrl
    sidecar_token: SecretStr
    timeout_fetch_media_s: float = Field(default=5.0, gt=0)
    timeout_transcribe_s: float = Field(default=10.0, gt=0)
    timeout_synthesize_s: float = Field(default=8.0, gt=0)
    max_inbound_audio_bytes: int = Field(default=5_242_880, gt=0)
    min_voice_note_ms: int = Field(default=700, ge=0)
    min_voiced_ms: int = Field(default=300, ge=0)
    max_voice_note_seconds: int = Field(default=180, gt=0)
    transcode_timeout_s: float = Field(default=5.0, gt=0)
    stt_max_keywords: int = Field(default=100, ge=0)
    reply_audio_for_text_input: bool = False

    # Added in S10b for the daily khoj message (s10b §4.11). Off until Meta approves the
    # templates; opt-ins are recorded either way.
    nudges_enabled: bool = False
    nudge_template_name: str = Field(default="marg_daily_khoj", min_length=1)  # hi and en
    nudge_template_name_hinglish: str = Field(default="marg_daily_khoj_hinglish", min_length=1)
    nudge_daily_limit: int = Field(default=200, ge=0)  # below the 250/day unverified cap

    # Added in S10b for khoj cards (C6): Muse Image after a good report (spike F: GO at low)
    khoj_card_enabled: bool = True
    model_image: str = Field(default="muse-image-1.0", min_length=1)
    image_reasoning_strength: Literal["low", "high"] = "low"
    timeout_make_card_s: float = Field(default=30.0, gt=0)

    # Added in S10b for activity photos (C7): SAM 3.1 checks for people, then counts (spike F)
    photo_input_enabled: bool = True
    model_segment: str = Field(default="sam-3.1", min_length=1)
    max_inbound_image_bytes: int = Field(default=5_242_880, gt=0)
    timeout_fetch_image_s: float = Field(default=5.0, gt=0)
    timeout_analyze_image_s: float = Field(default=6.0, gt=0)

    # Added in S14 for the web demo (s14; exception E2: polling, no SSE)
    session_signing_key: SecretStr
    session_signing_key_previous: SecretStr | None = None
    demo_rate_limit_per_hour: int = Field(default=30, ge=1)
    demo_ip_rate_limit_per_hour: int = Field(default=90, ge=1)
    demo_sessions_per_ip_per_hour: int = Field(default=20, ge=1)
    demo_max_audio_bytes: int = Field(default=1_000_000, gt=0)
    demo_max_image_bytes: int = Field(default=1_000_000, gt=0)  # the page sends a 1024-px JPEG
    # E2 upgrade (s14 §4.4): the live trace. A stream closes after this and the browser reconnects
    demo_sse_max_s: float = Field(default=600.0, gt=0)
    demo_sse_max_connections: int = Field(default=200, ge=1)  # open streams per api process
    daily_cost_cap_usd: Decimal = Field(default=Decimal(5), ge=0)  # web only, IST day

    # Added in S13 for /status and the admin dashboard (s13 §4.7, §4.9). The admin view shows
    # counts from as few as K_ANONYMITY_FLOOR_ADMIN children (owner, 2026-10-28); every other
    # view keeps K_ANONYMITY_FLOOR.
    public_base_url: HttpUrl = HttpUrl(LOCAL_BASE_URL)  # builds `marg admin-link` links
    dashboard_link_ttl_s: int = Field(default=900, gt=0)
    dashboard_cookie_ttl_s: int = Field(default=7200, gt=0)
    k_anonymity_floor: int = Field(default=5, ge=1)
    k_anonymity_floor_admin: int = Field(default=1, ge=1)

    # Added in S11 for retrieval over the corpus (s11 §7). The voice server also serves /embed.
    embed_model: str = Field(default="intfloat/multilingual-e5-small", min_length=1)
    timeout_embed_s: float = Field(default=5.0, gt=0)
    retrieval_top_k: int = Field(default=5, ge=1, le=10)
    retrieval_min_similarity: float = Field(default=0.80, ge=0, le=1)  # calibrated on the eval
    query_rewrite_enabled: bool = False  # on only if the eval shows recall@5 +0.05 (B9)

    # Added in S15 for `marg eval` (s15 §7). The judge reads replies, never users' messages.
    model_judge: str = Field(default="muse-spark-1.3", min_length=1)
    timeout_judge_s: float = Field(default=90.0, gt=0)  # high reasoning: slower than a turn
    # The TEST Postgres, with rights to create and drop databases: each run gets its own.
    eval_database_admin_url: SecretStr | None = None
    eval_concurrency: int = Field(default=4, ge=1, le=16)

    # Added in S10b for child talk (C13; contracts §7)
    child_talk_enabled: bool = True
    child_session_max_turns: int = Field(default=6, ge=1)
    child_session_max_minutes: int = Field(default=10, ge=1)
    child_session_cooldown_minutes: int = Field(default=30, ge=0)

    @field_validator("database_listen_url", "eval_database_admin_url", mode="before")
    @classmethod
    def _none_when_blank(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_listen_url", "eval_database_admin_url")
    @classmethod
    def _optional_url_uses_asyncpg(cls, url: SecretStr | None) -> SecretStr | None:
        if url is not None and not url.get_secret_value().startswith(ASYNCPG_SCHEME):
            raise ValueError(f"must use the {ASYNCPG_SCHEME} scheme")
        return url

    @model_validator(mode="after")
    def _lease_outlives_a_turn(self) -> Self:
        """A healthy turn must never lose its lease (s04 §7)."""
        if self.lease_duration_s < 2 * self.turn_budget_s:
            raise ValueError(
                f"lease_duration_s ({self.lease_duration_s}) must be at least twice "
                f"turn_budget_s ({self.turn_budget_s})"
            )
        return self

    @field_validator("public_base_url", mode="before")
    @classmethod
    def _local_when_blank(cls, value: object) -> object:
        """An empty PUBLIC_BASE_URL (the tunnel's address isn't known yet) means this machine."""
        if isinstance(value, str) and not value.strip():
            return LOCAL_BASE_URL
        return value

    @field_validator(
        "model_api_key",
        "safety_api_key",
        "open_model_api_key",
        "sidecar_token",
        "session_signing_key",
    )
    @classmethod
    def _require_a_key(cls, key: SecretStr) -> SecretStr:
        if not key.get_secret_value().strip():
            raise ValueError("must not be empty")
        return key


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
