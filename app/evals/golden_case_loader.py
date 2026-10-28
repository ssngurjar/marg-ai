"""GoldenCaseLoader: reads and checks every case file in `evals/golden/` (s15 §4.1).

Every `*.yaml` file is a list of cases. Unknown keys, a bad id, an id used twice (across files),
an activity that isn't enabled, an audio fixture that doesn't exist: every error in every file
is reported at once, each naming its file and case, so one run shows everything to fix.

An image fixture that isn't there yet is not an error: photos come from the owner's sample
collection, and a case waiting for one is skipped at run time with that reason.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml
from pydantic import ValidationError

from app.core.errors import GoldenCaseInvalid
from app.evals.golden_case import GoldenCase

ROOT: Final = Path(__file__).resolve().parents[2]
GOLDEN_DIRECTORY: Final = ROOT / "evals" / "golden"
AUDIO_FIXTURES: Final = ROOT / "tests" / "fixtures" / "audio"
IMAGE_FIXTURES: Final = ROOT / "evals" / "fixtures" / "images"


@dataclass(frozen=True, slots=True)
class LoadedCase:
    case: GoldenCase
    file: str  # e.g. "crisis.yaml": per-file pass rates and the hard gates
    missing_fixtures: tuple[str, ...]  # image fixtures not collected yet: the case is skipped


class GoldenCaseLoader:
    @staticmethod
    def load(
        directory: Path = GOLDEN_DIRECTORY,
        enabled_activities: frozenset[str] | None = None,
        audio_fixtures: Path = AUDIO_FIXTURES,
        image_fixtures: Path = IMAGE_FIXTURES,
    ) -> list[LoadedCase]:
        """Raises GoldenCaseInvalid listing every problem. `enabled_activities` None: activity
        ids aren't checked (unit tests of the loader alone)."""
        problems: list[str] = []
        loaded: list[LoadedCase] = []
        seen: dict[str, str] = {}
        for path in sorted(directory.glob("*.yaml")):
            for case in GoldenCaseLoader._cases_in(path, problems):
                where = f"{path.name} {case.id}"
                if case.id in seen:
                    problems.append(f"{where}: id already used in {seen[case.id]}")
                    continue
                seen[case.id] = path.name
                problems.extend(
                    GoldenCaseLoader._reference_problems(
                        case, where, enabled_activities, audio_fixtures
                    )
                )
                missing = tuple(
                    attachment.fixture
                    for attachment in case.attachments
                    if not (image_fixtures / attachment.fixture).is_file()
                )
                loaded.append(LoadedCase(case=case, file=path.name, missing_fixtures=missing))
        if not loaded and not problems:
            problems.append(f"{directory}: no *.yaml case files")
        if problems:
            raise GoldenCaseInvalid("invalid golden cases:\n- " + "\n- ".join(problems))
        return loaded

    @staticmethod
    def _cases_in(path: Path, problems: list[str]) -> list[GoldenCase]:
        try:
            raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: not valid YAML ({type(exc).__name__})")
            return []
        if not isinstance(raw, list):
            problems.append(f"{path.name}: expected a list of cases")
            return []
        cases: list[GoldenCase] = []
        for position, entry in enumerate(raw, start=1):
            label = entry.get("id", f"case {position}") if isinstance(entry, dict) else position
            try:
                cases.append(GoldenCase.model_validate(entry))
            except ValidationError as exc:
                problems.extend(
                    f"{path.name} {label}: {_location(error['loc'])} {error['msg']}"
                    for error in exc.errors(include_input=False, include_url=False)
                )
        return cases

    @staticmethod
    def _reference_problems(
        case: GoldenCase,
        where: str,
        enabled_activities: frozenset[str] | None,
        audio_fixtures: Path,
    ) -> list[str]:
        problems: list[str] = []
        if (
            enabled_activities is not None
            and case.open_activity is not None
            and case.open_activity not in enabled_activities
        ):
            problems.append(f"{where}: open_activity {case.open_activity!r} isn't enabled")
        for turn in case.turns:
            if (
                turn.audio_fixture is not None
                and not (audio_fixtures / turn.audio_fixture).is_file()
            ):
                problems.append(f"{where}: audio_fixture {turn.audio_fixture!r} doesn't exist")
        return problems


def _location(parts: Sequence[int | str]) -> str:
    return ".".join(str(part) for part in parts) or "case"
