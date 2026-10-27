"""Crisis replies and the helplines they give (s07 §4.6). Reviewed text, never generated.

Every helpline number is copied from an official government page, recorded with where and when
(CLAUDE.md §1: never from memory). A unit test checks each source is a .gov.in / .nic.in page.
S7 adds the child-worded versions (s10b §4.16) and the emergency number once it's copied from an
official page that states it.

Copy v1, written 2026-10-27 for the guide (parent/adult) speaker: pending the owner's review.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from app.domain.enums import FixedReplyVariant, Language


@dataclass(frozen=True, slots=True)
class Helpline:
    name: str
    number: str
    source_url: str
    retrieved_on: date
    quoted: str  # the sentence on the source page that states the number


TELE_MANAS: Final = Helpline(
    name="Tele-MANAS",
    number="14416",
    source_url="https://pib.gov.in/PressReleasePage.aspx?PRID=2022796",
    retrieved_on=date(2026, 10, 27),
    quoted=(
        "The initiative provides toll-free number, 14416, in each State and Union Territory "
        "(UT) for easy access to mental health support"
    ),
)
CHILD_HELPLINE: Final = Helpline(
    name="Child Helpline",
    number="1098",
    source_url="https://wcd.gov.in",
    retrieved_on=date(2026, 10, 27),
    quoted="Child Helpline Toll free No. - 1098.",
)

HELPLINES: Final[tuple[Helpline, ...]] = (TELE_MANAS, CHILD_HELPLINE)


def _spoken_digits(number: str) -> str:
    """Numbers are read digit by digit so they can be written down (s07 §4.6)."""
    return " ".join(number)


_SELF_HARM: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Aap jo mehsoos kar rahe hain, woh bahut bhaari ho sakta hai. Aap akele nahi hain. "
        "Abhi kisi bharose ke insaan se baat kijiye. Tele-MANAS helpline {tele_manas} par "
        "muft mein, 24 ghante baat kar sakte hain."
    ),
    Language.HINDI: (
        "आप जो महसूस कर रहे हैं, वह बहुत भारी हो सकता है। आप अकेले नहीं हैं। "
        "अभी किसी भरोसे के व्यक्ति से बात कीजिए। टेली-मानस हेल्पलाइन {tele_manas} पर "
        "मुफ़्त में, 24 घंटे बात कर सकते हैं।"
    ),
    Language.ENGLISH: (
        "What you're feeling can be very heavy, and you are not alone. Please talk to someone "
        "you trust right now. You can call the Tele-MANAS helpline on {tele_manas}, free, "
        "24 hours a day."
    ),
}

_ABUSE: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Yeh sunna mushkil hai, aur isme aapki koi galti nahi hai. Kripya abhi kisi bharose "
        "ke bade ya teacher ko batayein. Bachchon ki madad ke liye Child Helpline {child} par "
        "muft call kar sakte hain."
    ),
    Language.HINDI: (
        "यह सुनना मुश्किल है, और इसमें आपकी कोई गलती नहीं है। कृपया अभी किसी भरोसे के बड़े "
        "या टीचर को बताइए। बच्चों की मदद के लिए चाइल्ड हेल्पलाइन {child} पर मुफ़्त कॉल कर "
        "सकते हैं।"
    ),
    Language.ENGLISH: (
        "This is hard to hear, and it is not your fault. Please tell a trusted adult or a "
        "teacher now. For help for a child, call the Child Helpline on {child}, free."
    ),
}


@dataclass(frozen=True, slots=True)
class CrisisText:
    text: str
    spoken_text: str


def _render(template: str) -> CrisisText:
    return CrisisText(
        text=template.format(tele_manas=TELE_MANAS.number, child=CHILD_HELPLINE.number),
        spoken_text=template.format(
            tele_manas=_spoken_digits(TELE_MANAS.number),
            child=_spoken_digits(CHILD_HELPLINE.number),
        ),
    )


CRISIS_TEXTS: Final[dict[tuple[FixedReplyVariant, Language], CrisisText]] = {
    **{
        (FixedReplyVariant.SELF_HARM, language): _render(text)
        for language, text in _SELF_HARM.items()
    },
    **{(FixedReplyVariant.ABUSE, language): _render(text) for language, text in _ABUSE.items()},
}
CRISIS_VERSION: Final = "1"
