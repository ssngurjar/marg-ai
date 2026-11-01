"""BankResults: a bank run saved as evidence (critic review, 2026-11-01): what was read right,
overall and per language, and every miss. Written to evals/results/banks/ as JSON and Markdown,
dated, so a number quoted in the submission points at the run behind it.
"""

import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final

from app.core.clock import SystemClock

RESULTS_DIRECTORY: Final = Path(__file__).resolve().parents[1] / "evals" / "results" / "banks"


@dataclass(frozen=True, slots=True)
class BankMiss:
    text: str
    lang: str
    wrong: str  # what was read wrong, e.g. "intent new_khoj, not another_khoj"


@dataclass(frozen=True, slots=True)
class BankRun:
    bank: str  # "parent_intents", "onboarding_answers", …
    readings: int
    right_by_lang: Counter[str] = field(default_factory=Counter)
    total_by_lang: Counter[str] = field(default_factory=Counter)
    misses: list[BankMiss] = field(default_factory=list)
    # "off_topic": messages not about what Marg does, reported on their own (2026-11-01)
    right_by_section: Counter[str] = field(default_factory=Counter)
    total_by_section: Counter[str] = field(default_factory=Counter)

    @property
    def right(self) -> int:
        return self.readings - len(self.misses)

    @property
    def share_right(self) -> float:
        return self.right / self.readings if self.readings else 0.0


class BankResults:
    @staticmethod
    def report(run: BankRun) -> str:
        """The run as Markdown: the total, accuracy per language, every miss."""
        lines = [
            f"# Bank run: {run.bank}",
            "",
            f"**{run.right}/{run.readings} read right ({run.share_right:.1%})**",
            "",
            "| Language | Right | Of | Share |",
            "|---|---|---|---|",
        ]
        for lang in sorted(run.total_by_lang):
            total = run.total_by_lang[lang]
            right = run.right_by_lang[lang]
            lines.append(f"| {lang} | {right} | {total} | {right / total:.0%} |")
        if len(run.total_by_section) > 1:
            lines += ["", "| Section | Right | Of | Share |", "|---|---|---|---|"]
            for section in sorted(run.total_by_section):
                total = run.total_by_section[section]
                right = run.right_by_section[section]
                lines.append(f"| {section} | {right} | {total} | {right / total:.0%} |")
        if run.misses:
            lines += ["", "## Misses", ""]
            lines += [f"- ({miss.lang}) {miss.text!r}: {miss.wrong}" for miss in run.misses]
        return "\n".join(lines) + "\n"

    @staticmethod
    async def save(run: BankRun, *, repeat: int) -> Path:
        """Write the run, named by date, time and commit; returns the Markdown path."""
        RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        stamp = SystemClock().now().strftime("%Y-%m-%d-%H%M")
        commit = await BankResults._commit()
        name = f"{stamp}-{commit}-{run.bank}"
        payload = {
            "bank": run.bank,
            "run_at_utc": stamp,
            "commit": commit,
            "repeat": repeat,
            "readings": run.readings,
            "right": run.right,
            "by_language": {
                lang: {"right": run.right_by_lang[lang], "of": run.total_by_lang[lang]}
                for lang in sorted(run.total_by_lang)
            },
            "by_section": {
                section: {"right": run.right_by_section[section], "of": total}
                for section, total in sorted(run.total_by_section.items())
            },
            "misses": [asdict(miss) for miss in run.misses],
        }
        (RESULTS_DIRECTORY / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        markdown = RESULTS_DIRECTORY / f"{name}.md"
        markdown.write_text(BankResults.report(run), encoding="utf-8")
        return markdown

    @staticmethod
    async def print_and_save(run: BankRun, *, repeat: int, save: bool) -> None:
        sys.stdout.write(BankResults.report(run))
        if save:
            saved = await BankResults.save(run, repeat=repeat)
            sys.stdout.write(f"\nsaved {saved}\n")

    @staticmethod
    async def _commit() -> str:
        """The short commit the run was made at (uncommitted changes aren't marked)."""
        process = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "--short",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await process.communicate()
        return output.decode("utf-8", "replace").strip() or "unknown"
