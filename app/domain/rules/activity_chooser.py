"""ActivityChooser: which khoj today, deterministically (s10b §4.6). Pure.

The model makes the chosen activity feel personal; it never chooses it. Rotation through
domains keeps the child's breadth growing; following what lights the child up is allowed on
at most one pick in three, so the child doesn't narrow too early.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import ClassVar, Literal

from app.domain.enums import CuriosityDomain
from app.domain.models.activity import Activity, PastActivity

type ActiveSeason = Literal["summer", "monsoon", "winter"]


@dataclass(frozen=True, slots=True)
class _Scored:
    score: int
    activity_id: str
    activity: Activity


class ActivityChooser:
    RECENT_DOMAINS_WINDOW: ClassVar[int] = 5  # "+3 for each domain not in the last 5"
    UNSEEN_DOMAIN_POINTS: ClassVar[int] = 3
    ENGAGED_DOMAIN_POINTS: ClassVar[int] = 2
    SEASON_POINTS: ClassVar[int] = 1
    ENGAGEMENT_EVERY: ClassVar[int] = 3  # the engagement boost applies on 1 pick in 3
    SUMMER_MONTHS: ClassVar[range] = range(3, 7)  # March to June
    MONSOON_MONTHS: ClassVar[range] = range(7, 10)  # July to September; the rest is winter

    @staticmethod
    def season_of(today: date) -> ActiveSeason:
        """Mar-Jun summer, Jul-Sep monsoon, Oct-Feb winter (north Indian seasons)."""
        if today.month in ActivityChooser.SUMMER_MONTHS:
            return "summer"
        if today.month in ActivityChooser.MONSOON_MONTHS:
            return "monsoon"
        return "winter"

    @staticmethod
    def fits(activity: Activity, age: int, today: date) -> bool:
        """Enabled, made for this age, and right for the season."""
        in_season = activity.season in {"any", ActivityChooser.season_of(today)}
        return (
            activity.status == "enabled"
            and activity.age_min <= age <= activity.age_max
            and (in_season)
        )

    @staticmethod
    def choose(
        candidates: Sequence[Activity],
        history: Sequence[PastActivity],
        engaged_domains: Collection[CuriosityDomain],
        today: date,
        repeat_window: timedelta,
    ) -> Activity | None:
        """The best candidate for today; None only when there are no candidates at all.
        `history` is this learner's, newest first."""
        if not candidates:
            return None
        recent_ids = {
            past.activity_id for past in history if past.offered_at.date() > today - repeat_window
        }
        fresh = [activity for activity in candidates if activity.id not in recent_ids]
        if not fresh:
            return ActivityChooser._oldest_offered(candidates, history)
        recent_domains = {
            domain
            for past in history[: ActivityChooser.RECENT_DOMAINS_WINDOW]
            for domain in past.domains
        }
        boost_engagement = len(history) % ActivityChooser.ENGAGEMENT_EVERY == 0
        scored = [
            _Scored(
                ActivityChooser._score(
                    activity, recent_domains, engaged_domains, today, boost=boost_engagement
                ),
                activity.id,
                activity,
            )
            for activity in fresh
        ]
        highest_first = sorted(scored, key=lambda item: (-item.score, item.activity_id))
        return highest_first[0].activity  # ties go to the smallest id: reproducible

    @staticmethod
    def _score(
        activity: Activity,
        recent_domains: Collection[CuriosityDomain],
        engaged_domains: Collection[CuriosityDomain],
        today: date,
        *,
        boost: bool,
    ) -> int:
        unseen = sum(1 for domain in activity.domains if domain not in recent_domains)
        score = unseen * ActivityChooser.UNSEEN_DOMAIN_POINTS
        if boost and any(domain in engaged_domains for domain in activity.domains):
            score += ActivityChooser.ENGAGED_DOMAIN_POINTS
        if activity.season == ActivityChooser.season_of(today):
            score += ActivityChooser.SEASON_POINTS
        return score

    @staticmethod
    def _oldest_offered(
        candidates: Sequence[Activity], history: Sequence[PastActivity]
    ) -> Activity:
        """Everything was offered recently: repeat the one offered longest ago."""
        last_offered: dict[str, int] = {}
        for position, past in enumerate(history):  # newest first: lower position = more recent
            last_offered.setdefault(past.activity_id, position)
        return max(
            candidates,
            key=lambda activity: (last_offered.get(activity.id, -1), _reverse_id(activity.id)),
        )


def _reverse_id(activity_id: str) -> tuple[int, ...]:
    """Ties break by id, smallest first, inside a max(): negate the code points."""
    return tuple(-ord(character) for character in activity_id)
