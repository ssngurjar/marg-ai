"""ProgressReport: what a parent sees when they ask how their child is doing (owner,
2026-11-01). Built by code from the record, in reviewed wording: the khojs done and skipped in
the last 30 days, what they explored, and what the child asked Marg about in their own talks,
by topic. Never the child's words, and no model writes it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar

from app.constants.child_talk_copy import TOPIC_LABELS
from app.constants.journey_copy import (
    PROGRESS_ASKED,
    PROGRESS_DONE,
    PROGRESS_EXPLORED,
    PROGRESS_HEADER,
    PROGRESS_NOTHING_YET,
    PROGRESS_SKIPPED,
    UNNAMED_CHILD,
)
from app.domain.enums import ActivityStatus, CuriosityDomain, Language
from app.domain.models.activity import Activity, OfferRecord
from app.domain.models.learner import Learner
from app.domain.models.progress import ChildTalkTopics
from app.domain.rules.stage_rules import StageRules

type ActivityLookup = Callable[[str], Activity | None]


@dataclass(frozen=True, slots=True)
class ProgressRecord:
    """What the report is built from: every child's recent khojs and child-talk topics."""

    activities: Sequence[OfferRecord]
    child_talk: Sequence[ChildTalkTopics]


class ProgressReport:
    WINDOW: ClassVar[timedelta] = timedelta(days=30)
    MAX_TITLES: ClassVar[int] = 5  # titles listed; the count covers the rest

    @staticmethod
    def text(
        learners: Sequence[Learner],
        record: ProgressRecord,
        *,
        find: ActivityLookup,
        now: datetime,
        register: Language,
    ) -> str:
        """One paragraph per child, in the order they were added."""
        paragraphs = [
            ProgressReport._for_child(learner, record, find=find, now=now, register=register)
            for learner in learners
        ]
        return "\n\n".join(paragraphs)

    @staticmethod
    def _for_child(
        learner: Learner,
        record: ProgressRecord,
        *,
        find: ActivityLookup,
        now: datetime,
        register: Language,
    ) -> str:
        name = learner.nickname or UNNAMED_CHILD[register].format(
            age=StageRules.age_on(learner.birth_year, now.date())
        )
        done: list[Activity] = []
        skipped = 0
        for offer in record.activities:
            if offer.learner_id != learner.id or now - offer.offered_at > ProgressReport.WINDOW:
                continue
            if offer.status is ActivityStatus.SKIPPED:
                skipped += 1
            activity = find(offer.activity_id)
            if offer.status is ActivityStatus.DONE and activity is not None:
                done.append(activity)
        asked: list[CuriosityDomain] = []
        for talk in record.child_talk:
            if talk.learner_id == learner.id:
                asked.extend(talk.topics)
        if not done and not asked:
            return PROGRESS_NOTHING_YET[register].format(name=name)
        lines = [PROGRESS_HEADER[register].format(name=name)]
        if done:
            titles = ", ".join(activity.title for activity in done[: ProgressReport.MAX_TITLES])
            lines.append(PROGRESS_DONE[register].format(count=len(done), titles=titles))
        if skipped:
            lines.append(PROGRESS_SKIPPED[register].format(count=skipped))
        explored_domains = [domain for activity in done for domain in activity.domains]
        explored = ProgressReport._labels(explored_domains, register)
        if explored:
            lines.append(PROGRESS_EXPLORED[register].format(topics=explored))
        asked_about = ProgressReport._labels(asked, register)
        if asked_about:
            lines.append(PROGRESS_ASKED[register].format(topics=asked_about))
        return "\n".join(lines)

    @staticmethod
    def _labels(domains: Sequence[CuriosityDomain], register: Language) -> str:
        """Each topic once, in the order first seen, in the parent's language."""
        unique = list(dict.fromkeys(domains))
        return ", ".join(TOPIC_LABELS[domain][register] for domain in unique)
