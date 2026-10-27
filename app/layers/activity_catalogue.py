"""ActivityCatalogue: the reviewed khoj catalogue, loaded and checked at startup (s10b §4.3).

`content/activities/*.yaml`, one activity per file named after its id, plus the closed lists
`_materials.yaml` and `_hazards.yaml`. Any invalid file stops the app from starting
(CorpusValidationError naming the file and field): a parent is never sent an unreviewed or
unsafe activity. `CatalogueActivitySource` is the MVP's ActivitySource; generated sources plug
into the same port later, behind the same validator.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Final

import yaml

from app.constants.child_hazards import CHILD_HAZARD_WORDS
from app.core.errors import CorpusValidationError
from app.domain.models.activity import Activity
from app.domain.models.learner import Learner
from app.domain.rules.activity_chooser import ActivityChooser
from app.domain.rules.activity_validator import ActivityValidator
from app.domain.rules.stage_rules import StageRules

CATALOGUE_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "content" / "activities"


class ActivityCatalogue:
    def __init__(
        self, activities: Sequence[Activity], materials: frozenset[str] = frozenset()
    ) -> None:
        self.activities = tuple(activities)
        self.materials = materials  # the closed list; a curiosity mini-activity uses it too

    @staticmethod
    def load(directory: Path = CATALOGUE_DIRECTORY) -> "ActivityCatalogue":
        materials = frozenset(ActivityCatalogue._names(directory / "_materials.yaml", "materials"))
        hazards = frozenset(ActivityCatalogue._names(directory / "_hazards.yaml", "hazards"))
        if set(hazards) != set(CHILD_HAZARD_WORDS):
            raise CorpusValidationError("_hazards.yaml and the d7 hazard words list differ")
        activities: list[Activity] = []
        for path in sorted(directory.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            try:
                activity = ActivityValidator.validate(
                    ActivityCatalogue._mapping(path),
                    materials=materials,
                    hazards=hazards,
                    hazard_words=CHILD_HAZARD_WORDS,
                )
            except CorpusValidationError as exc:
                raise CorpusValidationError(f"{path.name}: {exc}") from exc
            if activity.id != path.stem:
                raise CorpusValidationError(f"{path.name}: id {activity.id!r} must match the file")
            activities.append(activity)
        return ActivityCatalogue(activities, materials)

    @property
    def enabled(self) -> list[Activity]:
        return [activity for activity in self.activities if activity.status == "enabled"]

    @staticmethod
    def _mapping(path: Path) -> Mapping[str, object]:
        loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
            raise CorpusValidationError(f"{path.name}: expected a mapping of field names")
        return {str(key): value for key, value in loaded.items()}

    @staticmethod
    def _names(path: Path, key: str) -> list[str]:
        values = ActivityCatalogue._mapping(path).get(key)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise CorpusValidationError(f"{path.name}: {key} must be a list of names")
        return [str(value) for value in values]


class CatalogueActivitySource:
    """Satisfies ActivitySource: enabled entries that fit the learner's age and the season."""

    def __init__(self, catalogue: ActivityCatalogue) -> None:
        self._catalogue = catalogue

    @property
    def materials(self) -> frozenset[str]:
        return self._catalogue.materials

    def find(self, activity_id: str) -> Activity | None:
        """An activity by id, whatever its status: an open one may since have been retired."""
        for activity in self._catalogue.activities:
            if activity.id == activity_id:
                return activity
        return None

    async def candidates(self, learner: Learner, today: date) -> list[Activity]:
        age = StageRules.age_on(learner.birth_year, today)
        return [
            activity
            for activity in self._catalogue.enabled
            if ActivityChooser.fits(activity, age, today)
        ]
