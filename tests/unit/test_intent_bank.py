"""The intent bank stays a valid, useful test set (scripts/intent_bank.py runs it live)."""

from collections import Counter

import pytest

from app.domain.enums import ParentIntent
from scripts.intent_bank import OPEN_KHOJ_TITLE, IntentBank

pytestmark = pytest.mark.unit

BANK = IntentBank.load()


def test_every_intent_has_at_least_five_cases() -> None:
    counts = Counter(case.intent for case in BANK.cases)
    assert {intent: counts[intent] for intent in ParentIntent if counts[intent] < 5} == {}


def test_no_message_is_in_the_bank_twice() -> None:
    texts = Counter(case.text.strip().lower() for case in BANK.cases)
    assert [text for text, count in texts.items() if count > 1] == []


def test_a_report_always_has_a_khoj_open() -> None:
    # without an open khoj, the reader's definition makes it a question
    assert [
        case.text
        for case in BANK.cases
        if case.intent is ParentIntent.REPORT and not case.open_khoj
    ] == []


def test_the_bank_covers_hindi_hinglish_english_and_braj() -> None:
    devanagari = [case for case in BANK.cases if any("ऀ" <= letter <= "ॿ" for letter in case.text)]
    braj = [
        case
        for case in BANK.cases
        if any(word in case.text.lower().split() for word in ("mero", "vaako", "lala", "rao"))
    ]
    asked = [case for case in BANK.cases if case.asked is not None]
    assert len(devanagari) >= 10
    assert len(braj) >= 2
    assert len(asked) >= 8


def test_braj_is_checked_both_ways() -> None:
    # Braj forms must turn the voice on, and plain Hindi must not (critic review, 2026-11-01)
    checked = Counter(case.braj for case in BANK.cases if case.braj is not None)
    assert checked[True] >= 10
    assert checked[False] >= 5


def test_report_about_is_given_only_for_reports_it_could_name() -> None:
    offered = OPEN_KHOJ_TITLE
    for case in BANK.cases:
        if case.report_about is None:
            continue
        assert case.intent is ParentIntent.REPORT, case.text
        assert case.report_about in {offered, *case.other_khojs}, case.text


def test_child_name_is_given_only_for_naming_cases() -> None:
    named = [case for case in BANK.cases if case.child_name is not None]
    assert len(named) >= 5
    assert [case.text for case in named if case.intent is not ParentIntent.CHILD_NAME] == []


def test_the_off_topic_section_has_judge_and_village_messages() -> None:
    off_topic = [case for case in BANK.cases if case.section == "off_topic"]
    assert len(off_topic) >= 10
    assert {case.lang for case in off_topic} >= {"english", "hinglish", "hindi"}
