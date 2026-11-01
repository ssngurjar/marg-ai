"""ProgressReport: a parent's "how is my child doing?", built by code from the record."""

from datetime import timedelta

import pytest

from app.constants.child_talk_copy import TOPIC_LABELS
from app.constants.journey_copy import (
    PROGRESS_ASKED,
    PROGRESS_HEADER,
    PROGRESS_NOTHING_YET,
    PROGRESS_SKIPPED,
)
from app.domain.enums import ActivityStatus, CuriosityDomain, Language
from app.domain.models.learner import Learner
from app.domain.models.progress import ChildTalkTopics
from app.layers.activity_catalogue import CatalogueActivitySource
from app.layers.progress_report import ProgressRecord, ProgressReport
from tests.support.journey import child, offer, shipped_catalogue
from tests.support.turn_context import NOW

pytestmark = pytest.mark.unit

H = Language.HINGLISH
E = Language.ENGLISH
MUNNI = child(1, "Munni", 5)
GOLU = child(2, "Golu", 7)
ACTIVITIES = shipped_catalogue().enabled
FIND = CatalogueActivitySource(shipped_catalogue()).find


def report(
    record: ProgressRecord, register: Language = E, learners: list[Learner] | None = None
) -> str:
    return ProgressReport.text(learners or [MUNNI], record, find=FIND, now=NOW, register=register)


def test_khojs_done_and_skipped_and_what_was_explored_are_listed() -> None:
    first, second, third = ACTIVITIES[0], ACTIVITIES[1], ACTIVITIES[2]
    record = ProgressRecord(
        activities=[
            offer(first, MUNNI, hours_ago=2, status=ActivityStatus.DONE, number=1),
            offer(second, MUNNI, hours_ago=30, status=ActivityStatus.DONE, number=2),
            offer(third, MUNNI, hours_ago=50, status=ActivityStatus.SKIPPED, number=3),
        ],
        child_talk=[],
    )
    text = report(record)
    assert text.startswith(PROGRESS_HEADER[E].format(name="Munni"))
    assert f"Khojs done: 2 ({first.title}, {second.title})" in text
    assert PROGRESS_SKIPPED[E].format(count=1) in text
    for domain in first.domains:
        assert TOPIC_LABELS[domain][E] in text


def test_child_talk_topics_are_named_never_the_childs_words() -> None:
    record = ProgressRecord(
        activities=[],
        child_talk=[ChildTalkTopics(learner_id=MUNNI.id, topics=[CuriosityDomain.EARTH_SKY])],
    )
    text = report(record)
    labels = TOPIC_LABELS[CuriosityDomain.EARTH_SKY][E]
    assert PROGRESS_ASKED[E].format(topics=labels) in text


def test_a_khoj_older_than_30_days_isnt_counted() -> None:
    old = offer(ACTIVITIES[0], MUNNI, hours_ago=31 * 24, status=ActivityStatus.DONE, number=1)
    text = report(ProgressRecord(activities=[old], child_talk=[]))
    assert text == PROGRESS_NOTHING_YET[E].format(name="Munni")


def test_each_child_gets_their_own_paragraph() -> None:
    record = ProgressRecord(
        activities=[offer(ACTIVITIES[0], GOLU, hours_ago=2, status=ActivityStatus.DONE, number=1)],
        child_talk=[],
    )
    text = report(record, learners=[MUNNI, GOLU])
    munni, golu = text.split("\n\n")
    assert munni == PROGRESS_NOTHING_YET[E].format(name="Munni")
    assert golu.startswith(PROGRESS_HEADER[E].format(name="Golu"))


def test_a_khoj_no_longer_in_the_catalogue_is_left_out() -> None:
    gone = offer(ACTIVITIES[0], MUNNI, hours_ago=2, status=ActivityStatus.DONE, number=1)
    gone = gone.model_copy(update={"activity_id": "retired-activity"})
    text = report(ProgressRecord(activities=[gone], child_talk=[]))
    assert text == PROGRESS_NOTHING_YET[E].format(name="Munni")


def test_the_summary_is_in_the_parents_language() -> None:
    record = ProgressRecord(
        activities=[offer(ACTIVITIES[0], MUNNI, hours_ago=2, status=ActivityStatus.DONE, number=1)],
        child_talk=[],
    )
    assert report(record, register=H).startswith(PROGRESS_HEADER[H].format(name="Munni"))


def test_an_unnamed_child_is_called_by_age() -> None:
    unnamed = child(3, None, 6)
    text = report(ProgressRecord(activities=[], child_talk=[]), learners=[unnamed])
    assert text.startswith("Child, 6 years")


@pytest.mark.parametrize("hours_ago", [0.0, 24.0, 29 * 24.0])
def test_a_khoj_inside_the_window_counts(hours_ago: float) -> None:
    done = offer(ACTIVITIES[0], MUNNI, hours_ago=hours_ago, status=ActivityStatus.DONE, number=1)
    assert "Khojs done: 1" in report(ProgressRecord(activities=[done], child_talk=[]))
    assert timedelta(hours=hours_ago) <= ProgressReport.WINDOW
