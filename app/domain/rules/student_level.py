"""StudentLevel: how a student's grade reads to a model, and which sources it may see (owner's
field test, 2026-11-01: a graduate preparing for UPSC). Pure."""

from app.domain.models.conversation import GRADUATE


class StudentLevel:
    @staticmethod
    def describe(grade: int | None) -> str:
        """ "class 9", "graduate (past class 12)", or "not known": never "class 13"."""
        if grade is None:
            return "not known"
        if grade == GRADUATE:
            return "graduate (past class 12)"
        return f"class {grade}"

    @staticmethod
    def retrieval_grade(grade: int | None) -> int | None:
        """The class sources are filtered by. A graduate isn't limited to school-tagged sources:
        most are tagged up to class 12, and exams like UPSC's are for graduates."""
        return None if grade == GRADUATE else grade
