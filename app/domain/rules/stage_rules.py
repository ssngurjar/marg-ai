"""StageRules: a learner's age and NEP stage from their birth year (s10b §4.2). Pure.

Birth year only, never a full date, so ages are approximate (±1). Age 8 sits in both the
foundational and preparatory stages; the MVP treats it as foundational.
"""

from datetime import date
from typing import ClassVar

from app.core.errors import InvalidProfileValue
from app.domain.enums import AgeBand


class StageRules:
    _BANDS: ClassVar[tuple[tuple[int, AgeBand], ...]] = (
        (3, AgeBand.UNDER_3),  # ages below 3
        (9, AgeBand.FOUNDATIONAL_3_8),  # 3..8
        (11, AgeBand.PREPARATORY_8_11),  # 9..10
        (14, AgeBand.MIDDLE_11_14),  # 11..13
        (18, AgeBand.SECONDARY_14_18),  # 14..17
    )

    @staticmethod
    def age_on(birth_year: int, today: date) -> int:
        """Raises InvalidProfileValue for a birth year after today's year."""
        age = today.year - birth_year
        if age < 0:
            raise InvalidProfileValue(f"birth_year {birth_year} is in the future")
        return age

    @staticmethod
    def age_band(birth_year: int, today: date) -> AgeBand:
        age = StageRules.age_on(birth_year, today)
        for below, band in StageRules._BANDS:
            if age < below:
                return band
        return AgeBand.ADULT
