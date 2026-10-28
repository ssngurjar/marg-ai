"""Fixed copy for students (s12): labels the mentor's reply uses, its plan button and the
child-protection line, and the roadmap's fixed text. Hinglish, Hindi and English. Pending
the owner's review."""

from typing import Final

from app.constants.crisis_replies import CHILD_HELPLINE
from app.domain.enums import Language
from app.domain.models.reply import ReplyButton

SOURCES_LABEL: Final[dict[Language, str]] = {
    Language.HINGLISH: "Sources (official):",
    Language.HINDI: "स्रोत (आधिकारिक):",
    Language.ENGLISH: "Sources (official):",
}
MAKE_A_PLAN: Final = "rm:create"
MAKE_A_PLAN_BUTTON: Final[dict[Language, ReplyButton]] = {
    Language.HINGLISH: ReplyButton(id=MAKE_A_PLAN, title="Plan banao"),
    Language.HINDI: ReplyButton(id=MAKE_A_PLAN, title="योजना बनाओ"),
    Language.ENGLISH: ReplyButton(id=MAKE_A_PLAN, title="Make a plan"),
}
DONT_KNOW_FALLBACK: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Is baare mein abhi mere paas pakki jaankari nahi hai. Apne teacher se poochiye, aur "
        "sirf sarkari website par hi bharosa kijiye."
    ),
    Language.HINDI: (
        "इस बारे में अभी मेरे पास पक्की जानकारी नहीं है। अपने शिक्षक से पूछिए, और सिर्फ़ सरकारी "
        "वेबसाइट पर ही भरोसा कीजिए।"
    ),
    Language.ENGLISH: (
        "I don't have verified information on this yet. Please ask your teacher, and trust only "
        "official government websites."
    ),
}
"""Sent when the mentor's reply can't be made to cite only its sources (s12 §8)."""

FAMILY_PRESSURE_WORDS: Final[tuple[str, ...]] = (
    "shaadi", "shadi", "byah", "biyah", "marriage", "married", "शादी", "ब्याह", "विवाह",
)  # fmt: skip
"""A student under 18 mentioning marriage gets the child-protection line (s12 §4.3)."""
_LINE = CHILD_HELPLINE.number
CHILD_PROTECTION_LINE: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        f"Agar koi aapko padhai chhodne ya shaadi ke liye majboor kare, toh Child Helpline {_LINE} "
        "par muft call kar sakte hain."
    ),
    Language.HINDI: (
        f"अगर कोई आपको पढ़ाई छोड़ने या शादी के लिए मजबूर करे, तो चाइल्ड हेल्पलाइन {_LINE} पर मुफ़्त "
        "कॉल कर सकते हैं।"
    ),
    Language.ENGLISH: (
        "If anyone forces you to leave school or to marry, you can call the Child Helpline "
        f"{_LINE} for free."
    ),
}

NEW_PLAN_PHRASES: Final[tuple[str, ...]] = (
    "naya plan", "new plan", "dusra plan", "doosra plan", "नया प्लान", "नई योजना",
)  # fmt: skip
NEW_PLAN_BUTTON: Final[dict[Language, ReplyButton]] = {
    Language.HINGLISH: ReplyButton(id=MAKE_A_PLAN, title="Naya plan"),
    Language.HINDI: ReplyButton(id=MAKE_A_PLAN, title="नई योजना"),
    Language.ENGLISH: ReplyButton(id=MAKE_A_PLAN, title="New plan"),
}
YOUR_PLAN: Final[dict[Language, str]] = {
    Language.HINGLISH: "Aapka plan: {goal}",
    Language.HINDI: "आपकी योजना: {goal}",
    Language.ENGLISH: "Your plan: {goal}",
}
PLAN_UNVERIFIABLE: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Is lakshya ke liye abhi pakki, sarkari jaankari nahi hai, isliye abhi plan nahi banaya "
        "ja sakta. Abhi yeh kijiye: 1. Apne teacher se is raaste ke baare mein baat "
        "kijiye. 2. Is saal ki padhai achhe se poori kijiye. 3. Sirf sarkari website par hi "
        "bharosa kijiye."
    ),
    Language.HINDI: (
        "इस लक्ष्य के लिए अभी पक्की, सरकारी जानकारी नहीं है, इसलिए अभी योजना नहीं बनाई जा सकती। "
        "अभी यह कीजिए: 1. अपने शिक्षक से इस रास्ते के बारे में बात कीजिए। 2. इस साल की पढ़ाई अच्छे से "
        "पूरी कीजिए। 3. सिर्फ़ सरकारी वेबसाइट पर ही भरोसा कीजिए।"
    ),
    Language.ENGLISH: (
        "I don't have verified, official information for this goal yet, so I won't make a plan "
        "for it. For now: 1. Talk to your teacher about this path. 2. Finish this year's studies "
        "well. 3. Trust only official government websites."
    ),
}
"""Sent when retrieval finds nothing relevant: no plan is drafted or stored (golden roadmap-003)."""
