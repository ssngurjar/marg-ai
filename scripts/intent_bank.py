"""Run the intent bank (evals/intents/parent_intents.yaml) through the live intent reader.

`.venv/bin/python -m scripts.intent_bank [--repeat N]` reads every case with Muse Spark, as
`IntentReader` does in a real turn, and prints each miss: the intent or the language asked for.
It costs a few cents per run and needs the Model API key in `.env`. Exit status 1 when fewer
than TARGET of the readings are right (owner, 2026-11-01: at least 97%).
"""

import argparse
import asyncio
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.clock import SystemClock
from app.core.config import Settings
from app.domain.enums import Language, LearnerRelation, ParentIntent
from app.domain.models.learner import Learner, LearnerId
from app.layers.intent_reader import IntentRead, IntentReader
from app.store.db import create_engine, create_session_factory
from app.wiring import build_providers, build_retry, close_providers, prompt_registry

BANK_PATH: Final = Path(__file__).resolve().parents[1] / "evals" / "intents" / "parent_intents.yaml"
OPEN_KHOJ_TITLE: Final = "Jaanwar ki chaal"
TARGET: Final = 0.97
AT_ONCE: Final = 6  # readings in flight at a time
CHILDREN: Final = (
    Learner(
        id=LearnerId(UUID(int=1)),
        relation=LearnerRelation.PARENT,
        nickname="Munni",
        birth_year=2021,
        child_talk_consented_at=None,
    ),
    Learner(
        id=LearnerId(UUID(int=2)),
        relation=LearnerRelation.PARENT,
        nickname="Golu",
        birth_year=2019,
        child_talk_consented_at=None,
    ),
)


class BankCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    open_khoj: bool
    intent: ParentIntent
    asked: Language | None = None


class IntentBank(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: list[BankCase]

    @staticmethod
    def load(path: Path = BANK_PATH) -> "IntentBank":
        return IntentBank.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True, slots=True)
class Reading:
    case: BankCase
    read: IntentRead
    seconds: float

    @property
    def right(self) -> bool:
        return self.read.intent is self.case.intent and self.read.asked_language is self.case.asked


async def read_case(reader: IntentReader, case: BankCase, limit: asyncio.Semaphore) -> Reading:
    async with limit:
        started = time.perf_counter()
        read = await reader.read(
            case.text, OPEN_KHOJ_TITLE if case.open_khoj else None, CHILDREN, []
        )
        return Reading(case, read, time.perf_counter() - started)


def describe(reading: Reading) -> str:
    case, read = reading.case, reading.read
    got = read.intent.value if read.intent else f"failed ({read.failed})"
    asked_got = read.asked_language.value if read.asked_language else "-"
    asked_expected = case.asked.value if case.asked else "-"
    return (
        f"  expected {case.intent.value}/asked={asked_expected}, "
        f"got {got}/asked={asked_got}: {case.text}"
    )


async def run(repeat: int) -> float:
    settings, clock = Settings(), SystemClock()
    engine = create_engine(settings)
    providers = build_providers(settings, create_session_factory(engine), build_retry(clock), clock)
    reader = IntentReader(providers.spark, prompt_registry(settings))
    bank = IntentBank.load()
    limit = asyncio.Semaphore(AT_ONCE)
    try:
        readings = await asyncio.gather(
            *(read_case(reader, case, limit) for _ in range(repeat) for case in bank.cases)
        )
    finally:
        await close_providers(providers)
        await engine.dispose()
    misses = [reading for reading in readings if not reading.right]
    missed_by_intent = Counter(reading.case.intent.value for reading in misses)
    seconds = sorted(reading.seconds for reading in readings)
    share_right = 1 - len(misses) / len(readings)
    sys.stdout.write(
        f"{len(readings) - len(misses)}/{len(readings)} right ({share_right:.1%}); "
        f"median {seconds[len(seconds) // 2]:.1f} s, slowest {seconds[-1]:.1f} s\n"
    )
    for intent, count in missed_by_intent.most_common():
        sys.stdout.write(f"{intent}: {count} missed\n")
    for reading in misses:
        sys.stdout.write(f"{describe(reading)}\n")
    return share_right


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1, help="read every case N times")
    arguments = parser.parse_args()
    share_right = asyncio.run(run(arguments.repeat))
    sys.exit(0 if share_right >= TARGET else 1)


if __name__ == "__main__":
    main()
