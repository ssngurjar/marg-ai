"""ChildSessionRules: when a child's own conversation starts, ends, and may start again
(s10b §4.16, s05 router rules 1a and 6a). Pure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar

from app.domain.models.child_session import ChildSession
from app.domain.models.learner import Learner
from app.domain.rules.phrase_finder import PhraseFinder

KID_START = "kid:start"  # + ":<learner id>" when it names a child


@dataclass(frozen=True, slots=True)
class ChildSessionLimits:
    max_turns: int  # CHILD_SESSION_MAX_TURNS: answered turns per session
    max_duration: timedelta  # CHILD_SESSION_MAX_MINUTES
    cooldown: timedelta  # CHILD_SESSION_COOLDOWN_MINUTES between sessions


class ChildSessionRules:
    GOODBYE_PHRASES: ClassVar[tuple[str, ...]] = (
        "bye", "bye bye", "bas", "bas karo", "tata", "ta ta", "alvida", "goodbye", "that's all",
        "बाय", "बस", "टाटा", "अलविदा",
    )  # fmt: skip
    INTRODUCTION_TEMPLATES: ClassVar[tuple[str, ...]] = (
        "main {name} hoon", "main {name} hu", "main {name} hun", "mai {name} hoon",
        "mai {name} hu", "{name} bol rahi hoon", "{name} bol raha hoon", "{name} bol rahi hu",
        "{name} bol raha hu", "i am {name}", "i'm {name}", "this is {name}", "मैं {name} हूँ",
        "मैं {name} हूं", "{name} बोल रही हूँ", "{name} बोल रहा हूँ",
    )  # fmt: skip

    @staticmethod
    def asks_to_start(
        user_text: str, interactive_ids: Sequence[str], learners: Sequence[Learner]
    ) -> bool:
        """A `kid:start` button, or a child introducing themselves by nickname."""
        if any(button.startswith(KID_START) for button in interactive_ids):
            return True
        return ChildSessionRules.introduced(user_text, learners) is not None

    @staticmethod
    def chosen_learner(
        interactive_ids: Sequence[str], user_text: str, learners: Sequence[Learner]
    ) -> Learner | None:
        """Which child is starting: named by the button, by their introduction, or the only
        child. None when it can't be told (several children, a bare `kid:start`)."""
        for button in reversed(interactive_ids):
            if not button.startswith(KID_START):
                continue
            named_id = button.removeprefix(KID_START).removeprefix(":")
            for learner in learners:
                if named_id and str(learner.id) == named_id:
                    return learner
        introduced = ChildSessionRules.introduced(user_text, learners)
        if introduced is not None:
            return introduced
        return learners[0] if len(learners) == 1 else None

    @staticmethod
    def introduced(user_text: str, learners: Sequence[Learner]) -> Learner | None:
        """The learner whose nickname the child introduced themselves with ("Main Munni
        hoon"), matched as whole words."""
        for learner in learners:
            if not learner.nickname:
                continue
            phrases = [
                template.format(name=learner.nickname)
                for template in ChildSessionRules.INTRODUCTION_TEMPLATES
            ]
            if PhraseFinder.contains_any(user_text, phrases):
                return learner
        return None

    @staticmethod
    def says_goodbye(user_text: str) -> bool:
        """The whole message is a goodbye ("bye", "bas"); "bas ek sawaal aur" is not."""
        return PhraseFinder.is_exactly(user_text, ChildSessionRules.GOODBYE_PHRASES)

    @staticmethod
    def is_over(session: ChildSession, now: datetime, limits: ChildSessionLimits) -> bool:
        """Every allowed turn answered, or the time is up."""
        if session.turns_count >= limits.max_turns:
            return True
        return now - session.started_at >= limits.max_duration

    @staticmethod
    def is_last_turn(session: ChildSession, limits: ChildSessionLimits) -> bool:
        """This turn is the last one the session allows: answer it, then say goodbye."""
        return session.turns_count + 1 >= limits.max_turns

    @staticmethod
    def in_cooldown(
        last_ended_at: datetime | None, now: datetime, limits: ChildSessionLimits
    ) -> bool:
        return last_ended_at is not None and now - last_ended_at < limits.cooldown
