"""Fixed copy for teachers (s10): the exposure bridge's labels and buttons, and the ask-for-chapter
text. Hinglish, Hindi and English. Pending the owner's review."""

from typing import Final

from app.domain.enums import Language
from app.domain.models.reply import ReplyButton

MORE_ACTIVITY: Final = "exp:more"
NEW_CHAPTER: Final = "exp:new"
EXPOSURE_BUTTONS: Final[dict[Language, tuple[ReplyButton, ReplyButton]]] = {
    Language.HINGLISH: (
        ReplyButton(id=MORE_ACTIVITY, title="Aur activity"),
        ReplyButton(id=NEW_CHAPTER, title="Naya chapter"),
    ),
    Language.HINDI: (
        ReplyButton(id=MORE_ACTIVITY, title="और गतिविधि"),
        ReplyButton(id=NEW_CHAPTER, title="नया अध्याय"),
    ),
    Language.ENGLISH: (
        ReplyButton(id=MORE_ACTIVITY, title="Another activity"),
        ReplyButton(id=NEW_CHAPTER, title="New chapter"),
    ),
}
ASK_CHAPTER: Final[dict[Language, str]] = {
    Language.HINGLISH: "Agla kaunsa chapter padha rahe hain? Class aur chapter ka naam batayiye.",
    Language.HINDI: "अगला कौन-सा अध्याय पढ़ा रहे हैं? कक्षा और अध्याय का नाम बताइए।",
    Language.ENGLISH: "Which chapter are you teaching next? Tell me the class and chapter name.",
}
LABELS: Final[dict[Language, dict[str, str]]] = {
    Language.HINGLISH: {
        "topic": "Chapter", "fields": "Yeh chapter in teen kshetron se judta hai",
        "why": "Kyun", "example": "Bharat se udaharan", "activity": "Activity (5 minute)",
        "materials": "Saamaan", "careers": "Kaam", "local": "Gaon se jod",
        "another": "Ek aur activity",
    },
    Language.HINDI: {
        "topic": "अध्याय", "fields": "यह अध्याय इन तीन क्षेत्रों से जुड़ता है",
        "why": "क्यों", "example": "भारत से उदाहरण", "activity": "गतिविधि (5 मिनट)",
        "materials": "सामान", "careers": "काम", "local": "गाँव से जुड़ाव",
        "another": "एक और गतिविधि",
    },
    Language.ENGLISH: {
        "topic": "Topic", "fields": "Three fields this chapter leads to",
        "why": "Why", "example": "Example from India", "activity": "Activity (5 minutes)",
        "materials": "Materials", "careers": "Careers", "local": "Local link",
        "another": "Another activity",
    },
}  # fmt: skip
DEVICE_OR_PURCHASE_WORDS: Final[tuple[str, ...]] = (
    "projector", "laptop", "computer", "smartphone", "tablet", "internet", "wifi", "youtube",
    "printout", "buy", "purchase", "kharid", "kharidna", "kharidein", "ख़रीद", "खरीद",
)  # fmt: skip
"""s10 §4.4: a classroom activity needs no device and nothing bought."""
MONEY_WORDS: Final[tuple[str, ...]] = ("lakh", "crore", "salary", "per month", "lakh rupaye")
"""s10 §4.4: careers are named, never priced."""

DASHBOARD_LINK: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Aapke zile ke students ka dashboard (15 minute ke liye khulega): {url}\nIsme sirf ginti "
        "hoti hai, kisi bachche ka naam ya message nahi."
    ),
    Language.HINDI: (
        "आपके ज़िले के विद्यार्थियों का डैशबोर्ड (15 मिनट के लिए खुलेगा): {url}\nइसमें सिर्फ़ गिनती "
        "होती है, किसी बच्चे का नाम या संदेश नहीं।"
    ),
    Language.ENGLISH: (
        "Your district's student dashboard (opens for 15 minutes): {url}\nIt shows counts only, "
        "never a child's name or message."
    ),
}
DASHBOARD_NO_DISTRICT: Final[dict[Language, str]] = {
    Language.HINGLISH: "Dashboard ke liye pehle apna zila batayiye.",
    Language.HINDI: "डैशबोर्ड के लिए पहले अपना ज़िला बताइए।",
    Language.ENGLISH: "Please tell me your district first, to see its dashboard.",
}
