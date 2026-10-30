"""The Muse Spark client's per-call limit (wiring): the longest step that makes a call."""

import pytest

from app.wiring import spark_call_limit
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.unit


def test_a_teachers_or_students_call_is_not_cut_at_the_parent_limit() -> None:
    """Regression (2026-10-31): a teacher's three-field bridge timed out at the parent's 20 s,
    because the client's timeout was TIMEOUT_GENERATE_S."""
    settings = make_settings().model_copy(
        update={"timeout_generate_s": 20.0, "timeout_exposure_s": 24.0, "timeout_mentor_s": 22.0}
    )
    assert spark_call_limit(settings) == 24.0


@pytest.mark.parametrize(
    ("generate", "exposure", "mentor", "expected"),
    [(30.0, 24.0, 24.0, 30.0), (20.0, 20.0, 26.0, 26.0), (20.0, 20.0, 20.0, 20.0)],
)
def test_the_limit_is_the_longest_step(
    generate: float, exposure: float, mentor: float, expected: float
) -> None:
    settings = make_settings().model_copy(
        update={
            "timeout_generate_s": generate,
            "timeout_exposure_s": exposure,
            "timeout_mentor_s": mentor,
        }
    )
    assert spark_call_limit(settings) == expected
