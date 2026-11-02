"""SmallTalkRules: a message that only acknowledges, thanks, greets or says good night ("ok ok
ok", "ohk 🤣", "good night", "🥰"), so it gets a short fixed reply at once, with no model and no
source search (owner's field test, 2026-11-01: a student's "okay okay" took 10 s and "okk okk 🤣"
repeated the UPSC facts). Pure."""

import unicodedata
from typing import ClassVar, Final, Literal

from app.domain.rules.onboarding_answer_parser import OnboardingAnswerParser
from app.domain.rules.phrase_finder import PhraseFinder

type SmallTalk = Literal["thanks", "greeting", "good_night", "goodbye"]


class SmallTalkRules:
    MAX_WORDS: ClassVar[int] = 5
    WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "ok", "okay", "okk", "ohk", "k", "kk", "hmm", "hm", "haan", "ha", "han", "ji",
            "thanks", "thank", "you", "u", "thanku", "thnx", "thx", "shukriya", "dhanyavad",
            "dhanyawad", "accha", "acha", "achha", "theek", "thik", "hai", "good", "nice", "great",
            "sahi", "badhiya", "wah", "waah", "haha", "hahaha", "lol", "done", "fine", "sure",
            "ठीक", "है", "धन्यवाद", "शुक्रिया", "अच्छा", "हाँ", "हां", "जी", "बढ़िया", "वाह",
        }
    )  # fmt: skip
    GOOD_NIGHT: ClassVar[frozenset[str]] = frozenset(
        {"good night", "gn", "shubh ratri", "subh ratri", "शुभ रात्रि"}
    )
    # Any time of day (a web tester, 2026-11-02: "Ttyl" at noon got "Enjoy it together")
    GOODBYE: ClassVar[frozenset[str]] = frozenset(
        {
            "bye", "bye bye", "ttyl", "talk later", "talk to you later", "see you", "later",
            "baad mein baat karte hain", "phir baat karte hain", "phir milte hain", "chalo bye",
            "बाय", "फिर मिलते हैं", "बाद में बात करते हैं",
        }
    )  # fmt: skip

    @staticmethod
    def kind(text: str) -> SmallTalk | None:
        """ "good_night" or "goodbye" for leaving, "greeting" for a hello (a web tester's "Hii",
        2026-11-02, took 10 s through the mentor), "thanks" for an ok, thanks or emoji."""
        if not text.strip():
            return None
        words = PhraseFinder.words(text)
        if len(words) > SmallTalkRules.MAX_WORDS:
            return None
        leaving = SmallTalkRules._leaving(" ".join(words))
        if leaving is not None:
            return leaving
        if not words:
            return "thanks" if SmallTalkRules._only_emoji(text) else None
        if OnboardingAnswerParser.is_greeting(text):
            return "greeting"
        return "thanks" if set(words) <= _WORDS else None

    @staticmethod
    def repeats(reply: str, previous_reply: str | None) -> bool:
        """Marg's last reply was exactly this: say it differently (the same small-talk reply twice
        in a row sounds like a machine; a web tester, 2026-11-02)."""
        return previous_reply is not None and previous_reply.strip() == reply.strip()

    @staticmethod
    def _leaving(said: str) -> SmallTalk | None:
        """ "good night" or a goodbye, maybe after an ok."""
        if SmallTalkRules._ends_with(said, _GOOD_NIGHT):
            return "good_night"
        if SmallTalkRules._ends_with(said, _GOODBYE):
            return "goodbye"
        return None

    @staticmethod
    def _ends_with(said: str, phrases: frozenset[str]) -> bool:
        """ "good night", "acha good night", "bye": a goodbye, maybe after an ok."""
        for phrase in phrases:
            ends_with_it = said == phrase or said.endswith(f" {phrase}")
            if ends_with_it and set(said.removesuffix(phrase).split()) <= _WORDS:
                return True
        return False

    @staticmethod
    def _only_emoji(text: str) -> bool:
        """Only symbols such as emoji, no letters or digits ("🥰", "👍👍")."""
        marks = [character for character in text if not character.isspace()]
        return bool(marks) and all(
            unicodedata.category(character).startswith("S")
            or unicodedata.category(character) in {"Mn", "Cf"}
            for character in marks
        )


_WORDS: Final = frozenset(" ".join(PhraseFinder.words(word)) for word in SmallTalkRules.WORDS)
_GOOD_NIGHT: Final = frozenset(
    " ".join(PhraseFinder.words(phrase)) for phrase in SmallTalkRules.GOOD_NIGHT
)
_GOODBYE: Final = frozenset(
    " ".join(PhraseFinder.words(phrase)) for phrase in SmallTalkRules.GOODBYE
)
