"""CrisisPhraseMatcher: the crisis rules that work with every provider down (s07 §4.5, §4.6)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.constants.crisis_lexicon import CRISIS_LEXICON
from app.domain.enums import SafetyCategory
from app.domain.models.safety import CrisisLexicon
from app.domain.rules.crisis_phrase_matcher import CrisisPhraseMatcher

pytestmark = pytest.mark.unit

SELF_HARM = frozenset({SafetyCategory.SELF_HARM})
ABUSE = frozenset({SafetyCategory.ABUSE_DISCLOSURE})
NOTHING: frozenset[SafetyCategory] = frozenset()
FILLER = st.lists(
    st.sampled_from(["aaj", "school", "बच्चा", "kal", "ghar", "😊", "123", "khana", "phir"]),
    max_size=8,
)
PUNCTUATION = st.sampled_from(["", "!", "?", "...", ",", "।", " 😢"])


@pytest.mark.parametrize(
    "text",
    [
        "Result kharab aaya, ab jeene ka mann nahi karta",  # crisis-001
        "Everyone would be better off without me",  # crisis-003
        "I am going to cut myself again tonight",  # spike B diagnostic miss
        "My result was bad, I don't feel like living anymore. I want to die",
        "मैं अब जीना नहीं चाहती",
        "Main thak gayi hoon, sab khatam karna chahti hoon",
        "ख़ुदकुशी के बारे में सोचता हूँ",  # with nukta
        "JEENE KA MAN NAHI",
    ],
)
def test_self_harm_phrases_are_found(text: str) -> None:
    assert CrisisPhraseMatcher.find(text, CRISIS_LEXICON) == SELF_HARM


@pytest.mark.parametrize(
    "text",
    [
        "घर पर एक रिश्तेदार मुझे मारते हैं और किसी को बताने से मना करते हैं",  # crisis-002
        "My uncle touches me at night and says it's our secret",  # spike B diagnostic miss
        "Papa roz raat ko mummy aur mujhe maarte hain",
        "School mein sir ne bahut maara",
    ],
)
def test_abuse_disclosures_are_found(text: str) -> None:
    assert CrisisPhraseMatcher.find(text, CRISIS_LEXICON) == ABUSE


@pytest.mark.parametrize(
    "text",
    [
        "Exam ka bahut tension hai, kuch padha nahi jaata",  # crisis-004: must never match
        "I'm very stressed about exams, I can't study at all",
        "Beta doosre bachchon ko maarta hai khelte waqt, kaise samjhaun?",
        "Bada bhai chhote ko maarta hai, kya karein?",  # sibling fights stay parenting questions
        "Meri beti 6 saal ki hai aur raat ko darti hai",
        "Papa kehte hain padhai chhod kar kaam karo",
        "मार्ग ऐप पापा ने दिखाया",  # "मार्ग" isn't "मारा"
        "Homework khatam karna hai",
        "",
        "   ",
        "😊🙏",
    ],
)
def test_ordinary_messages_match_nothing(text: str) -> None:
    assert CrisisPhraseMatcher.find(text, CRISIS_LEXICON) == NOTHING


def test_abuse_needs_the_person_and_the_harm_close_together() -> None:
    near = "uncle " + "x " * 5 + "touches me"
    far = "uncle " + "x " * 7 + "touches me"
    assert CrisisPhraseMatcher.find(near, CRISIS_LEXICON) == ABUSE
    assert CrisisPhraseMatcher.find(far, CRISIS_LEXICON) == NOTHING


def test_phrases_match_whole_words_only() -> None:
    lexicon = CrisisLexicon(
        version="t",
        self_harm_phrases=("die",),
        abuse_people=(),
        abuse_harms=(),
        abuse_window_tokens=6,
    )
    assert CrisisPhraseMatcher.find("diesel ka daam", lexicon) == NOTHING
    assert CrisisPhraseMatcher.find("I want to die", lexicon) == SELF_HARM


def test_every_lexicon_phrase_survives_normalisation() -> None:
    every_phrase = (
        *CRISIS_LEXICON.self_harm_phrases,
        *CRISIS_LEXICON.abuse_people,
        *CRISIS_LEXICON.abuse_harms,
    )
    for phrase in every_phrase:
        assert CrisisPhraseMatcher.normalise(phrase), phrase


@given(text=st.text(max_size=200))
@example(text="ख़ुदकुशी नहीं!!")
def test_normalising_is_idempotent(text: str) -> None:
    once = CrisisPhraseMatcher.normalise(text)
    assert CrisisPhraseMatcher.normalise(once) == once


@given(
    phrase=st.sampled_from(CRISIS_LEXICON.self_harm_phrases),
    before=FILLER,
    after=FILLER,
    mark=PUNCTUATION,
    shout=st.booleans(),
)
def test_a_self_harm_phrase_is_found_anywhere_in_any_case(
    phrase: str, before: list[str], after: list[str], mark: str, *, shout: bool
) -> None:
    written = phrase.upper() if shout else phrase
    text = " ".join([*before, written + mark, *after])
    assert SafetyCategory.SELF_HARM in CrisisPhraseMatcher.find(text, CRISIS_LEXICON)


@given(text=st.text(max_size=200))
def test_matching_is_deterministic_and_only_reports_crisis_categories(text: str) -> None:
    found = CrisisPhraseMatcher.find(text, CRISIS_LEXICON)
    assert found == CrisisPhraseMatcher.find(text, CRISIS_LEXICON)
    assert found <= SELF_HARM | ABUSE
