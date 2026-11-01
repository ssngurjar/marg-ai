"""A bank run reads the same in the terminal and in its saved evidence (scripts/bank_results.py)."""

import json
from collections import Counter
from dataclasses import asdict

import pytest

from scripts.bank_results import BankMiss, BankResults, BankRun

pytestmark = pytest.mark.unit

MISS = BankMiss(text="mero lala", lang="braj", wrong="braj False, not True")
RUN = BankRun(
    bank="parent_intents",
    readings=4,
    right_by_lang=Counter({"braj": 1, "hindi": 2}),
    total_by_lang=Counter({"braj": 2, "hindi": 2}),
    misses=[MISS],
)


def test_the_report_gives_the_total_and_every_language() -> None:
    report = BankResults.report(RUN)
    assert "**3/4 read right (75.0%)**" in report
    assert "| braj | 1 | 2 | 50% |" in report
    assert "| hindi | 2 | 2 | 100% |" in report
    assert "- (braj) 'mero lala': braj False, not True" in report


def test_a_clean_run_has_no_misses_section() -> None:
    clean = BankRun(
        bank="teacher_messages",
        readings=2,
        right_by_lang=Counter({"english": 2}),
        total_by_lang=Counter({"english": 2}),
    )
    assert "## Misses" not in BankResults.report(clean)
    assert clean.share_right == 1.0


def test_an_empty_run_is_zero_not_a_division_error() -> None:
    assert BankRun(bank="parent_intents", readings=0).share_right == 0.0


def test_a_miss_serialises_to_json() -> None:
    # slots dataclasses have no __dict__: the saved evidence must still carry every field
    assert json.loads(json.dumps(asdict(MISS))) == {
        "text": "mero lala",
        "lang": "braj",
        "wrong": "braj False, not True",
    }
