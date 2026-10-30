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
        "मेरो बच्चा दस साल को है, वाय कैसे पढ़ाऊं?",  # a mother's real voice note, 2026-10-29
        "mero lala, vaay kaise padhaun",
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
        "वाह, मेरा बेटा पढ़ता है",  # "वाह" is not the Braj "वाय"
        "waah, mera beta padhta hai",
        "My son doesn't study",
        "",
        "🙏😊",
    ],
)
def test_standard_hindi_and_one_form_alone_are_not_braj(text: str) -> None:
    assert not braj(text)


@pytest.mark.parametrize(
    "heard",
    [
        "मेरोमेरो लाला दिन भर मोबाइल देख तो है, वाको का करूँ?",  # a word written twice
        "मेरी ललितक्षु नाय बोलत बस इसारे करत है।.",  # two words run together
        "मेरो चोरा स्कूल नाई रह्यो आ",  # after the Gujarati script was put back
    ],
)
def test_braj_still_shows_through_speech_to_text_slips(heard: str) -> None:
    """What Muse Voice Transcribe made of three spoken Braj lines (owner's check, 2026-10-28)."""
    assert braj(heard)


@pytest.mark.parametrize(
    "text",
    [
        "वो खेलते हैं और बोलते हैं",  # "खेलत" and "बोलत" sit inside the standard -ते forms
        "हम रोज़ देखते हैं और करते हैं",
        "बच्चा बोलता है, खेलता है",
        "Woh karate class jaata hai",  # Roman forms only count as whole words
        "story sunao, toy chahiye",
    ],
)
def test_standard_hindi_verb_endings_are_not_braj(text: str) -> None:
    assert not braj(text)


BRAJ_BELT = ["Karauli, Rajasthan", "Mathura", "AGRA, Uttar Pradesh", "भरतपुर", "Deeg"]


@pytest.mark.parametrize("district", BRAJ_BELT)
@pytest.mark.parametrize(
    "text",
    [
        "Namaste",
        "Main aage padhna chahti hoon par ghar wale shaadi ki baat kar rahe hain",  # owner's test
        "मेरा बच्चा पढ़ाई में मन नहीं लगाता",
    ],
)
def test_a_braj_district_alone_is_not_braj(district: str, text: str) -> None:
    """Owner, 2026-10-31: in Karauli too, Hinglish or Hindi words get Hinglish or Hindi."""
    assert not braj(text, district)


@pytest.mark.parametrize("district", BRAJ_BELT)
def test_in_a_braj_district_one_braj_form_is_enough(district: str) -> None:
    assert braj("mero lala padhai mein dhyan nahi deta", district)


@pytest.mark.parametrize("district", ["Barmer, Rajasthan", "Bahraich", "Nashik", None, ""])
def test_elsewhere_one_form_is_not_enough(district: str | None) -> None:
    assert not braj("mero lala padhai mein dhyan nahi deta", district)


ORDINARY = st.text(
    alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyz कखगमनपरलसह😊?.")), max_size=60
)


@given(ORDINARY)
@example("चल रहा है")
def test_detection_is_a_pure_function_of_its_inputs(text: str) -> None:
    assert braj(text) == braj(text)
    assert braj(text, "Mathura") >= braj(text)  # a Braj district only ever lowers the bar


@pytest.mark.parametrize("register", [Language.HINDI, Language.HINGLISH])
def test_a_braj_speaker_gets_light_braj_and_village_examples(register: Language) -> None:
    line = LocalVoice.rule(register, "Karauli, Rajasthan", "mero lala padhai nahi karta")
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
