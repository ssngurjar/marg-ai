"""ChildSessionRules: when a child's own conversation starts, ends, and may start again
(s10b §4.16, s05 router rules 1a and 6a). Pure.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final

from app.domain.models.child_session import ChildSession
from app.domain.models.learner import Learner
from app.domain.rules.phrase_finder import PhraseFinder

KID_START = "kid:start"  # + ":<learner id>" when it names a child
KID_PARENT = "kid:parent"  # "Yes, I'm the parent": ends the child's session (owner, 2026-11-01)


@dataclass(frozen=True, slots=True)
class ChildSessionLimits:
    max_turns: int  # CHILD_SESSION_MAX_TURNS: answered turns per session
    max_duration: timedelta  # CHILD_SESSION_MAX_MINUTES
    cooldown: timedelta  # CHILD_SESSION_COOLDOWN_MINUTES between sessions


class ChildSessionRules:
    # "Main bachcha hoon", as the reply after the parent's yes tells them to say it (owner's field
    # test, 2026-11-01: a typed "mai bacha hun" was answered "who is writing?")
    I_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"main", "mai", "mein", "me", "i", "im", "मैं", "मै"}
    )
    CHILD_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "bachcha", "baccha", "bacha", "bachha", "bachchi", "bacchi", "bachi", "bachhi",
            "child", "kid", "बच्चा", "बच्ची",
        }
    )  # fmt: skip
    FILLER_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"hoon", "hu", "hun", "hu.", "am", "the", "a", "हूँ", "हूं", "हू"}
    )
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
        """A `kid:start` button, a child introducing themselves by nickname, or "main bachcha
        hoon" when there is a child on the list."""
        if any(button.startswith(KID_START) for button in interactive_ids):
            return True
        if learners and ChildSessionRules.says_i_am_the_child(user_text):
            return True
        return ChildSessionRules.introduced(user_text, learners) is not None

    @staticmethod
    def says_i_am_the_child(text: str) -> bool:
        """Only "main bachcha hoon", "mai bacha hun", "मैं बच्ची हूँ", "I am the child", "I'm the
        child" (the English reply's own words: the apostrophe is dropped, "I'm" is "im")."""
        unquoted = text.replace("'", "").replace("\u2019", "")
        said = {ChildSessionRules._squeezed(word) for word in PhraseFinder.words(unquoted)}
        only_these = said <= _I_WORDS | _CHILD_WORDS | _FILLER_WORDS
        return only_these and bool(said & _CHILD_WORDS) and bool(said & _I_WORDS)

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
        allowed = [learner for learner in learners if learner.child_talk_consented_at is not None]
        if ChildSessionRules.says_i_am_the_child(user_text) and len(allowed) == 1:
            return allowed[0]  # "main bachcha hoon": the one child the parent said yes for
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

    # A parent taking the phone back (owner's demos, 2026-11-01: "i am parent", "Mein parent
    # hoon", "munni ki summary do" were answered as the child). Only asks: the "Yes, I'm the
    # parent" button ends the session. Words are compared after PhraseFinder.normalise.
    SELF_HINDI: ClassVar[frozenset[str]] = frozenset({"main", "mein", "mai", "me", "मै", "मैं"})
    SELF_ENGLISH: ClassVar[frozenset[str]] = frozenset({"i", "im"})
    PARENT_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "parent", "parents", "mummy", "mumma", "mummi", "mom", "mother", "maa", "mata",
            "ammi", "papa", "pappa", "dad", "father", "pita", "abba", "guardian",
            "मम्मी", "माँ", "मा", "माता", "पापा", "पिता", "अभिभावक",
        }
    )  # fmt: skip
    I_AM_WORDS: ClassVar[frozenset[str]] = frozenset({"hoon", "hun", "hu", "hoo", "हू", "हु"})
    SWITCH_PHRASES: ClassVar[tuple[str, ...]] = (
        "switch to parent", "parent mode", "parent here", "parent bol", "mummy bol rahi",
        "papa bol raha", "back to parent", "parent ki chat", "मम्मी बोल रही", "पापा बोल रहे",
    )  # fmt: skip
    ABOUT_CHILD_PARTICLES: ClassVar[frozenset[str]] = frozenset(
        {"ne", "ki", "ka", "ko", "ke", "ने", "की", "का", "को", "के"}
    )
    PARENT_ASKS: ClassVar[frozenset[str]] = frozenset(
        {"summary", "progress", "report", "सारांश", "प्रगति"}
    )
    WITHIN: ClassVar[int] = 3  # how far after "main"/"I" the parent word may come

    @staticmethod
    def claims_to_be_parent(user_text: str, child_nickname: str | None) -> bool:
        """Someone on the phone seems to be the child's parent: "I'm her mother", "mein parent
        hoon", "switch to parent", the child named in the third person ("Munni ne aaj kya
        kiya"), or a summary asked for. "main mummy ko bataungi" (I'll tell mummy) is not."""
        if PhraseFinder.contains_any(user_text, ChildSessionRules.SWITCH_PHRASES):
            return True
        words = PhraseFinder.words(user_text)
        if set(words) & ChildSessionRules.PARENT_ASKS:
            return True
        if ChildSessionRules._names_the_child(words, child_nickname):
            return True
        return ChildSessionRules._says_i_am_a_parent(words)

    @staticmethod
    def _says_i_am_a_parent(words: Sequence[str]) -> bool:
        rules = ChildSessionRules
        for position, word in enumerate(words):
            ahead = words[position + 1 : position + 1 + rules.WITHIN]
            for offset, later in enumerate(ahead):
                if later not in rules.PARENT_WORDS:
                    continue
                says_am = position + 1 < len(words) and words[position + 1] in {"am", "m"}
                if word in rules.SELF_ENGLISH and says_am:
                    return True  # "i am her mother", "i'm the parent"; not "i want my mummy"
                after = words[position + 1 + offset + 1 : position + 1 + offset + 2]
                if word in rules.SELF_HINDI and set(after) & rules.I_AM_WORDS:
                    return True  # "mein parent hoon", "main uski mummy hoon"
        return False

    @staticmethod
    def _names_the_child(words: Sequence[str], child_nickname: str | None) -> bool:
        """The talking child named in the third person ("munni ne", "munni ki"): a grown-up."""
        if not child_nickname:
            return False
        name = PhraseFinder.words(child_nickname)
        if len(name) != 1:
            return False
        for position, word in enumerate(words[:-1]):
            if word == name[0] and words[position + 1] in ChildSessionRules.ABOUT_CHILD_PARTICLES:
                return True
        return False

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


def _normalised(words: frozenset[str]) -> frozenset[str]:
    return frozenset(PhraseFinder.words(" ".join(words)))


_I_WORDS: Final = _normalised(ChildSessionRules.I_WORDS)
_CHILD_WORDS: Final = _normalised(ChildSessionRules.CHILD_WORDS)
_FILLER_WORDS: Final = _normalised(ChildSessionRules.FILLER_WORDS)
