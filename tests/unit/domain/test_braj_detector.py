"""BrajDetector and LocalVoice: light Braj for a Braj speaker, village examples for everyone
(owner, 2026-10-28)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.constants.braj_words import BRAJ_DISTRICTS, BRAJ_MARKERS, BRAJ_RULE, VILLAGE_RULE
from app.domain.enums import Language
from app.domain.rules.braj_detector import BrajDetector
from app.layers.local_voice import LocalVoice

pytestmark = pytest.mark.unit


def braj(text: str, district: str | None = None) -> bool:
    return BrajDetector.speaks_braj(text, district, BRAJ_MARKERS, BRAJ_DISTRICTS)


@pytest.mark.parametrize(
    "text",
    [
        "mero chhora naay padh rao",
        "मेरो छोरा स्कूल नाय गयो",
        "Tero lala ka kar rae ho aaj?",
        "मोय बताओ, वाको का करनो है",
        "Mero lala din bhar mobile dekhto hai, vaako ka karun?",  # translation-007
    ],
)
def test_two_braj_forms_mean_a_braj_speaker(text: str) -> None:
    assert braj(text)


@pytest.mark.parametrize(
    "text",
    [
        "Mera beta padhai nahi karta",  # standard Hindi
        "मेरा बेटा स्कूल नहीं गया",
        "chhora bahut shaitan hai",  # one form alone is common across north India
        "My son doesn't study",
        "",
        "🙏😊",
    ],
)
def test_standard_hindi_and_one_form_alone_are_not_braj(text: str) -> None:
    assert not braj(text)


@pytest.mark.parametrize(
    "district", ["Karauli, Rajasthan", "Mathura", "AGRA, Uttar Pradesh", "भरतपुर", "Deeg"]
)
def test_a_braj_district_is_enough(district: str) -> None:
    assert braj("Namaste", district)


@pytest.mark.parametrize("district", ["Barmer, Rajasthan", "Bahraich", "Nashik", None, ""])
def test_other_districts_are_not(district: str | None) -> None:
    assert not braj("Namaste", district)


ORDINARY = st.text(
    alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyz कखगमनपरलसह😊?.")), max_size=60
)


@given(ORDINARY)
@example("चल रहा है")
def test_detection_is_a_pure_function_of_its_inputs(text: str) -> None:
    assert braj(text) == braj(text)
    assert braj(text, "Mathura")  # a Braj district always counts


@pytest.mark.parametrize("register", [Language.HINDI, Language.HINGLISH])
def test_a_braj_speaker_gets_light_braj_and_village_examples(register: Language) -> None:
    line = LocalVoice.rule(register, "Karauli, Rajasthan", "Namaste")
    assert line.startswith(VILLAGE_RULE)
    assert BRAJ_RULE[register] in line


def test_english_never_gets_braj_even_in_mathura() -> None:
    assert LocalVoice.rule(Language.ENGLISH, "Mathura", "mero chhora naay padh rao") == (
        VILLAGE_RULE
    )


def test_everyone_else_gets_village_examples_only() -> None:
    assert LocalVoice.rule(Language.HINGLISH, "Barmer", "Mera beta padhai nahi karta") == (
        VILLAGE_RULE
    )
