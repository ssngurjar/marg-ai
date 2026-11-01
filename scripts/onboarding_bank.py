"""Run the onboarding bank (evals/intents/onboarding_answers.yaml) through the live onboarding
reader.

`.venv/bin/python -m scripts.onboarding_bank [--repeat N]` reads every answer as a real turn does
(the word rules first, then the Muse Spark extraction for what they don't understand) and prints
each miss: the event, or one of its values. It costs a few cents per run and needs the Model API
key in `.env`. Exit status 1 below TARGET (owner, 2026-11-01: at least 97%).
"""

import argparse
import asyncio
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.clock import SystemClock
from app.core.config import Settings
from app.domain.enums import ConversationState, Language, Role
from app.domain.models.conversation import (
    ChildAnswered,
    ChildInvalid,
    ChildrenAnswered,
    ConversationEvent,
    LanguageSwitched,
    ProfileAnswered,
    QuestionNoted,
    RoleChosen,
    Unrecognised,
)
from app.layers.onboarding_layer import OnboardingLayer
from app.store.db import create_engine, create_session_factory
from app.wiring import build_providers, build_retry, close_providers, prompt_registry
from tests.support.turn_context import text_message, turn_context, user_profile

BANK_PATH: Final = (
    Path(__file__).resolve().parents[1] / "evals" / "intents" / "onboarding_answers.yaml"
)
TARGET: Final = 0.97
AT_ONCE: Final = 6
INVITE_LINK: Final = "https://wa.me/15550000000"

EventName = Literal[
    "ConsentGiven",
    "ConsentDeclined",
    "RoleChosen",
    "GuardianConfirmed",
    "GuardianDeclined",
    "ChildAnswered",
    "ChildrenAnswered",
    "ChildInvalid",
    "ProfileAnswered",
    "LanguageSwitched",
    "QuestionNoted",
    "AboutMargAsked",
    "Unrecognised",
]


class KnownProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    grade: int | None = None
    subject: str | None = None
    district: str | None = None


class Expected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event: EventName
    role: Role | None = None
    age: int | None = None
    nickname: str | None = None
    grade: int | None = None
    subject: str | None = None
    district: str | None = None
    language: Language | None = None
    question: bool | None = None
    reason: str | None = None
    children: list[str] | None = None  # ChildrenAnswered: the home names, in order


class OnboardingCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: ConversationState
    role: Role | None = None
    known: KnownProfile = KnownProfile()
    text: str
    expect: Expected


class OnboardingBank(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: list[OnboardingCase]

    @staticmethod
    def load(path: Path = BANK_PATH) -> "OnboardingBank":
        return OnboardingBank.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True, slots=True)
class Reading:
    case: OnboardingCase
    event: ConversationEvent
    seconds: float
    differences: list[str]


class EventComparer:
    """What differs between an event and the bank's expectation; [] when it's right."""

    @staticmethod
    def differences(expected: Expected, event: ConversationEvent, now: datetime) -> list[str]:
        name = type(event).__name__
        if name != expected.event:
            return [f"event {name}, not {expected.event}"]
        differences: list[str] = []
        if (
            expected.role is not None
            and isinstance(event, RoleChosen)
            and event.role is not expected.role
        ):
            differences.append(f"role {event.role.value}")
        if isinstance(event, ChildAnswered):
            differences.extend(EventComparer._child(expected, event, now))
        if isinstance(event, ChildrenAnswered) and expected.children is not None:
            names = [(child.nickname or "").casefold() for child in event.children]
            if names != [name.casefold() for name in expected.children]:
                differences.append(f"children {names}")
        if isinstance(event, ProfileAnswered):
            differences.extend(EventComparer._profile(expected, event))
        if isinstance(event, LanguageSwitched) and expected.language not in {None, event.language}:
            differences.append(f"language {event.language.value}")
        if expected.question is not None:
            kept = isinstance(event, QuestionNoted | ProfileAnswered) and bool(event.question)
            if kept is not expected.question:
                differences.append(f"question kept: {kept}")
        if expected.reason is not None:
            reason = EventComparer._reason(event)
            if reason != expected.reason:
                differences.append(f"reason {reason}")
        return differences

    @staticmethod
    def _child(expected: Expected, event: ChildAnswered, now: datetime) -> list[str]:
        differences: list[str] = []
        if expected.age is not None and event.birth_year != now.year - expected.age:
            differences.append(f"age {now.year - event.birth_year}")
        if "nickname" in expected.model_fields_set:
            got = (event.nickname or "").casefold()
            if got != (expected.nickname or "").casefold():
                differences.append(f"nickname {event.nickname!r}")
        return differences

    @staticmethod
    def _profile(expected: Expected, event: ProfileAnswered) -> list[str]:
        update = event.update
        differences: list[str] = []
        if expected.grade is not None and update.grade != expected.grade:
            differences.append(f"grade {update.grade}")
        for field_name in ("subject", "district"):
            wanted: str | None = getattr(expected, field_name)
            got: str | None = getattr(update, field_name)
            if wanted is not None and wanted.casefold() not in (got or "").casefold():
                differences.append(f"{field_name} {got!r}")
        return differences

    @staticmethod
    def _reason(event: ConversationEvent) -> str | None:
        if isinstance(event, ChildInvalid):
            return event.reason.value
        if isinstance(event, Unrecognised):
            return event.not_understood.value
        return None


async def read_case(
    layer: OnboardingLayer, case: OnboardingCase, now: datetime, limit: asyncio.Semaphore
) -> Reading:
    profile = user_profile(state=case.state, role=case.role).model_copy(
        update=case.known.model_dump(exclude_none=True)
    )
    ctx = turn_context(text_message(case.text), profile=profile, learners=[])
    async with limit:
        started = time.perf_counter()
        # the bank tests what a turn reads, before the state machine acts on it
        reading = await layer._read(ctx, case.text, [], now)
        seconds = time.perf_counter() - started
    differences = EventComparer.differences(case.expect, reading.event, now)
    return Reading(case, reading.event, seconds, differences)


async def run(repeat: int) -> float:
    settings, clock = Settings(), SystemClock()
    engine = create_engine(settings)
    providers = build_providers(settings, create_session_factory(engine), build_retry(clock), clock)
    layer = OnboardingLayer(providers.language_model, prompt_registry(settings), INVITE_LINK)
    bank = OnboardingBank.load()
    limit = asyncio.Semaphore(AT_ONCE)
    now = clock.now()
    try:
        readings = await asyncio.gather(
            *(read_case(layer, case, now, limit) for _ in range(repeat) for case in bank.cases)
        )
    finally:
        await close_providers(providers)
        await engine.dispose()
    misses = [reading for reading in readings if reading.differences]
    seconds = sorted(reading.seconds for reading in readings)
    share_right = 1 - len(misses) / len(readings)
    sys.stdout.write(
        f"{len(readings) - len(misses)}/{len(readings)} right ({share_right:.1%}); "
        f"median {seconds[len(seconds) // 2]:.1f} s, slowest {seconds[-1]:.1f} s\n"
    )
    for state, count in Counter(reading.case.state.value for reading in misses).most_common():
        sys.stdout.write(f"{state}: {count} missed\n")
    for reading in misses:
        sys.stdout.write(
            f"  [{reading.case.state.value}] {reading.case.text!r}: "
            f"{'; '.join(reading.differences)} (got {reading.event})\n"
        )
    return share_right


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=1, help="read every case N times")
    arguments = parser.parse_args()
    sys.exit(0 if asyncio.run(run(arguments.repeat)) >= TARGET else 1)


if __name__ == "__main__":
    main()
