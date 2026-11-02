"""Replies to small talk that every persona gets alike (owner, 2026-11-02: what is true for one
persona's "ok" or good night is true for all). Hinglish, Hindi and English. Pending the owner's
review."""

from typing import Final

from app.domain.enums import Language

GOOD_NIGHT: Final[dict[Language, str]] = {
    Language.HINGLISH: "Shubh ratri! Kal phir baat karte hain.",
    Language.HINDI: "शुभ रात्रि! कल फिर बात करते हैं।",
    Language.ENGLISH: "Good night! Talk again tomorrow.",
}
# "bye", "ttyl", "phir milte hain": any time of day, so not "good night" (2026-11-02)
GOODBYE: Final[dict[Language, str]] = {
    Language.HINGLISH: "Theek hai, phir baat karte hain! Jab chahein, likhiye.",
    Language.HINDI: "ठीक है, फिर बात करते हैं! जब चाहें, लिखिए।",
    Language.ENGLISH: "Okay, talk soon! Write whenever you like.",
}

# The same small-talk reply twice in a row sounds like a machine: the second time, this (a web
# tester's "later" got the same "Bahut badhiya!" as their "thanks", 2026-11-02)
ACKNOWLEDGED_AGAIN: Final[dict[Language, str]] = {
    Language.HINGLISH: "Theek hai! Jab man kare, bataiye.",
    Language.HINDI: "ठीक है! जब मन करे, बताइए।",
    Language.ENGLISH: "Okay! Tell me whenever you like.",
}

# Someone set up as one kind of user who wants to use Marg as another (owner, 2026-11-02: explain,
# and point to deleting and starting again; the role is never changed from words)
OTHER_ROLE_REPLY: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Is number par Marg abhi ek hi tarah se aapse baat karta hai. Parent, student ya teacher"
        " ki tarah alag se use karna ho, to 'mera data hatao' likhiye, phir 'Hi' bhejkar naye"
        " sire se shuru kijiye. Ya kisi doosre phone se likhiye."
    ),
    Language.HINDI: (
        "इस नंबर पर मार्ग अभी एक ही तरह से आपसे बात करता है। माता-पिता, विद्यार्थी या शिक्षक की"
        " तरह अलग से इस्तेमाल करना हो, तो 'मेरा डेटा हटाओ' लिखिए, फिर 'Hi' भेजकर नए सिरे से"
        " शुरू कीजिए। या किसी दूसरे फ़ोन से लिखिए।"
    ),
    Language.ENGLISH: (
        "On this number, Marg talks with you one way for now. To use it as a parent, a student"
        " or a teacher instead, send 'delete my data', then 'Hi' to start again. Or write from"
        " another phone."
    ),
}

FAREWELLS: Final[dict[str, dict[Language, str]]] = {"good_night": GOOD_NIGHT, "goodbye": GOODBYE}
"""The reply for each kind of leaving that `SmallTalkRules.kind` names."""
