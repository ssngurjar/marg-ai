"""ScorecardRenderer: the scorecard as markdown, readable on its own (s15 §4.6).

A headline table (pass rate, hard gates, rubric means, cost, latency, and the change against
the baseline), per-file pass rates, then each failing case with its reasons. This file goes in
the README and the submission.
"""

from app.evals.scorecard import RUBRIC_NAMES, CaseResult, RegressionReport, Scorecard


class ScorecardRenderer:
    @staticmethod
    def markdown(card: Scorecard, regression: RegressionReport | None) -> str:
        dirty = " (uncommitted changes)" if card.dirty else ""
        partial = " **Partial run (filtered): not a baseline.**" if card.partial else ""
        invalid = " **Invalid: too many provider errors.**" if card.invalid else ""
        models = ", ".join(f"{role}: {model}" for role, model in card.models.items())
        lines = [
            f"# Eval scorecard: {card.started_at:%Y-%m-%d %H:%M} UTC",
            "",
            f"Run `{card.run_id}` at `{card.git_sha}`{dirty}, prompts `{card.prompts_hash}`."
            f"{partial}{invalid}",
            "",
            "| | |",
            "|---|---|",
            f"| Pass rate | **{card.pass_rate:.0%}** ({_counted(card)}) |",
        ]
        for file, passed in card.hard_gates.items():
            lines.append(f"| Hard gate `{file}` | {'pass' if passed else '**FAIL**'} |")
        for name in RUBRIC_NAMES:
            if name in card.rubric:
                lines.append(
                    f"| {name.replace('_', ' ').capitalize()} | {card.rubric[name]:.2f} / 5 |"
                )
        lines.extend(
            [
                f"| Cost | ${card.cost_usd:.2f} pipeline + ${card.judge_cost_usd:.2f} judge |",
                f"| Latency | p50 {_ms(card.latency_p50_ms)}, p95 {_ms(card.latency_p95_ms)} |",
                f"| Models | {models} |",
            ]
        )
        if card.provider_errors:
            lines.append(f"| Provider errors | {card.provider_errors} |")
        if regression is not None:
            lines.extend(["", *ScorecardRenderer._regression(regression)])
        lines.extend(["", "## By file", "", "| File | Pass rate |", "|---|---|"])
        lines.extend(f"| `{file}` | {rate:.0%} |" for file, rate in card.pass_rate_by_file.items())
        failing = [case for case in card.cases if case.status != "passed"]
        if failing:
            lines.extend(["", "## Not passing", ""])
            for case in failing:
                lines.extend(ScorecardRenderer._case(case))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _regression(regression: RegressionReport) -> list[str]:
        lines = [f"## Against `{regression.baseline_run}`", ""]
        if not (regression.newly_failing or regression.newly_passing or regression.rubric_drops):
            lines.append("No change in which cases pass, and no rubric drop.")
        if regression.newly_failing:
            lines.append(f"- **Newly failing:** {', '.join(regression.newly_failing)}")
        if regression.newly_passing:
            lines.append(f"- Newly passing: {', '.join(regression.newly_passing)}")
        lines.extend(
            f"- **Rubric drop** ({drop.scope}): {drop.dimension} {drop.baseline:.2f} → "
            f"{drop.current:.2f}"
            for drop in regression.rubric_drops
        )
        lines.extend(
            f"- Prompt changed: `{prompt_id}` {before} → {after}"
            for prompt_id, (before, after) in regression.prompt_changes.items()
        )
        return lines

    @staticmethod
    def _case(case: CaseResult) -> list[str]:
        lines = [f"### `{case.id}` ({case.file}): {case.status.replace('_', ' ')}", ""]
        if case.note:
            lines.append(f"- {case.note}")
        lines.extend(f"- Check failed: {check}" for check in case.failed_checks)
        lines.extend(
            f"- {item.kind.replace('_', ' ')}: {item.text}. Judge: {item.reason}"
            for item in case.failed_items
        )
        if case.reply:
            quoted = "\n".join(f"> {line}" if line else ">" for line in case.reply.splitlines())
            lines.extend(["", "Reply:", "", quoted])
        lines.append("")
        return lines


def _counted(card: Scorecard) -> str:
    statuses = [case.status for case in card.cases if not case.deferred]
    passed = statuses.count("passed")
    judged = passed + statuses.count("failed")
    extras = []
    if skipped := statuses.count("skipped"):
        extras.append(f"{skipped} skipped")
    if errors := statuses.count("judge_error"):
        extras.append(f"{errors} judge errors")
    if deferred := sum(case.deferred for case in card.cases):
        extras.append(f"{deferred} deferred")
    suffix = f"; {', '.join(extras)}" if extras else ""
    return f"{passed} of {judged} cases{suffix}"


def _ms(value: int | None) -> str:
    return f"{value / 1000:.1f} s" if value is not None else "n/a"
