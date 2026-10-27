"""LearnerChooser: which of a parent's children this turn is about (s10b §4.2). Pure.

1. A button that carries a learner id (`jrn:today:<id>`) wins.
2. Otherwise a nickname in the message ("Munni ne kaha…"), when exactly one child matches.
3. Otherwise the child of the latest activity offered in the last 48 hours.
4. Otherwise the only child. With several and no signal: None, and the journey asks which child.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar

from app.domain.models.learner import Learner, LearnerId
from app.domain.rules.phrase_finder import PhraseFinder


@dataclass(frozen=True, slots=True)
class RecentOffer:
    learner_id: LearnerId
    offered_at: datetime


class LearnerChooser:
    RECENT: ClassVar[timedelta] = timedelta(hours=48)

    @staticmethod
    def choose(
        learners: Sequence[Learner],
        button_learner: str | None,
        text: str,
        recent_offers: Sequence[RecentOffer],
        now: datetime,
    ) -> Learner | None:
        if button_learner is not None:
            for learner in learners:
                if str(learner.id) == button_learner:
                    return learner
        named = [
            learner
            for learner in learners
            if learner.nickname and PhraseFinder.contains_any(text, [learner.nickname])
        ]
        if len(named) == 1:
            return named[0]
        recent = [
            offer for offer in recent_offers if now - offer.offered_at <= LearnerChooser.RECENT
        ]
        if recent:
            latest = max(recent, key=lambda offer: offer.offered_at)
            for learner in learners:
                if learner.id == latest.learner_id:
                    return learner
        if len(learners) == 1:
            return learners[0]
        return None
