"""`marg eval` runs only on the test Postgres, and asks before spending (s15 §4.8)."""

import pytest
from pydantic import SecretStr

from app import cli
from app.core.config import Settings
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.unit

TEST_POSTGRES = SecretStr("postgresql+asyncpg://marg:marg@127.0.0.1:1/marg_test")


def settings(**changes: object) -> Settings:
    return make_settings().model_copy(update=changes)


def run(monkeypatch: pytest.MonkeyPatch, configured: Settings, *arguments: str) -> int:
    monkeypatch.setattr(cli, "load_settings", lambda: configured)
    return cli.main(["eval", *arguments])


def test_it_refuses_a_production_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prod = settings(environment="prod", eval_database_admin_url=TEST_POSTGRES)
    assert run(monkeypatch, prod, "--case", "crisis-001") == cli.EXIT_EVAL_HARNESS
    assert "never runs with ENVIRONMENT=prod" in capsys.readouterr().out


def test_it_refuses_to_run_without_the_test_postgres(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unset = settings(eval_database_admin_url=None)  # whatever a local .env says
    assert run(monkeypatch, unset, "--case", "crisis-001") == cli.EXIT_EVAL_HARNESS
    assert "EVAL_DATABASE_ADMIN_URL is not set" in capsys.readouterr().out


def test_a_full_run_asks_before_spending_more_than_two_dollars(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configured = settings(eval_database_admin_url=TEST_POSTGRES)
    assert run(monkeypatch, configured) == cli.EXIT_NOTHING_TO_DO
    out = capsys.readouterr().out
    assert "estimated cost about $" in out
    assert "run again with --yes" in out


def test_a_filter_that_matches_nothing_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, settings(), "--case", "nobody-001") == cli.EXIT_EVAL_HARNESS
    assert "No case matches the filter." in capsys.readouterr().out
