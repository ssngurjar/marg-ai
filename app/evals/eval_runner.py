"""EvalRunner: `marg eval` from start to finish (s15 §4.2, §4.5 to §4.8).

Loads and filters the golden cases, plays them (EVAL_CONCURRENCY at a time) through a fresh
EvalHarness, checks and judges every turn that has an expectation, and builds the scorecard,
compared against the newest committed baseline.

A case passes when every check on every expected turn passes and the judge passed every item.
Hard gates: every crisis case passes; every adversarial case passes its safety and fixed-reply
checks and all its must_not items. Exit codes: 0 fine; 1 a hard gate failed; 2 a regression with
`fail_on_regression`. A harness failure (database, loader, a provider outage outside a turn)
raises instead, and the CLI exits 3 with no half-written scorecard.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Final

from app.core.clock import Clock
from app.core.config import Settings
from app.domain.enums import FailureKind
from app.domain.models.eval_judgement import JudgeScore
from app.evals.eval_checks import CheckResult, EvalChecks
from app.evals.eval_harness import EvalHarness, HarnessOptions
from app.evals.eval_judge import EvalJudge, JudgedTurn
from app.evals.golden_case import TurnExpectation
from app.evals.golden_case_loader import ROOT, GoldenCaseLoader, LoadedCase
from app.evals.scorecard import CaseResult, CaseStatus, FailedItem, RegressionReport, Scorecard
from app.evals.scorecard_builder import RunMeta, ScorecardBuilder
from app.evals.scorecard_renderer import ScorecardRenderer
from app.evals.turn_capture import TurnRecord
from app.layers.activity_catalogue import ActivityCatalogue

RESULTS_DIRECTORY: Final = ROOT / "evals" / "results"
PROVIDER_FAILURES: Final = frozenset(
    {FailureKind.TIMEOUT.value, FailureKind.RATE_LIMITED.value, FailureKind.UNAVAILABLE.value}
)
GATED_CHECKS: Final = frozenset({"safety", "fixed_reply"})
EXIT_OK: Final = 0
EXIT_HARD_GATE: Final = 1
EXIT_REGRESSION: Final = 2


@dataclass(frozen=True, slots=True)
class CaseFilter:
    files: frozenset[str] = frozenset()  # e.g. {"crisis.yaml"}; empty: every file
    case_ids: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()

    @property
    def partial(self) -> bool:
        return bool(self.files or self.case_ids or self.tags)

    def selects(self, loaded: LoadedCase) -> bool:
        case = loaded.case
        return (
            (not self.files or loaded.file in self.files)
            and (not self.case_ids or case.id in self.case_ids)
            and (not self.tags or bool(self.tags.intersection(case.tags)))
        )


@dataclass(frozen=True, slots=True)
class EvalRunConfig:
    case_filter: CaseFilter
    repeat: int
    options: HarnessOptions
    baseline: Path | None  # None: the newest committed full run
    fail_on_regression: bool
    write: bool
    results_directory: Path = RESULTS_DIRECTORY


@dataclass(frozen=True, slots=True)
class RunIdentity:
    git_sha: str
    dirty: bool


@dataclass(frozen=True, slots=True)
class EvalOutcome:
    scorecard: Scorecard
    regression: RegressionReport | None
    exit_code: int
    written: list[Path] = field(default_factory=list)


@dataclass(slots=True)
class _CaseTally:
    """What one case's turns found, before it becomes a CaseResult."""

    checks: list[CheckResult] = field(default_factory=list)
    judged: list[tuple[TurnExpectation, JudgedTurn]] = field(default_factory=list)
    records: list[TurnRecord] = field(default_factory=list)


class EvalRunner:
    def __init__(self, settings: Settings, config: EvalRunConfig, clock: Clock) -> None:
        self._settings = settings
        self._config = config
        self._clock = clock

    @staticmethod
    def select(case_filter: CaseFilter) -> list[LoadedCase]:
        """Raises GoldenCaseInvalid listing every problem in every file."""
        enabled = frozenset(activity.id for activity in ActivityCatalogue.load().enabled)
        loaded = GoldenCaseLoader.load(enabled_activities=enabled)
        return [case for case in loaded if case_filter.selects(case)]

    async def run(self, cases: Sequence[LoadedCase], identity: RunIdentity) -> EvalOutcome:
        started = self._clock.now()
        run_id = started.strftime("%Y%m%d_%H%M%S")
        async with EvalHarness(self._settings, self._config.options, run_id) as harness:
            judge = harness.judge(self._config.repeat)
            limit = asyncio.Semaphore(self._settings.eval_concurrency)

            async def one(loaded: LoadedCase) -> _CaseRun:
                async with limit:
                    return await self._case(loaded, harness, judge)

            runs = await asyncio.gather(*(one(loaded) for loaded in cases))
            versions = harness.prompt_versions
        results = [run.result for run in runs]
        meta = RunMeta(
            run_id=run_id,
            started_at=started,
            git_sha=identity.git_sha,
            dirty=identity.dirty,
            partial=self._config.case_filter.partial,
            models={
                "text": self._settings.model_text,
                "open": self._settings.open_model,
                "judge": self._settings.model_judge,
                "safety": self._settings.safety_model,
                "stt": self._settings.model_stt,
            },
            prompt_versions=versions,
            provider_errors=sum(run.provider_error for run in runs),
        )
        card = ScorecardBuilder.build(results, meta)
        return self._finish(card)

    def _finish(self, card: Scorecard) -> EvalOutcome:
        baseline = (
            Scorecard.model_validate_json(self._config.baseline.read_text(encoding="utf-8"))
            if self._config.baseline is not None
            else ScorecardBuilder.find_baseline(self._config.results_directory)
        )
        regression = ScorecardBuilder.compare(card, baseline) if baseline is not None else None
        written: list[Path] = []
        if self._config.write:
            directory = self._config.results_directory
            directory.mkdir(parents=True, exist_ok=True)
            stem = ScorecardBuilder.file_stem(card)
            json_path, markdown_path = directory / f"{stem}.json", directory / f"{stem}.md"
            json_path.write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")
            markdown_path.write_text(ScorecardRenderer.markdown(card, regression), encoding="utf-8")
            written = [json_path, markdown_path]
        exit_code = EXIT_OK
        if not all(card.hard_gates.values()):
            exit_code = EXIT_HARD_GATE
        elif self._config.fail_on_regression and regression is not None and regression.regressed:
            exit_code = EXIT_REGRESSION
        return EvalOutcome(
            scorecard=card, regression=regression, exit_code=exit_code, written=written
        )

    async def _case(self, loaded: LoadedCase, harness: EvalHarness, judge: EvalJudge) -> "_CaseRun":
        case = loaded.case
        if loaded.missing_fixtures:
            missing = ", ".join(loaded.missing_fixtures)
            skipped = _skipped(loaded, f"fixture not collected yet: {missing}")
            return _CaseRun(result=skipped, provider_error=False)
        user_hash = await harness.seed(case)
        tally = _CaseTally()
        said: list[str] = []
        for index, turn in enumerate(case.turns):
            last = index == len(case.turns) - 1
            record = await harness.play(case, user_hash, turn, first=index == 0)
            tally.records.append(record)
            said.append(turn.user if turn.button is None else f"(tapped {turn.button})")
            expectations = [turn.expect] if turn.expect is not None else []
            if last:
                expectations.append(case.expect)
            for expect in expectations:
                tally.checks.extend(EvalChecks.run(case, expect, record))
                if expect.judged_items:
                    tally.judged.append((expect, await judge.judge(case, said, record, expect)))
        provider_error = any(
            step.outcome == "failed" and step.failure_kind in PROVIDER_FAILURES
            for record in tally.records
            for step in record.snapshot.steps
        )
        return _CaseRun(result=_result(loaded, tally), provider_error=provider_error)


@dataclass(frozen=True, slots=True)
class _CaseRun:
    result: CaseResult
    provider_error: bool  # a model or safety call failed inside one of its turns


def _result(loaded: LoadedCase, tally: _CaseTally) -> CaseResult:
    case = loaded.case
    failed_checks = [f"{check.name}: {check.detail}" for check in tally.checks if not check.passed]
    failed_items: list[FailedItem] = []
    scores: list[JudgeScore] = []
    judge_errors: list[str] = []
    for expect, judged in tally.judged:
        if judged.score is None:
            judge_errors.append(judged.error or "unknown")
            continue
        scores.append(judged.score)
        failed_items.extend(_failed_items(expect, judged.score))
    status: CaseStatus = "passed"
    if judge_errors:
        status = "judge_error"
    elif failed_checks or failed_items:
        status = "failed"
    last = tally.records[-1]
    return CaseResult(
        id=case.id,
        file=loaded.file,
        status=status,
        deferred=case.deferred,
        hard_gate_ok=_hard_gate(loaded, tally, failed_items, passed=status == "passed"),
        failed_checks=failed_checks,
        failed_items=failed_items,
        rubric=_rubric(scores[-1]) if scores else None,
        cost_usd=sum((record.cost_usd for record in tally.records), Decimal(0)),
        judge_cost_usd=sum((judged.cost_usd for _, judged in tally.judged), Decimal(0)),
        latency_ms=last.snapshot.latency_ms,
        reply=last.reply_text if status != "passed" else None,
        note=f"judge error: {', '.join(judge_errors)}" if judge_errors else None,
    )


def _failed_items(expect: TurnExpectation, score: JudgeScore) -> list[FailedItem]:
    texts = expect.judged_items
    return [
        FailedItem(kind=item.kind, text=texts[item.index], reason=item.reason)
        for item in sorted(score.items, key=lambda item: item.index)
        if not item.passed and item.index < len(texts)
    ]


def _hard_gate(
    loaded: LoadedCase, tally: _CaseTally, failed_items: Sequence[FailedItem], *, passed: bool
) -> bool | None:
    if loaded.file == "crisis.yaml":
        return passed
    if loaded.file == "adversarial.yaml":
        gated_checks_ok = all(check.passed for check in tally.checks if check.name in GATED_CHECKS)
        judged_ok = all(judged.score is not None for _, judged in tally.judged)
        return (
            gated_checks_ok
            and judged_ok
            and not any(item.kind == "must_not" for item in failed_items)
        )
    return None


def _rubric(score: JudgeScore) -> dict[str, int]:
    return {
        "grounding": score.grounding,
        "cultural_resonance": score.cultural_resonance,
        "reading_level": score.reading_level,
        "actionability": score.actionability,
        "safety": score.safety,
    }


def _skipped(loaded: LoadedCase, note: str) -> CaseResult:
    return CaseResult(
        id=loaded.case.id,
        file=loaded.file,
        status="skipped",
        deferred=loaded.case.deferred,
        hard_gate_ok=None,
        failed_checks=[],
        failed_items=[],
        rubric=None,
        cost_usd=Decimal(0),
        judge_cost_usd=Decimal(0),
        latency_ms=None,
        reply=None,
        note=note,
    )
