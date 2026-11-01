"""How a student's level reads to a model, and which sources it may see (field test)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.models.conversation import GRADUATE
from app.domain.rules.student_level import StudentLevel

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("grade", "said"),
    [(9, "class 9"), (12, "class 12"), (GRADUATE, "graduate (past class 12)"), (None, "not known")],
)
def test_a_level_is_said_in_words_never_class_13(grade: int | None, said: str) -> None:
    assert StudentLevel.describe(grade) == said


def test_a_graduate_sees_every_source_not_only_school_ones() -> None:
    assert StudentLevel.retrieval_grade(GRADUATE) is None


@given(grade=st.integers(1, 12))
def test_a_school_class_is_filtered_by_itself(grade: int) -> None:
    assert StudentLevel.retrieval_grade(grade) == grade
    assert StudentLevel.describe(grade) == f"class {grade}"
