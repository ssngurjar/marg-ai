"""Run the child bank (evals/intents/child_messages.yaml) through the live child intent reader.

`.venv/bin/python -m scripts.child_bank [--repeat N] [--save]` reads every case with Muse Spark,
as `ChildIntentReader` does, and checks the intent, the language asked for, and whether the
answer is followed by the goodbye (`leaving_after`) or the parent's button (`handover_after`).
Why a leaving child is going (`leaving_reason`) is reported apart and never scored. It
prints accuracy per language and per intent, and each miss; `--save` writes the run to
evals/results/banks/. It needs the Model API key in `.env`. Exit status 0 at TARGET or above,
1 below (owner, 2026-11-20: at least 85%).
"""

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.clock import SystemClock
from app.core.config import Settings
from app.domain.enums import ChildIntent, Language, LeavingReason, Route
from app.domain.models.turn import Exchange
from app.layers.child_intent_reader import ChildIntentRead, ChildIntentReader
from app.store.db import create_engine, create_session_factory
from app.wiring import build_providers, build_retry, close_providers, prompt_registry
from scripts.bank_results import BankMiss, BankResults, BankRun

BANK_PATH: Final = Path(__file__).resolve().parents[1] / "evals" / "intents" / "child_messages.yaml"
BANK_NAME: Final = "child_messages"
TARGET: Final = Fraction(85, 100)  # exact: 85 of 100 passes, 84 doesn't
AT_ONCE: Final = 6  # readings in flight at a time
NICKNAME: Final = "Munni"
SAID_AT: Final = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)  # the reader doesn't read the time
LABEL_CONTEXT_CHARS: Final = 40  # how much of what Marg said a miss shows

type CaseLanguage = Literal["hindi", "hinglish", "braj", "english", "mixed"]


class ChildCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    intent: ChildIntent
    lang: CaseLanguage  # how the case is written, for the per-language table
    asked: Language | None = None
    leaving_after: bool = False
    handover_after: bool = False
    leaving_reason: LeavingReason | None = None  # every leaving case gives one
    marg_said: str | None = None  # Marg's last reply, when the meaning depends on it

    @property
    def label(self) -> str:
        """The case as a miss names it: the words, and what they followed when that decides
        ("nahi" after "…Aur kuch jaanna hai?" is going; after a question, an answer)."""
        if self.marg_said is None:
            return self.text
        tail = " ".join(self.marg_said.split())[-LABEL_CONTEXT_CHARS:]
        return f"{self.text} (after: …{tail})"

    def recent(self) -> list[Exchange]:
        """What the reader is shown as said before: Marg's last reply, or nothing."""
        if self.marg_said is None:
            return []
        return [
            Exchange(user_text="", reply_text=self.marg_said, route=Route.CHILD_TALK, at=SAID_AT)
        ]


class ChildBank(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: list[ChildCase]

    @staticmethod
    def load(path: Path = BANK_PATH) -> "ChildBank":
        return ChildBank.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True, slots=True)
class Reading:
    case: ChildCase
    read: ChildIntentRead

    @property
    def wrong(self) -> list[str]:
        """What the reading got wrong; [] when it's right. A failed call is one miss."""
        case, read = self.case, self.read
        if read.intent is None:
            return [f"failed ({read.failed}), not {case.intent.value}"]
        wrong: list[str] = []
        if read.intent is not case.intent:
            wrong.append(f"intent {read.intent.value}, not {case.intent.value}")
        if read.asked_language is not case.asked:
            wrong.append(f"asked {read.asked_language}, not {case.asked}")
        if read.leaving_after is not case.leaving_after:
            wrong.append(f"leaving_after {read.leaving_after}, not {case.leaving_after}")
        if read.handover_after is not case.handover_after:
            wrong.append(f"handover_after {read.handover_after}, not {case.handover_after}")
        return wrong

    @property
    def reason_wrong(self) -> str | None:
        """Why a leaving child is going, read wrong: reported apart, never a miss (owner,
        2026-11-20: the reason only picks an opening goodbye's words, and a missing one says
        "other"). None: right, or not a leaving case read as leaving."""
        case, read = self.case, self.read
        if case.intent is not ChildIntent.LEAVING or read.intent is not ChildIntent.LEAVING:
            return None
        if read.leaving_reason is case.leaving_reason:
            return None
        got = read.leaving_reason.value if read.leaving_reason else "none"
        expected = case.leaving_reason.value if case.leaving_reason else "none"
        return f"leaving_reason {got}, not {expected}"


@dataclass(frozen=True, slots=True)
class ReasonTally:
    """The leaving cases read as leaving, and how many gave the expected reason."""

    right: int
    of: int
    misses: list[BankMiss]

    def report(self) -> str:
        lines = ["", "## Why the child is going (not scored)", ""]
        if self.of == 0:
            return "\n".join([*lines, "No leaving case was read as leaving."]) + "\n"
        lines.append(f"{self.right}/{self.of} reasons as expected ({self.right / self.of:.0%})")
        lines += [f"- ({miss.lang}) {miss.text!r}: {miss.wrong}" for miss in self.misses]
        return "\n".join(lines) + "\n"


class ChildBankScorer:
    @staticmethod
    def score(readings: Sequence[Reading]) -> BankRun:
        """The run: right per language and per expected intent (the report's "Section"
        table), and every miss."""
        total_by_lang: Counter[str] = Counter()
        right_by_lang: Counter[str] = Counter()
        total_by_intent: Counter[str] = Counter()
        right_by_intent: Counter[str] = Counter()
        misses: list[BankMiss] = []
        for reading in readings:
            case = reading.case
            total_by_lang[case.lang] += 1
            total_by_intent[case.intent.value] += 1
            wrong = reading.wrong
            if wrong:
                misses.append(BankMiss(text=case.label, lang=case.lang, wrong="; ".join(wrong)))
            else:
                right_by_lang[case.lang] += 1
                right_by_intent[case.intent.value] += 1
        return BankRun(
            bank=BANK_NAME,
            readings=len(readings),
            right_by_lang=right_by_lang,
            total_by_lang=total_by_lang,
            misses=misses,
            right_by_section=right_by_intent,
            total_by_section=total_by_intent,
        )

    @staticmethod
    def reasons(readings: Sequence[Reading]) -> ReasonTally:
        """Why each leaving child is going, as read: apart from the score."""
        checked = 0
        misses: list[BankMiss] = []
        for reading in readings:
            expected_leaving = reading.case.intent is ChildIntent.LEAVING
            read_leaving = reading.read.intent is ChildIntent.LEAVING
            if not (expected_leaving and read_leaving):
                continue  # the intent itself was missed: scored above
            checked += 1
            reason_wrong = reading.reason_wrong
            if reason_wrong is not None:
                case = reading.case
                misses.append(BankMiss(text=case.label, lang=case.lang, wrong=reason_wrong))
        return ReasonTally(right=checked - len(misses), of=checked, misses=misses)

    @staticmethod
    def passes(run: BankRun) -> bool:
        """At least TARGET read right. A run with no readings proves nothing: it fails."""
        if run.readings == 0:
            return False
        return Fraction(run.right, run.readings) >= TARGET

    @staticmethod
    def exit_status(run: BankRun) -> int:
        return 0 if ChildBankScorer.passes(run) else 1


class ChildBankRunner:
    def __init__(self, reader: ChildIntentReader, at_once: int = AT_ONCE) -> None:
        self._reader = reader
        self._at_once = at_once

    async def read_all(self, cases: Sequence[ChildCase], repeat: int) -> list[Reading]:
        """Every case read `repeat` times, at most `at_once` in flight."""
        if repeat < 1:
            raise ValueError(f"repeat must be at least 1, not {repeat}")
        limit = asyncio.Semaphore(self._at_once)
        return await asyncio.gather(
            *(self._read(case, limit) for _ in range(repeat) for case in cases)
        )

    async def _read(self, case: ChildCase, limit: asyncio.Semaphore) -> Reading:
        async with limit:
            read = await self._reader.read(case.text, NICKNAME, case.recent())
            return Reading(case, read)


async def run(repeat: int, *, save: bool) -> BankRun:
    """The live run: real settings, the real model."""
    settings, clock = Settings(), SystemClock()
    engine = create_engine(settings)
    providers = build_providers(settings, create_session_factory(engine), build_retry(clock), clock)
    # the same time limit as in a turn: a slow reading is a miss, as it fails for a child
    reader = ChildIntentReader(
        providers.spark, prompt_registry(settings), timedelta(seconds=settings.timeout_route_s)
    )
    bank = ChildBank.load()
    try:
        readings = await ChildBankRunner(reader).read_all(bank.cases, repeat)
    finally:
        await close_providers(providers)
        await engine.dispose()
    result = ChildBankScorer.score(readings)
    reasons = ChildBankScorer.reasons(readings).report()
    sys.stdout.write(BankResults.report(result) + reasons)
    if save:
        saved = await BankResults.save(result, repeat=repeat)
        saved.write_text(saved.read_text(encoding="utf-8") + reasons, encoding="utf-8")
        sys.stdout.write(f"\nsaved {saved}\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1, help="read every case N times")
    parser.add_argument("--save", action="store_true", help="write the run to evals/results/banks")
    arguments = parser.parse_args()
    result = asyncio.run(run(arguments.repeat, save=arguments.save))
    sys.exit(ChildBankScorer.exit_status(result))


if __name__ == "__main__":
    main()
