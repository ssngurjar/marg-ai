"""Run the intent bank (evals/intents/parent_intents.yaml) through the live intent reader.

`.venv/bin/python -m scripts.intent_bank [--repeat N] [--save]` reads every case with Muse Spark,
as `IntentReader` does in a real turn, and checks the intent, the language asked for and, where a
case says, Braj, the written language, the child's name and which khoj a report is about. It
prints accuracy per language and each miss; `--save` writes the run to evals/results/banks/. It
costs a few cents per run and needs the Model API key in `.env`. Exit status 1 below TARGET
(owner, 2026-11-01: at least 97%).
"""

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
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
from scripts.bank_results import BankMiss, BankResults, BankRun

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

type CaseLanguage = Literal["hindi", "hinglish", "braj", "english", "mixed"]


class BankCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    open_khoj: bool
    intent: ParentIntent
    lang: CaseLanguage  # how the case is written, for the per-language table
    section: Literal["main", "off_topic"] = "main"  # off_topic: reported on its own
    asked: Language | None = None
    # Checked only when a case gives them (critic review, 2026-11-01):
    braj: bool | None = None
    language: Language | None = None  # what the reader should hear the words as
    child_name: str | None = None
    report_about: str | None = None
    other_khojs: list[str] = []  # khoj titles offered lately besides the open one


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

    @property
    def wrong(self) -> list[str]:
        """What the reading got wrong; [] when it's right."""
        case, read = self.case, self.read
        wrong: list[str] = []
        if read.intent is not case.intent:
            got = read.intent.value if read.intent else f"failed ({read.failed})"
            wrong.append(f"intent {got}, not {case.intent.value}")
        if read.asked_language is not case.asked:
            wrong.append(f"asked {read.asked_language}, not {case.asked}")
        if case.braj is not None and read.braj is not case.braj:
            wrong.append(f"braj {read.braj}, not {case.braj}")
        if case.language is not None and read.language is not case.language:
            wrong.append(f"language {read.language}, not {case.language}")
        read_name = (read.child_name or "").casefold()
        if case.child_name is not None and read_name != case.child_name.casefold():
            wrong.append(f"child_name {read.child_name!r}, not {case.child_name!r}")
        if case.report_about is not None and read.report_about != case.report_about:
            wrong.append(f"report_about {read.report_about!r}, not {case.report_about!r}")
        return wrong


async def read_case(reader: IntentReader, case: BankCase, limit: asyncio.Semaphore) -> Reading:
    async with limit:
        read = await reader.read(
            case.text,
            OPEN_KHOJ_TITLE if case.open_khoj else None,
            CHILDREN,
            [],
            case.other_khojs,
        )
        return Reading(case, read)


async def run(repeat: int, *, save: bool) -> float:
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
    total_by_lang: Counter[str] = Counter(reading.case.lang for reading in readings)
    misses = [
        BankMiss(text=reading.case.text, lang=reading.case.lang, wrong="; ".join(reading.wrong))
        for reading in readings
        if reading.wrong
    ]
    missed_by_lang: Counter[str] = Counter(miss.lang for miss in misses)
    right_by_lang: Counter[str] = Counter(
        {lang: total - missed_by_lang[lang] for lang, total in total_by_lang.items()}
    )
    total_by_section: Counter[str] = Counter(reading.case.section for reading in readings)
    right_by_section: Counter[str] = Counter(
        reading.case.section for reading in readings if not reading.wrong
    )
    result = BankRun(
        bank="parent_intents",
        readings=len(readings),
        right_by_lang=right_by_lang,
        total_by_lang=total_by_lang,
        misses=misses,
        right_by_section=right_by_section,
        total_by_section=total_by_section,
    )
    await BankResults.print_and_save(result, repeat=repeat, save=save)
    return result.share_right


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1, help="read every case N times")
    parser.add_argument("--save", action="store_true", help="write the run to evals/results/banks")
    arguments = parser.parse_args()
    share_right = asyncio.run(run(arguments.repeat, save=arguments.save))
    sys.exit(0 if share_right >= TARGET else 1)


if __name__ == "__main__":
    main()
