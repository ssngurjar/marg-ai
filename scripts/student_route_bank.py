"""Run the student-routing bank (evals/intents/student_routes.yaml) through `TurnRouter`.

`.venv/bin/python -m scripts.student_route_bank` routes every student message as a real turn
does and prints each miss. No model calls: a student's route is decided by word rules (s12 §4.6).
Exit status 1 below TARGET.
"""

import sys
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.domain.enums import Role, Route
from app.pipeline.turn_router import TurnRouter
from tests.support.turn_context import user_profile

BANK_PATH: Final = Path(__file__).resolve().parents[1] / "evals" / "intents" / "student_routes.yaml"
TARGET: Final = 0.97


class StudentCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    route: Literal["roadmap", "mentor"]


class StudentRouteBank(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: list[StudentCase]

    @staticmethod
    def load(path: Path = BANK_PATH) -> "StudentRouteBank":
        return StudentRouteBank.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def run() -> float:
    student = user_profile(role=Role.STUDENT)
    bank = StudentRouteBank.load()
    misses: list[tuple[StudentCase, Route]] = []
    for case in bank.cases:
        route = TurnRouter.decide(student, case.text, []).route
        if route.value != case.route:
            misses.append((case, route))
    share_right = 1 - len(misses) / len(bank.cases)
    sys.stdout.write(
        f"{len(bank.cases) - len(misses)}/{len(bank.cases)} right ({share_right:.1%})\n"
    )
    for case, route in misses:
        sys.stdout.write(f"  expected {case.route}, got {route.value}: {case.text}\n")
    return share_right


def main() -> None:
    sys.exit(0 if run() >= TARGET else 1)


if __name__ == "__main__":
    main()
