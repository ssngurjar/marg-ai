"""ChildSessionRules: when a child's own conversation starts, ends, and may start again
(s10b §4.16, s05 router rules 1a and 6a). Pure.
"""

import re
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
    # A child names themselves the way they text (owner's test, 2026-10-29: "Mein munni hi bol
    # rhi hoon"): the name, "hi"/"toh" for emphasis, then a first-person "hoon" or "bol rahi
    # hoon". Only "hoon" makes it first person: "main"/"mein" before the name proves nothing
    # ("ghar mein Munni bol rahi thi"). Words are compared after PhraseFinder.normalise, which
    # drops the nasal marks ("हूँ" → "हू"), with stretched letters squeezed ("hooon").
    EMPHASIS_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"hi", "hee", "toh", "to", "ji", "ही", "तो"}
    )
    AM_WORDS: ClassVar[frozenset[str]] = frozenset({"hoon", "hun", "hu", "hoo", "हू", "हु"})
    SPEAKING_WORDS: ClassVar[frozenset[str]] = frozenset({"bol", "बोल"})
    SPEAKING_NOW_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"rahi", "rhi", "raha", "rha", "rahe", "rhe", "रही", "रहा"}
    )
    ENGLISH_INTRODUCTIONS: ClassVar[tuple[str, ...]] = (
        "i am {name}", "i'm {name}", "im {name}", "this is {name}", "it's {name}", "its {name}",
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
        """The learner whose nickname the child introduced themselves with ("Main Munni hoon",
        "Mein munni hi bol rhi hoon", "I'm Munni"), the name matched as whole words. A parent
        speaking about the child ("Munni bol rahi hai", "main Munni ki mummy hoon") is not."""
        words = [ChildSessionRules._squeezed(word) for word in PhraseFinder.words(user_text)]
        for learner in learners:
            if not learner.nickname:
                continue
            english = [
                template.format(name=learner.nickname)
                for template in ChildSessionRules.ENGLISH_INTRODUCTIONS
            ]
            if PhraseFinder.contains_any(user_text, english):
                return learner
            name_length = len(PhraseFinder.words(learner.nickname))
            for start in PhraseFinder.positions(words, learner.nickname):
                if ChildSessionRules._says_i_am(words[start + name_length :]):
                    return learner
        return None

    @staticmethod
    def _says_i_am(after_name: Sequence[str]) -> bool:
        """The words after the name make the sentence first person: "hoon", or "bol rahi
        hoon", after any "hi"/"toh"."""
        rest = list(after_name)
        while rest and rest[0] in ChildSessionRules.EMPHASIS_WORDS:
            rest.pop(0)
        rules = ChildSessionRules
        match rest:
            case [am, *_] if am in rules.AM_WORDS:
                return True  # "Munni hoon"
            case [speak, now, am, *_] if (
                speak in rules.SPEAKING_WORDS
                and now in rules.SPEAKING_NOW_WORDS
                and am in rules.AM_WORDS
            ):
                return True  # "Munni bol rahi hoon"
            case _:
                return False

    @staticmethod
    def _squeezed(word: str) -> str:
        """Stretched letters back to at most two ("hooooon" → "hoon")."""
        return re.sub(r"(.)\1{2,}", r"\1\1", word)

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
