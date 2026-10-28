"""MemoryLayer: a short rolling memory, with nothing that looks like a number or an email
(s12 §4.7)."""

from datetime import UTC, datetime

import pytest

from app.domain.models.student import MemoryUpdate, ProfileMemory
from app.layers.memory_layer import MemoryLayer
from tests.fakes.language_model import FakeLanguageModel
from tests.support.prompts import shipped_registry

pytestmark = pytest.mark.unit

UPDATE = {
    "summary": "The student is in class 9 and wants to become a doctor.",
    "ambitions": ["doctor (NEET)"],
    "constraints": ["family money is tight"],
}


async def test_the_update_gets_the_previous_memory_and_the_exchange_as_data() -> None:
    llm = FakeLanguageModel([UPDATE])
    previous = ProfileMemory(
        summary="Likes biology.", ambitions=["science"], constraints=[],
        updated_at=datetime(2026, 10, 1, tzinfo=UTC),
    )  # fmt: skip
    update, _, version = await MemoryLayer(llm, shipped_registry()).update(
        previous, "doctor banna hai par paise nahi hain", "NEET ke baare mein…"
    )
    assert update.ambitions == ["doctor (NEET)"]
    assert version == "1.0.0"
    [prompt] = llm.prompts
    assert "Likes biology." in prompt.user
    assert "doctor banna hai" in prompt.user
    assert "doctor banna hai" not in prompt.system


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        ("summary", "Call him on 9876543210.", "6 or more digits"),
        ("summary", "Aadhaar 123456 shared", "6 or more digits"),
        ("constraints", ["write to me at kid@example.com"], "email"),
    ],
)
def test_anything_like_a_phone_id_or_email_is_refused(
    field: str, value: object, problem: str
) -> None:
    update = MemoryUpdate.model_validate({**UPDATE, field: value})
    assert problem in " | ".join(MemoryLayer.privacy_problems(update))


def test_class_numbers_and_short_numbers_are_fine() -> None:
    update = MemoryUpdate.model_validate({**UPDATE, "summary": "Class 10, scored 85 in maths."})
    assert MemoryLayer.privacy_problems(update) == []


@pytest.mark.parametrize(
    "change",
    [
        {"summary": "x" * 601},
        {"ambitions": ["a"] * 6},
        {"constraints": ["x" * 61]},
        {"ambitions": ["  "]},
    ],
)
def test_the_memory_has_hard_limits(change: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="validation error"):
        MemoryUpdate.model_validate({**UPDATE, **change})
