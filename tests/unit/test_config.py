from pathlib import Path

import pytest

from app.core.config import Settings, load_settings
from app.core.errors import ConfigError

pytestmark = pytest.mark.unit

VALID_URL = "postgresql+asyncpg://marg:marg@localhost:5432/marg"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No .env file and no inherited settings: each test sets exactly what it needs."""
    monkeypatch.chdir(tmp_path)
    for name in ("ENVIRONMENT", "DATABASE_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


def test_load_settings_reads_environment_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    settings = load_settings()
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.database_url.get_secret_value() == VALID_URL


def test_load_settings_reads_dotenv_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"DATABASE_URL={VALID_URL}\nENVIRONMENT=test\n")
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
