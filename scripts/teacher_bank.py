"""Run the teacher bank (evals/intents/teacher_messages.yaml) through the live teacher reader.

`.venv/bin/python -m scripts.teacher_bank [--repeat N]` reads every message with Muse Spark, as
`TeacherIntentReader` does in a real turn (owner, 2026-11-01), and prints each miss. It needs the
Model API key in `.env`. Exit status 1 below TARGET.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.clock import SystemClock
from app.core.config import Settings
from app.domain.enums import TeacherIntent
from app.layers.teacher_intent_reader import TeacherIntentRead, TeacherIntentReader
from app.store.db import create_engine, create_session_factory
from app.wiring import build_providers, build_retry, close_providers, prompt_registry

BANK_PATH: Final = (
    Path(__file__).resolve().parents[1] / "evals" / "intents" / "teacher_messages.yaml"
)
TARGET: Final = 0.97
AT_ONCE: Final = 6


class TeacherCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    last_topic: str | None = None
    intent: TeacherIntent


class TeacherBank(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: list[TeacherCase]

    @staticmethod
    def load(path: Path = BANK_PATH) -> "TeacherBank":
        return TeacherBank.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


async def read_case(
    reader: TeacherIntentReader, case: TeacherCase, limit: asyncio.Semaphore
) -> tuple[TeacherCase, TeacherIntentRead]:
    async with limit:
        return case, await reader.read(case.text, case.last_topic)


async def run(repeat: int) -> float:
    settings, clock = Settings(), SystemClock()
    engine = create_engine(settings)
    providers = build_providers(settings, create_session_factory(engine), build_retry(clock), clock)
    reader = TeacherIntentReader(providers.spark, prompt_registry(settings))
    bank = TeacherBank.load()
    limit = asyncio.Semaphore(AT_ONCE)
    try:
        readings = await asyncio.gather(
            *(read_case(reader, case, limit) for _ in range(repeat) for case in bank.cases)
        )
    finally:
        await close_providers(providers)
        await engine.dispose()
    misses = [(case, read) for case, read in readings if read.intent is not case.intent]
    share_right = 1 - len(misses) / len(readings)
    sys.stdout.write(f"{len(readings) - len(misses)}/{len(readings)} right ({share_right:.1%})\n")
    for case, read in misses:
        got = read.intent.value if read.intent else f"failed ({read.failed})"
        sys.stdout.write(f"  expected {case.intent.value}, got {got}: {case.text}\n")
    return share_right


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1, help="read every case N times")
    arguments = parser.parse_args()
    sys.exit(0 if asyncio.run(run(arguments.repeat)) >= TARGET else 1)


if __name__ == "__main__":
    main()
