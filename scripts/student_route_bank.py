"""Run the student-routing bank (evals/intents/student_routes.yaml) as a turn routes it.

`.venv/bin/python -m scripts.student_route_bank [--repeat N]` routes every student message with
`TurnRouter`'s plan words, then, where they sent it to the mentor by default, with the live
`StudentIntentReader` (owner, 2026-11-01), and prints each miss. It needs the Model API key in
`.env`. Exit status 1 below TARGET.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.clock import SystemClock
from app.core.config import Settings
from app.domain.enums import Role, Route, StudentIntent
from app.layers.student_intent_reader import StudentIntentReader
from app.pipeline.turn_router import TurnRouter
from app.store.db import create_engine, create_session_factory
from app.wiring import build_providers, build_retry, close_providers, prompt_registry
from tests.support.turn_context import user_profile

BANK_PATH: Final = Path(__file__).resolve().parents[1] / "evals" / "intents" / "student_routes.yaml"
TARGET: Final = 0.97
AT_ONCE: Final = 6


class StudentCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    # about_marg: a question about Marg itself, answered from the reviewed facts (2026-11-01)
    route: Literal["roadmap", "mentor", "about_marg"]


class StudentRouteBank(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: list[StudentCase]

    @staticmethod
    def load(path: Path = BANK_PATH) -> "StudentRouteBank":
        return StudentRouteBank.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


type Destination = Literal["roadmap", "mentor", "about_marg"]
DESTINATIONS: Final[dict[StudentIntent, Destination]] = {
    StudentIntent.PLAN: "roadmap",
    StudentIntent.QUESTION: "mentor",
    StudentIntent.ABOUT_MARG: "about_marg",
}


@dataclass(frozen=True, slots=True)
class Routed:
    case: StudentCase
    route: str  # where the turn goes: a route's name, or "about_marg"
    by: str  # "words" or "reading"


async def route_case(
    reader: StudentIntentReader, case: StudentCase, limit: asyncio.Semaphore
) -> Routed:
    decision = TurnRouter.decide(user_profile(role=Role.STUDENT), case.text, [])
    if decision.route is not Route.MENTOR:
        return Routed(case, decision.route.value, "words")
    async with limit:
        read = await reader.read(case.text)
    destination = DESTINATIONS[read.intent] if read.intent is not None else "mentor"
    return Routed(case, destination, "reading")


async def run(repeat: int) -> float:
    settings, clock = Settings(), SystemClock()
    engine = create_engine(settings)
    providers = build_providers(settings, create_session_factory(engine), build_retry(clock), clock)
    reader = StudentIntentReader(providers.language_model, prompt_registry(settings))
    bank = StudentRouteBank.load()
    limit = asyncio.Semaphore(AT_ONCE)
    try:
        routed = await asyncio.gather(
            *(route_case(reader, case, limit) for _ in range(repeat) for case in bank.cases)
        )
    finally:
        await close_providers(providers)
        await engine.dispose()
    misses = [item for item in routed if item.route != item.case.route]
    share_right = 1 - len(misses) / len(routed)
    sys.stdout.write(f"{len(routed) - len(misses)}/{len(routed)} right ({share_right:.1%})\n")
    for item in misses:
        sys.stdout.write(
            f"  expected {item.case.route}, got {item.route} by {item.by}: {item.case.text}\n"
        )
    return share_right


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1, help="route every case N times")
    arguments = parser.parse_args()
    sys.exit(0 if asyncio.run(run(arguments.repeat)) >= TARGET else 1)


if __name__ == "__main__":
    main()
