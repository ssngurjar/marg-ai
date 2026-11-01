"""The intent bank stays a valid, useful test set (scripts/intent_bank.py runs it live)."""

from collections import Counter

import pytest

from app.domain.enums import ParentIntent
from scripts.intent_bank import IntentBank

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
