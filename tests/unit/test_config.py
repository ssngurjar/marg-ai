from pathlib import Path

import pytest

from app.core.config import Settings, load_database_settings, load_settings
from app.core.errors import ConfigError
from tests.support.app_factory import TEST_ENCRYPTION_KEY, TEST_SALT

pytestmark = pytest.mark.unit

VALID_URL = "postgresql+asyncpg://marg:marg@localhost:5432/marg"


S3_SETTINGS = {
    "USER_HASH_SALT": TEST_SALT,
    "ADDRESS_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
    "WHATSAPP_GRAPH_BASE_URL": "https://graph.facebook.com/v26.0",
    "WHATSAPP_ACCESS_TOKEN": "test-access-token",
    "WHATSAPP_APP_SECRET": "test-app-secret",
    "WHATSAPP_VERIFY_TOKEN": "test-verify-token",
    "WHATSAPP_PHONE_NUMBER_ID": "100000000000001",
    "WHATSAPP_DISPLAY_NUMBER": "15550000000",
    "MODEL_API_BASE_URL": "https://api.meta.ai/v1",
    "MODEL_API_KEY": "test-model-key",
    "OPEN_MODEL_BASE_URL": "https://inference.baseten.co/v1",
    "OPEN_MODEL_API_KEY": "test-open-model-key",
    "OPEN_MODEL": "meta-models/muse-spark-open",
    "SAFETY_BASE_URL": "https://guard.example/v1",
    "SAFETY_API_KEY": "test-guard-key",
    "SAFETY_MODEL": "meta-llama/Llama-Guard-4-12B",
    "SESSION_SIGNING_KEY": "test-session-signing-key-0123456789",
}


OPTIONAL_PROVIDERS = (
    "OPEN_MODEL_BASE_URL",
    "OPEN_MODEL_API_KEY",
    "SAFETY_BASE_URL",
    "SAFETY_API_KEY",
)
"""Baseten and DeepInfra: a local run needs only the Meta Model API key (2026-11-03)."""


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No .env file and no inherited settings; the S3 settings are valid unless a test says not."""
    monkeypatch.chdir(tmp_path)
    for name in ("ENVIRONMENT", "DATABASE_URL", "LOG_LEVEL", "WEBHOOK_MAX_BODY_BYTES"):
        monkeypatch.delenv(name, raising=False)
    for name, value in S3_SETTINGS.items():
        monkeypatch.setenv(name, value)


def test_load_settings_reads_environment_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    settings = load_settings()
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.database_url.get_secret_value() == VALID_URL


def test_load_settings_reads_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WHATSAPP_APP_SECRET")
    (tmp_path / ".env").write_text(
        f"DATABASE_URL={VALID_URL}\nENVIRONMENT=test\nWHATSAPP_APP_SECRET=from-file\n"
    )
    assert load_settings().environment == "test"


def test_load_settings_missing_database_url_names_field() -> None:
    with pytest.raises(ConfigError, match=r"DATABASE_URL \(field required\)"):
        load_settings()


def test_load_settings_invalid_environment_names_field_and_allowed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ConfigError, match=r"ENVIRONMENT \(input should be 'local', 'test'"):
        load_settings()


@pytest.mark.parametrize(
    "url",
    [
        "postgres://marg:marg@localhost/marg",
        "postgresql://marg:marg@localhost/marg",
        "postgresql+psycopg://marg:marg@localhost/marg",
        "",
        "   ",
    ],
)
def test_load_settings_rejects_non_asyncpg_scheme(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ConfigError, match=r"DATABASE_URL \(must use the postgresql\+asyncpg://"):
        load_settings()


def test_config_error_never_contains_secret_value(monkeypatch: pytest.MonkeyPatch) -> None:
    leak_marker = "marker-value-that-must-not-leak"
    monkeypatch.setenv("DATABASE_URL", f"postgres://marg:{leak_marker}@localhost/marg")
    with pytest.raises(ConfigError) as caught:
        load_settings()
    assert leak_marker not in str(caught.value)
    assert caught.value.__cause__ is not None
    assert leak_marker not in str(caught.value.__cause__)


def test_config_error_lists_every_bad_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "nope")
    monkeypatch.setenv("LOG_LEVEL", "LOUD")
    with pytest.raises(ConfigError) as caught:
        load_settings()
    message = str(caught.value)
    for field_name in ("DATABASE_URL", "ENVIRONMENT", "LOG_LEVEL"):
        assert field_name in message


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    settings = load_settings()
    with pytest.raises(ValueError, match="frozen"):
        settings.environment = "prod"  # type: ignore[misc]  # asserting the model refuses it


def test_database_url_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    assert "marg:marg" not in repr(Settings())


@pytest.mark.parametrize("name", sorted(set(S3_SETTINGS) - set(OPTIONAL_PROVIDERS)))
def test_missing_s3_setting_is_named(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.delenv(name)
    with pytest.raises(ConfigError, match=name):
        load_settings()


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_only_the_meta_key_is_needed_for_the_models(
    monkeypatch: pytest.MonkeyPatch, blank: str | None
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    for name in OPTIONAL_PROVIDERS:
        if blank is None:
            monkeypatch.delenv(name)
        else:
            monkeypatch.setenv(name, blank)
    settings = load_settings()
    assert not settings.llama_guard_configured
    assert not settings.open_model_configured
    assert settings.open_model_in_use == settings.model_text


def test_with_both_hosts_set_llama_guard_and_the_open_model_are_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    settings = load_settings()
    assert settings.llama_guard_configured
    assert settings.open_model_configured
    assert settings.open_model_in_use == "meta-models/muse-spark-open"


@pytest.mark.parametrize(
    ("missing", "guard", "open_model"),
    [
        ("SAFETY_API_KEY", False, True),
        ("SAFETY_BASE_URL", False, True),
        ("OPEN_MODEL_API_KEY", True, False),
        ("OPEN_MODEL_BASE_URL", True, False),
    ],
)
def test_a_host_without_its_key_or_a_key_without_its_host_is_not_used(
    monkeypatch: pytest.MonkeyPatch, missing: str, *, guard: bool, open_model: bool
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.delenv(missing)
    settings = load_settings()
    assert settings.llama_guard_configured is guard
    assert settings.open_model_configured is open_model


@pytest.mark.parametrize("name", ["SAFETY_BASE_URL", "OPEN_MODEL_BASE_URL"])
def test_an_optional_host_that_isnt_a_url_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv(name, "not a url")
    with pytest.raises(ConfigError, match=name):
        load_settings()


# --- migrations (alembic/env.py) read only DATABASE_URL ---------------------------------------


def test_database_settings_load_without_any_other_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: CI's migration step sets only DATABASE_URL and failed once S3 added settings.
    for name in S3_SETTINGS:
        monkeypatch.delenv(name)
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    assert load_database_settings().database_url.get_secret_value() == VALID_URL


def test_database_settings_missing_url_names_field() -> None:
    with pytest.raises(ConfigError, match=r"DATABASE_URL \(field required\)"):
        load_database_settings()


def test_database_settings_reject_non_asyncpg_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://marg:marg@localhost:5432/marg")
    with pytest.raises(
        ConfigError, match=r"DATABASE_URL \(must use the postgresql\+asyncpg:// scheme\)"
    ):
        load_database_settings()


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_public_base_url_means_this_machine(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("PUBLIC_BASE_URL", value)
    assert str(load_settings().public_base_url) == "http://127.0.0.1:8000/"


def test_a_public_base_url_that_isnt_a_url_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("PUBLIC_BASE_URL", "not a url")
    with pytest.raises(ConfigError, match=r"PUBLIC_BASE_URL \(input should be a valid URL"):
        load_settings()


def test_the_admin_floor_is_one_and_everyone_elses_five_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    settings = load_settings()
    assert (settings.k_anonymity_floor, settings.k_anonymity_floor_admin) == (5, 1)


def test_a_lease_shorter_than_two_turn_budgets_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """s04 §7: a healthy turn must never lose its lease."""
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("TURN_BUDGET_S", "40")
    monkeypatch.setenv("LEASE_DURATION_S", "60")
    with pytest.raises(
        ConfigError,
        match=r"lease_duration_s \(60\.0\) must be at least twice turn_budget_s \(40\.0\)",
    ):
        load_settings()


def test_a_lease_of_exactly_two_turn_budgets_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("TURN_BUDGET_S", "30")
    monkeypatch.setenv("LEASE_DURATION_S", "60")
    assert load_settings().lease_duration_s == 60.0


@pytest.mark.parametrize(("value", "expected"), [("", None), ("   ", None)])
def test_a_blank_listen_url_means_the_main_database_url(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: None
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("DATABASE_LISTEN_URL", value)
    assert load_settings().database_listen_url is expected


def test_a_listen_url_must_use_asyncpg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("DATABASE_LISTEN_URL", "postgresql://marg:marg@localhost/marg")
    with pytest.raises(ConfigError, match=r"DATABASE_LISTEN_URL \(must use the postgresql"):
        load_settings()


def test_a_safety_check_has_room_for_the_backup_after_llama_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # owner, 2026-11-03: at 5 s and 6 s a slow Llama Guard left the Muse Spark backup too
    # little time; a parent's photo was dropped and their reply became the holding text
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    settings = load_settings()
    assert settings.timeout_safety_in_s == 20.0
    assert settings.timeout_safety_out_s == 20.0
    assert settings.timeout_safety_in_s - settings.timeout_guard_s >= 7.0
    assert settings.turn_budget_s > settings.timeout_safety_out_s + 2  # s16 §4.5


def test_a_reply_waits_rather_than_fails_and_only_backup_switches_stay_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # owner, 2026-11-03: "better to reply a little late than seem to fail"
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    settings = load_settings()
    reply_limits = [
        settings.timeout_generate_s,
        settings.timeout_exposure_s,
        settings.timeout_mentor_s,
        settings.timeout_safety_in_s,
        settings.timeout_safety_out_s,
        settings.timeout_transcribe_s,
    ]
    assert min(reply_limits) >= 20.0
    assert max(reply_limits) < settings.turn_budget_s
    assert settings.lease_duration_s >= 2 * settings.turn_budget_s
    backup_switches = [
        settings.timeout_guard_s,
        settings.timeout_open_model_s,
        settings.timeout_route_s,
    ]
    assert max(backup_switches) <= 7.0
