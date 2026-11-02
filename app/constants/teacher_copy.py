"""Fixed copy for teachers (s10): the exposure bridge's labels and buttons, and the ask-for-chapter
text. Hinglish, Hindi and English. Pending the owner's review."""

from typing import Final

from app.constants.crisis_replies import CHILD_HELPLINE
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
        "another": "Ek aur activity", "class": "class",
    },
    Language.HINDI: {
        "topic": "अध्याय", "fields": "यह अध्याय इन तीन क्षेत्रों से जुड़ता है",
        "why": "क्यों", "example": "भारत से उदाहरण", "activity": "गतिविधि (5 मिनट)",
        "materials": "सामान", "careers": "काम", "local": "गाँव से जुड़ाव",
        "another": "एक और गतिविधि", "class": "कक्षा",
    },
    Language.ENGLISH: {
        "topic": "Topic", "fields": "Three fields this chapter leads to",
        "why": "Why", "example": "Example from India", "activity": "Activity (5 minutes)",
        "materials": "Materials", "careers": "Careers", "local": "Local link",
        "another": "Another activity", "class": "class",
    },
}  # fmt: skip
# A teaching answer's sections (owner, 2026-11-01: teachers asked how to start a chapter)
TEACHING_LABELS: Final[dict[Language, dict[str, str]]] = {
    Language.HINGLISH: {
        "start": "Class aise shuru kijiye", "steps": "Teen aasaan kadam mein samjhaiye",
        "check": "Samjha ya nahi, poochhiye", "mistake": "Aam galti",
    },
    Language.HINDI: {
        "start": "कक्षा ऐसे शुरू कीजिए", "steps": "तीन आसान कदमों में समझाइए",
        "check": "समझा या नहीं, पूछिए", "mistake": "आम ग़लती",
    },
    Language.ENGLISH: {
        "start": "Start the class like this", "steps": "Explain it in three simple steps",
        "check": "Check they understood", "mistake": "A common mistake",
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
# A district kept as typed, not on LGD's list (critic review D4, owner 2026-11-01): it has no
# district dashboard, since its numbers would mean a group the official list doesn't know.
DASHBOARD_DISTRICT_UNVERIFIED: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Aapka zila ({district}) sarkari soochi mein nahi mila, isliye uska dashboard abhi nahi"
        " ban sakta."
    ),
    Language.HINDI: (
        "आपका ज़िला ({district}) सरकारी सूची में नहीं मिला, इसलिए उसका डैशबोर्ड अभी नहीं बन सकता।"
    ),
    Language.ENGLISH: (
        "Your district ({district}) isn't on the official list, so it has no dashboard yet."
    ),
}
# A teacher worried about a child (critic review D2, owner 2026-11-01): what to do now, in fixed
# words; the helpline number is the sourced one in crisis_replies. Pending the owner's review.
TEACHER_CONCERN: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Aapne dhyan diya, yeh bahut zaroori hai. Bachche se akele mein, aaraam se baat kijiye,"
        " bina daante, aur yeh wada mat kijiye ki baat kisi ko nahi batayenge. Aaj hi apne head"
        " teacher ko batayiye. Bachche ki suraksha khatre mein lage toh Child Helpline"
        f" {CHILD_HELPLINE.number} par muft call kijiye."
    ),
    Language.HINDI: (
        "आपने ध्यान दिया, यह बहुत ज़रूरी है। बच्चे से अकेले में, आराम से बात कीजिए, बिना डाँटे, और"
        " यह वादा मत कीजिए कि बात किसी को नहीं बताएँगे। आज ही अपने प्रधानाध्यापक को बताइए। बच्चे की"
        f" सुरक्षा ख़तरे में लगे तो चाइल्ड हेल्पलाइन {CHILD_HELPLINE.number} पर मुफ़्त कॉल कीजिए।"
    ),
    Language.ENGLISH: (
        "Thank you for noticing; this matters. Talk to the child gently and alone, without blame,"
        " and don't promise to keep it secret. Tell your head teacher today. If the child may be"
        f" unsafe, call the Child Helpline on {CHILD_HELPLINE.number}, free."
    ),
}
# Not about teaching (critic review D2): an honest "this is what I do", and the way back in.
# Owner, 2026-11-02: say Marg is just beginning and growing, not a flat "I can't help".
TEACHER_OUT_OF_SCOPE: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Marg abhi shuruaat mein hai, isliye yeh abhi nahi kar paata; hum ise lagataar behtar bana"
        " rahe hain aur nayi cheezein jod rahe hain. Abhi Marg padhane mein madad karta hai: kisi"
        " chapter ko asli kaam aur careers se jodna ho, ya use class mein kaise padhayein, yeh"
        " poochhiye. Kaunsa chapter?"
    ),
    Language.HINDI: (
        "मार्ग अभी शुरुआत में है, इसलिए यह अभी नहीं कर पाता; हम इसे लगातार बेहतर बना रहे हैं और नई"
        " चीज़ें जोड़ रहे हैं। अभी मार्ग पढ़ाने में मदद करता है: किसी अध्याय को असली काम और करियर से"
        " जोड़ना हो, या उसे कक्षा में कैसे पढ़ाएँ, यह पूछिए। कौन-सा अध्याय?"
    ),
    Language.ENGLISH: (
        "Marg is just getting started, so it can't do this yet; we're improving it all the time and"
        " adding more. For now Marg helps with teaching: ask me to connect a chapter to real work"
        " and careers, or how to teach it in class. Which chapter?"
    ),
}
# A teacher's hello: answered at once (one behaviour, every persona: 2026-11-02)
TEACHER_HELLO: Final[dict[Language, str]] = {
    Language.HINGLISH: (
        "Namaste! Kal ka chapter batayiye: use asli kaam aur ek chhoti gatividhi se jodenge."
    ),
    Language.HINDI: "नमस्ते! कल का अध्याय बताइए: उसे असली काम और एक छोटी गतिविधि से जोड़ेंगे।",
    Language.ENGLISH: (
        "Hello! Tell me tomorrow's chapter, and we'll link it to real work and a short activity."
    ),
}
# A teacher's "ok", thanks or emoji: answered at once (owner's field test, 2026-11-02: "Ok" got the
# out-of-scope reply)
TEACHER_ACKNOWLEDGED: Final[dict[Language, str]] = {
    Language.HINGLISH: "Theek hai! Jab chahein, agla chapter batayiye.",
    Language.HINDI: "ठीक है! जब चाहें, अगला अध्याय बताइए।",
    Language.ENGLISH: "Okay! Tell me your next chapter whenever you like.",
}
