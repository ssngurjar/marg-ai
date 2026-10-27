"""ActivityValidator: a catalogue entry is safe to serve, or the app refuses to start (s10b §4.3).

Every rule names the field it rejects. The same validator will check generated activities later
(s10b §4.5), so safety doesn't depend on where an activity came from.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import ClassVar

from pydantic import ValidationError

from app.core.errors import CorpusValidationError
from app.domain.models.activity import Activity
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.phrase_finder import PhraseFinder


class ActivityValidator:
    YOUNGEST: ClassVar[int] = 3
    OLDEST: ClassVar[int] = 8  # the foundational stage: the MVP's journey
    STEP_MAX_CHARS: ClassVar[int] = 160
    PURCHASE_WORDS: ClassVar[tuple[str, ...]] = (
        "buy", "bought", "purchase", "shop", "kharid", "kharido", "kharidna", "kharidiye",
        "dukaan se", "dukan se", "rupees", "rupaye", "rs", "ख़रीद", "खरीद", "दुकान से", "रुपये",
    )  # fmt: skip

    @staticmethod
    def validate(
        raw: Mapping[str, object],
        *,
        materials: frozenset[str],
        hazards: frozenset[str],
        hazard_words: Mapping[str, Sequence[str]],
    ) -> Activity:
        """The Activity, or CorpusValidationError naming the field that's wrong."""
        try:
            activity = Activity.model_validate(raw)
        except ValidationError as exc:
            fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
            raise CorpusValidationError(
                f"invalid or missing field(s): {', '.join(fields)}"
            ) from exc
        problems = ActivityValidator.problems(
            activity, materials=materials, hazards=hazards, hazard_words=hazard_words
        )
        if problems:
            raise CorpusValidationError(f"activity {activity.id}: {'; '.join(problems)}")
        return activity

    @staticmethod
    def problems(
        activity: Activity,
        *,
        materials: frozenset[str],
        hazards: frozenset[str],
        hazard_words: Mapping[str, Sequence[str]],
    ) -> list[str]:
        problems: list[str] = []
        if activity.age_min < ActivityValidator.YOUNGEST:
            problems.append(f"age_min: below {ActivityValidator.YOUNGEST}")
        if activity.age_max > ActivityValidator.OLDEST:
            problems.append(f"age_max: above {ActivityValidator.OLDEST}")
        if activity.age_min > activity.age_max:
            problems.append("age_min: greater than age_max")
        unknown_materials = sorted(set(activity.materials) - materials)
        if unknown_materials:
            problems.append(f"materials: not on the list: {', '.join(unknown_materials)}")
        unknown_hazards = sorted(set(activity.hazards) - hazards)
        if unknown_hazards:
            problems.append(f"hazards: not on the list: {', '.join(unknown_hazards)}")
        if len(activity.safety_notes) < len(activity.hazards):
            problems.append("safety_notes: each declared hazard needs a note")
        long_steps = [
            index for index, step in enumerate(activity.steps, start=1)
            if len(step) > ActivityValidator.STEP_MAX_CHARS
        ]  # fmt: skip
        if long_steps:
            problems.append(f"steps: longer than {ActivityValidator.STEP_MAX_CHARS} characters")
        undeclared = ChildHazardMatcher.undeclared(
            " ".join(activity.steps), hazard_words, activity.hazards
        )
        if undeclared:
            problems.append(f"steps: mention undeclared hazards: {', '.join(sorted(undeclared))}")
        if ActivityValidator.mentions_buying(ActivityValidator._texts(activity)):
            problems.append("text: asks for something to be bought")
        if activity.status == "enabled" and not (
            activity.reviewed_by_role and activity.reviewed_on
        ):
            problems.append("status: enabled needs reviewed_by_role and reviewed_on")
        return problems

    @staticmethod
    def mentions_buying(texts: Iterable[str]) -> bool:
        for text in texts:
            if "₹" in text or PhraseFinder.contains_any(text, ActivityValidator.PURCHASE_WORDS):
                return True
        return False

    @staticmethod
    def _texts(activity: Activity) -> list[str]:
        return [
            activity.title,
            *activity.steps,
            *activity.questions_to_ask,
            activity.listen_for,
            *activity.parent_tips,
        ]
