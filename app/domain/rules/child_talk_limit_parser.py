"""ChildTalkLimitParser: a parent asking about a child's daily talk limit (s10b §4.16). Pure.

Owner, 2026-11-13: the parent picks 20 minutes, 30 minutes or 1 hour on a button, and can type
it too, including "no limit" ("Munni ka limit hata do"), which has no button (WhatsApp allows
three). Only a message that is clearly about Marg's talk limit is read here; any other message
that says "limit" (a TV limit, an exam's age limit, "kya bachchon ki koi limit honi chahiye?")
is the parent's question, answered as before (owner, 2026-11-13: "not everything containing
limit"). Clearly about it means: it says "limit", names nothing else the limit could be for, and
either mentions Marg or talking, or carries a value (a time, or no limit), or is one of the
short commands Marg's own replies teach ("limit badlo", "Munni ki limit kitni hai").

The time is read from a number and its unit ("20 minute", "1 ghanta", "aadha ghanta", "बीस
मिनट"). A time that isn't one of the choices ("45 minute") names nothing, and nothing is
guessed: the parent is asked again. A question never sets one ("kya 1 ghanta ki limit theek
hai?"): the layer shows the limit now and the choices instead.

A parent may also ask how much of today's time is left or used ("Munni ka Marg se kitna time
bacha hai?", "aaj Munni ne kitni der baat ki?"): `asks_time_left`, as precise: it must ask about
time left, or about time used today, and be about Marg (the limit, Marg or talking, or one of
the parent's children with a time word), with nothing else the time could be for.
"""

import re
from collections.abc import Sequence
from typing import ClassVar, Final

from app.domain.enums import DailyTalkLimit
from app.domain.models.learner import Learner
from app.domain.rules.phrase_finder import PhraseFinder


class ChildTalkLimitParser:
    LIMIT_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"limit", "limits", "limt", "unlimited", "लिमिट"}
    )
    TALK_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "marg", "margai", "मार्ग", "baat", "baatein", "batein", "bate", "बात", "बातें",
            "talk", "talking", "chat", "bolne", "बोलने",
        }
    )  # fmt: skip
    """Words that say the limit is on talking to Marg."""
    OTHER_SUBJECT_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "tv", "television", "टीवी", "screen", "स्क्रीन", "mobile", "phone", "फोन", "मोबाइल",
            "game", "games", "गेम", "youtube", "cartoon", "cartoons", "कार्टून", "video",
            "videos", "वीडियो", "khana", "khane", "food", "sugar", "cheeni", "चीनी", "खाना",
            "paise", "paisa", "money", "pocket", "पैसे", "age", "umar", "umr", "उम्र", "exam",
            "pariksha", "परीक्षा", "scholarship", "income", "aay", "आय", "data", "internet",
            "speed", "credit", "loan", "marks", "seat", "seats", "cutoff", "padhai", "पढ़ाई",
            "neend", "sona", "नींद", "khelne", "खेलने", "word", "words", "shabd", "school",
            "skool", "स्कूल", "bus", "homework", "tuition", "class",
        }
    )  # fmt: skip
    """A limit on something else: never Marg's (and a message naming both is left unread)."""
    REMAINING_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "bacha", "bachaa", "bachi", "bache", "baaki", "baki", "left", "remaining", "remain",
            "बचा", "बची", "बचे", "बाकी",
        }
    )  # fmt: skip
    """Time left: "kitna time bacha hai", "how much is left"."""
    HOW_MUCH_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"kitna", "kitni", "kitne", "how", "कितना", "कितनी", "कितने"}
    )
    TODAY_WORDS: ClassVar[frozenset[str]] = frozenset({"aaj", "today", "आज"})
    TIME_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"time", "samay", "der", "minute", "minutes", "min", "समय", "देर", "मिनट", "long"}
    )
    """With one of the parent's children named, these make "kitna time bacha" about Marg."""
    QUESTION_STARTS: ClassVar[frozenset[str]] = frozenset(
        {
            "kya", "क्या", "should", "is", "are", "can", "could", "does", "would", "what",
            "how", "why", "kyun", "kyon", "क्यों", "kaisi", "kaisa",
        }
    )  # fmt: skip
    FILLER_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "ka", "ki", "ke", "ko", "kaa", "kee", "meri", "mera", "mere", "my", "the", "please",
            "pls", "plz", "ji", "bhi", "ab", "abhi", "s", "bachche", "bachchi", "beti", "beta",
            "child", "childs", "kid", "का", "की", "के", "को", "मेरी", "मेरा", "अब", "भी", "जी",
            "बच्चे", "बच्ची", "बेटी", "बेटा",
        }
    )  # fmt: skip
    """Left out when a message is compared with COMMANDS ("Munni ki limit badlo")."""
    COMMANDS: ClassVar[tuple[str, ...]] = (
        "limit", "limit badlo", "limit badal do", "limit badalni hai", "limit change karo",
        "limit change kar do", "change limit", "change the limit", "set limit", "limit set karo",
        "limit kitni hai", "limit kitna hai", "limit kya hai", "what is the limit",
        "whats the limit", "limit badhao", "limit badha do", "limit kam karo", "limit kam kar do",
        "increase limit", "increase the limit", "reduce limit", "reduce the limit", "लिमिट",
        "लिमिट बदलो", "लिमिट बदल दो", "लिमिट कितनी है", "लिमिट क्या है", "लिमिट बढ़ाओ",
        "लिमिट बढ़ा दो", "लिमिट कम करो", "लिमिट कम कर दो",
    )  # fmt: skip
    """The short ways to see or change it, as Marg's replies teach them ("limit badlo")."""
    NO_LIMIT_PHRASES: ClassVar[tuple[str, ...]] = (
        "hata do", "hata de", "hatado", "hata dijiye", "hata dijie", "hatao", "hata diya",
        "no limit", "koi limit nahi", "koi limit nhi", "limit nahi", "limit nhi", "bina limit",
        "without limit", "without a limit", "remove", "remove the limit", "unlimited",
        "khatam kar do", "khatam karo", "limit band", "mat lagao", "nahi chahiye", "nhi chahiye",
        "हटा दो", "हटा दीजिए", "हटाओ", "कोई लिमिट नही", "लिमिट नही", "बिना लिमिट", "खत्म कर दो",
        "नही चाहिए", "मत लगाओ",
    )  # fmt: skip
    MINUTE_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"min", "mins", "minute", "minutes", "minat", "mint", "मिनट"}
    )
    HOUR_WORDS: ClassVar[frozenset[str]] = frozenset(
        {"ghanta", "ghante", "ghantey", "ghanti", "hour", "hours", "hr", "hrs", "घंटा", "घंटे"}
    )
    NUMBER_WORDS: ClassVar[dict[str, int]] = {
        "ek": 1, "one": 1, "an": 1, "a": 1, "एक": 1,
        "do": 2, "two": 2, "दो": 2,
        "bees": 20, "bis": 20, "twenty": 20, "बीस": 20,
        "tees": 30, "thirty": 30, "तीस": 30,
        "saath": 60, "sath": 60, "sixty": 60, "साठ": 60,
    }  # fmt: skip
    HALF_WORDS: ClassVar[frozenset[str]] = frozenset({"aadha", "adha", "half", "आधा"})
    CHOICES_IN_MINUTES: ClassVar[dict[int, DailyTalkLimit]] = {
        20: DailyTalkLimit.MINUTES_20,
        30: DailyTalkLimit.MINUTES_30,
        60: DailyTalkLimit.MINUTES_60,
    }
    _NUMBER_THEN_UNIT: ClassVar[re.Pattern[str]] = re.compile(r"^(\d+)(\D+)$")

    @staticmethod
    def is_about_the_limit(text: str, learners: Sequence[Learner]) -> bool:
        """Clearly about a child's daily talk limit with Marg (see the module note): a parent
        asking to see or change it; a child saying it gets "ask Mummy-Papa". `learners`: the
        children whose names may come with a short command."""
        words = PhraseFinder.words(text)
        said = set(words)
        if not said & _LIMIT_WORDS or said & _OTHER_SUBJECT_WORDS:
            return False
        if said & _TALK_WORDS:
            return True
        if ChildTalkLimitParser._carries_a_value(text):
            return True
        return ChildTalkLimitParser._is_a_command(words, learners)

    @staticmethod
    def asks_time_left(text: str, learners: Sequence[Learner]) -> bool:
        """How much of a child's time with Marg is left or used today ("Munni ki limit mein
        kitna time bacha hai?", "aaj Munni ne Marg se kitni der baat ki?"). Reads nothing: never
        sets a limit."""
        said = set(PhraseFinder.words(text))
        if said & _OTHER_SUBJECT_WORDS:
            return False
        asks_left = bool(said & _REMAINING_WORDS)
        asks_used_today = bool(said & _HOW_MUCH_WORDS) and bool(said & _TODAY_WORDS)
        if not (asks_left or asks_used_today):
            return False
        if said & (_LIMIT_WORDS | _TALK_WORDS):
            return True
        names_a_child = ChildTalkLimitParser.child_named(text, learners) is not None
        return names_a_child and bool(said & _TIME_WORDS)

    @staticmethod
    def asks_a_question(text: str) -> bool:
        """ "Kya 1 ghanta ki limit theek hai?": asks, so sets nothing."""
        words = PhraseFinder.words(text)
        return text.rstrip().endswith("?") or bool(words and words[0] in _QUESTION_STARTS)

    @staticmethod
    def limit_named(text: str) -> DailyTalkLimit | None:
        """The one choice the message names: no limit, or a time that is a choice. None when
        it names none, a time that isn't a choice, or more than one."""
        named: set[DailyTalkLimit] = set()
        if PhraseFinder.contains_any(text, ChildTalkLimitParser.NO_LIMIT_PHRASES):
            named.add(DailyTalkLimit.NO_LIMIT)
        for minutes in ChildTalkLimitParser._durations_in_minutes(text):
            choice = ChildTalkLimitParser.CHOICES_IN_MINUTES.get(minutes)
            if choice is None:
                return None  # "45 minute": not a choice, never rounded to one
            named.add(choice)
        if len(named) != 1:
            return None
        return named.pop()

    @staticmethod
    def child_named(text: str, learners: Sequence[Learner]) -> Learner | None:
        """The one child whose home name the message says, as whole words."""
        words = PhraseFinder.words(text)
        named = [
            learner
            for learner in learners
            if learner.nickname and PhraseFinder.positions(words, learner.nickname)
        ]
        return named[0] if len(named) == 1 else None

    @staticmethod
    def _carries_a_value(text: str) -> bool:
        """A time ("1 ghanta", even one that isn't a choice) or no limit."""
        if PhraseFinder.contains_any(text, ChildTalkLimitParser.NO_LIMIT_PHRASES):
            return True
        return bool(ChildTalkLimitParser._durations_in_minutes(text))

    @staticmethod
    def _is_a_command(words: Sequence[str], learners: Sequence[Learner]) -> bool:
        """The message is one of COMMANDS once children's names and fillers are left out."""
        names: set[str] = set()
        for learner in learners:
            if learner.nickname:
                names.update(PhraseFinder.words(learner.nickname))
        kept = [word for word in words if word not in names and word not in _FILLER_WORDS]
        return tuple(kept) in _COMMANDS

    @staticmethod
    def _durations_in_minutes(text: str) -> list[int]:
        """Every number followed by a time unit, in minutes: "20 minute" → 20, "1 ghanta" →
        60, "aadha ghanta" / "half an hour" → 30, "20min" → 20."""
        words = ChildTalkLimitParser._split_glued(PhraseFinder.words(text))
        durations: list[int] = []
        for position, word in enumerate(words):
            if position == 0:
                continue
            if word in _MINUTE_WORDS:
                unit = 1
            elif word in _HOUR_WORDS:
                unit = 60
            else:
                continue
            amount = ChildTalkLimitParser._amount_before(words, position)
            if amount is not None:
                durations.append(round(amount * unit))
        return durations

    @staticmethod
    def _amount_before(words: Sequence[str], unit_at: int) -> float | None:
        before = words[unit_at - 1]
        if before in _HALF_WORDS:
            return 0.5  # "aadha ghanta"
        two_before = words[unit_at - 2] if unit_at > 1 else ""
        if before in {"an", "a"} and two_before in _HALF_WORDS:
            return 0.5  # "half an hour"
        if before.isdecimal():
            return float(int(before))
        number = _NUMBER_WORDS.get(before)
        return float(number) if number is not None else None

    @staticmethod
    def _split_glued(words: Sequence[str]) -> list[str]:
        """ "20min" → "20", "min"."""
        split: list[str] = []
        for word in words:
            glued = ChildTalkLimitParser._NUMBER_THEN_UNIT.match(word)
            if glued is None:
                split.append(word)
            else:
                split.extend([glued.group(1), glued.group(2)])
        return split


def _normalised(words: frozenset[str]) -> frozenset[str]:
    """The words as PhraseFinder compares them ("घंटा" → "घटा": nasal marks dropped)."""
    return frozenset(PhraseFinder.words(" ".join(words)))


_LIMIT_WORDS: Final = _normalised(ChildTalkLimitParser.LIMIT_WORDS)
_TALK_WORDS: Final = _normalised(ChildTalkLimitParser.TALK_WORDS)
_OTHER_SUBJECT_WORDS: Final = _normalised(ChildTalkLimitParser.OTHER_SUBJECT_WORDS)
_QUESTION_STARTS: Final = _normalised(ChildTalkLimitParser.QUESTION_STARTS)
_FILLER_WORDS: Final = _normalised(ChildTalkLimitParser.FILLER_WORDS)
_REMAINING_WORDS: Final = _normalised(ChildTalkLimitParser.REMAINING_WORDS)
_HOW_MUCH_WORDS: Final = _normalised(ChildTalkLimitParser.HOW_MUCH_WORDS)
_TODAY_WORDS: Final = _normalised(ChildTalkLimitParser.TODAY_WORDS)
_TIME_WORDS: Final = _normalised(ChildTalkLimitParser.TIME_WORDS)
_MINUTE_WORDS: Final = _normalised(ChildTalkLimitParser.MINUTE_WORDS)
_HOUR_WORDS: Final = _normalised(ChildTalkLimitParser.HOUR_WORDS)
_HALF_WORDS: Final = _normalised(ChildTalkLimitParser.HALF_WORDS)
_NUMBER_WORDS: Final = {
    PhraseFinder.normalise(word): number
    for word, number in ChildTalkLimitParser.NUMBER_WORDS.items()
}

_COMMANDS: Final = frozenset(
    tuple(word for word in PhraseFinder.words(command) if word not in _FILLER_WORDS)
    for command in ChildTalkLimitParser.COMMANDS
)
