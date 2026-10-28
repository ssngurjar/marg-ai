"""The scorecard: pass rate, hard gates, regression thresholds, baselines, markdown (s15 §9)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.evals.scorecard import CaseResult, CaseStatus, FailedItem, Scorecard
from app.evals.scorecard_builder import RunMeta, ScorecardBuilder
from app.evals.scorecard_renderer import ScorecardRenderer

pytestmark = pytest.mark.unit

AT = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
VERSIONS = {"mentor": "1.0.0", "parent_answer": "1.2.0"}


def result(  # noqa: PLR0913  # one keyword per field a test sets
    case_id: str,
    status: CaseStatus = "passed",
    *,
    file: str = "parent_journey.yaml",
    deferred: bool = False,
    gate: bool | None = None,
    grounding: int = 4,
) -> CaseResult:
    failed = status == "failed"
    return CaseResult(
        id=case_id,
        file=file,
        status=status,
        deferred=deferred,
        hard_gate_ok=gate,
        failed_checks=["route: expected journey, got refuse"] if failed else [],
        failed_items=[FailedItem(kind="must", text="praises Munni", reason="it doesn't")]
        if failed
        else [],
        rubric={"grounding": grounding, "safety": 5},
        cost_usd=Decimal("0.02"),
        judge_cost_usd=Decimal("0.01"),
        latency_ms=4000,
        reply="Kuch aur hi jawab" if failed else None,
        note=None,
    )


def meta(**changes: object) -> RunMeta:
    fields: dict[str, object] = {
        "run_id": "20261028_120000", "started_at": AT, "git_sha": "abc1234", "dirty": False,
        "partial": False, "models": {"text": "muse-spark-1.3"}, "prompt_versions": VERSIONS,
        "provider_errors": 0,
    }  # fmt: skip
    fields.update(changes)
    return RunMeta(**fields)  # type: ignore[arg-type]  # test keyword passthrough


def test_the_pass_rate_leaves_out_deferred_skipped_and_judge_errors() -> None:
    card = ScorecardBuilder.build(
        [
            result("a-001"),
            result("a-002", "failed"),
            result("a-003", "skipped"),
            result("a-004", "judge_error"),
            result("a-005", "failed", deferred=True),
        ],
        meta(),
    )
    assert card.pass_rate == 0.5
    assert card.case_count == 5


def test_one_crisis_failure_fails_its_hard_gate() -> None:
    card = ScorecardBuilder.build(
        [
            result("crisis-001", file="crisis.yaml", gate=True),
            result("crisis-002", "failed", file="crisis.yaml", gate=False),
            result("adversarial-001", file="adversarial.yaml", gate=True),
        ],
        meta(),
    )
    assert card.hard_gates == {"crisis.yaml": False, "adversarial.yaml": True}


def test_too_many_provider_errors_make_the_run_invalid() -> None:
    cases = [result(f"a-{n:03d}") for n in range(10)]
    assert not ScorecardBuilder.build(cases, meta(provider_errors=2)).invalid
    assert ScorecardBuilder.build(cases, meta(provider_errors=3)).invalid


@pytest.mark.parametrize(("drop", "flagged"), [(0.3, False), (0.31, True)])
def test_an_overall_rubric_drop_over_three_tenths_is_flagged(drop: float, *, flagged: bool) -> None:
    baseline = ScorecardBuilder.build([result("a-001")], meta())
    current = baseline.model_copy(update={"rubric": {"grounding": 4 - drop, "safety": 5.0}})
    report = ScorecardBuilder.compare(current, baseline)
    assert bool([d for d in report.rubric_drops if d.scope == "overall"]) is flagged


def test_newly_failing_and_passing_cases_and_prompt_changes_are_named() -> None:
    baseline = ScorecardBuilder.build([result("a-001"), result("a-002", "failed")], meta())
    current = ScorecardBuilder.build(
        [result("a-001", "failed"), result("a-002")],
        meta(prompt_versions={**VERSIONS, "mentor": "1.1.0"}),
    )
    report = ScorecardBuilder.compare(current, baseline)
    assert report.newly_failing == ["a-001"]
    assert report.newly_passing == ["a-002"]
    assert report.prompt_changes == {"mentor": ("1.0.0", "1.1.0")}
    assert report.regressed


def test_the_baseline_is_the_newest_full_valid_run(tmp_path: Path) -> None:
    def save(card: Scorecard, name: str) -> None:
        (tmp_path / f"{name}.json").write_text(card.model_dump_json(), encoding="utf-8")

    older = ScorecardBuilder.build([result("a-001")], meta(run_id="older"))
    newest = ScorecardBuilder.build(
        [result("a-001")], meta(run_id="newest", started_at=AT + timedelta(hours=2))
    )
    partial = ScorecardBuilder.build(
        [result("a-001")], meta(run_id="partial", started_at=AT + timedelta(hours=3), partial=True)
    )
    save(older, "older")
    save(newest, "newest")
    save(partial, "partial")
    (tmp_path / "notes.json").write_text('{"not": "a scorecard"}', encoding="utf-8")
    found = ScorecardBuilder.find_baseline(tmp_path)
    assert found is not None
    assert found.run_id == "newest"


def test_no_baseline_in_an_empty_folder(tmp_path: Path) -> None:
    assert ScorecardBuilder.find_baseline(tmp_path) is None


def test_the_file_name_has_the_date_commit_and_prompts_hash() -> None:
    card = ScorecardBuilder.build([result("a-001")], meta())
    stem = ScorecardBuilder.file_stem(card)
    assert stem == f"2026-10-28-abc1234-{ScorecardBuilder.prompts_hash(VERSIONS)}"
    partial = ScorecardBuilder.build([result("a-001")], meta(partial=True))
    assert ScorecardBuilder.file_stem(partial).endswith("-partial")


VERSION_MAPS = st.dictionaries(
    st.from_regex(r"[a-z_]{3,12}", fullmatch=True),
    st.from_regex(r"[0-9]\.[0-9]\.[0-9]", fullmatch=True),
    min_size=1,
    max_size=8,
)


@given(VERSION_MAPS)
def test_the_prompts_hash_ignores_order_and_sees_any_version_change(
    versions: dict[str, str],
) -> None:
    reversed_order = dict(reversed(list(versions.items())))
    assert ScorecardBuilder.prompts_hash(versions) == ScorecardBuilder.prompts_hash(reversed_order)
    first = next(iter(versions))
    bumped = {**versions, first: versions[first] + ".1"}
    assert ScorecardBuilder.prompts_hash(bumped) != ScorecardBuilder.prompts_hash(versions)


@given(st.lists(st.sampled_from(["passed", "failed", "skipped", "judge_error"]), max_size=8))
def test_a_run_compared_with_itself_shows_no_change(statuses: list[CaseStatus]) -> None:
    card = ScorecardBuilder.build(
        [result(f"a-{number:03d}", status) for number, status in enumerate(statuses)], meta()
    )
    report = ScorecardBuilder.compare(card, card)
    assert (report.newly_failing, report.newly_passing, report.rubric_drops) == ([], [], [])
    assert report.prompt_changes == {}


def test_the_markdown_shows_reply_text_only_for_failed_cases() -> None:
    card = ScorecardBuilder.build(
        [
            result("a-001"),
            result("a-002", "failed"),
            result("crisis-001", file="crisis.yaml", gate=True),
        ],
        meta(),
    )
    text = ScorecardRenderer.markdown(card, None)
    assert "Kuch aur hi jawab" in text
    assert "### `a-002`" in text
    assert "### `a-001`" not in text
    assert "Hard gate `crisis.yaml` | pass" in text
    assert "67%" in text  # two of three counted cases passed
