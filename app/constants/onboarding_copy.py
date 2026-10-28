"""Onboarding copy: fixed, reviewed text in Hinglish, Hindi and English (s08 §4.8).

The consent text is the legally important copy (DPDP Act 2023): it says what is kept, that no
name or number is shared, and how to delete everything. Every (key, language) pair exists (a
startup check and a unit test); button ids are the same in every language; titles are at most 20
characters. Placeholders, filled by the onboarding layer: {child} (the nickname, or "your
child"), {invite_link} (the teacher's ready-to-forward wa.me link).

COPY_VERSION is recorded on every consent event: bump it on any text change.
v onb-2026-10-27.1: written for the MVP (parent and teacher roles); pending the owner's review.
v onb-2026-10-28.1: the student role opens (S12): ASK_ROLE names students, a third role button.
v onb-2026-10-28.2: teachers get the Exposure layer (S10): PROFILE_DONE_TEACHER asks for a chapter.
"""

from dataclasses import dataclass
from typing import Final

from app.domain.enums import CopyKey, Language
from app.domain.models.reply import ReplyButton

COPY_VERSION: Final = "onb-2026-10-28.2"

_HINGLISH = Language.HINGLISH
_HINDI = Language.HINDI
_ENGLISH = Language.ENGLISH


@dataclass(frozen=True, slots=True)
class CopyEntry:
    body: str
    buttons: tuple[ReplyButton, ...]


def _buttons(*pairs: tuple[str, str]) -> tuple[ReplyButton, ...]:
    return tuple(ReplyButton(id=button_id, title=title) for button_id, title in pairs)


CONSENT_YES = "onb:consent:yes"
CONSENT_NO = "onb:consent:no"
ROLE_PARENT = "onb:role:parent"
ROLE_TEACHER = "onb:role:teacher"
ROLE_STUDENT = "onb:role:student"
GUARDIAN_YES = "onb:guardian:yes"
GUARDIAN_NO = "onb:guardian:no"
DELETE_YES = "onb:delete:yes"
DELETE_NO = "onb:delete:no"
CHILD_TALK_YES = "onb:childtalk:yes"  # + ":<learner id>"
CHILD_TALK_NO = "onb:childtalk:no"  # + ":<learner id>"
ADD_CHILD = "onb:add-child"

_CONSENT_BUTTONS: Final = {
    _HINGLISH: _buttons((CONSENT_YES, "Haan, theek hai"), (CONSENT_NO, "Nahi")),
    _HINDI: _buttons((CONSENT_YES, "हाँ, ठीक है"), (CONSENT_NO, "नहीं")),
    _ENGLISH: _buttons((CONSENT_YES, "Yes, I agree"), (CONSENT_NO, "No")),
}
_ROLE_BUTTONS: Final = {
    _HINGLISH: _buttons(
        (ROLE_PARENT, "Main parent hoon"),
        (ROLE_STUDENT, "Main student hoon"),
        (ROLE_TEACHER, "Main teacher hoon"),
    ),
    _HINDI: _buttons(
        (ROLE_PARENT, "मैं माता-पिता हूँ"),
        (ROLE_STUDENT, "मैं विद्यार्थी हूँ"),
        (ROLE_TEACHER, "मैं शिक्षक हूँ"),
    ),
    _ENGLISH: _buttons(
        (ROLE_PARENT, "I'm a parent"),
        (ROLE_STUDENT, "I'm a student"),
        (ROLE_TEACHER, "I'm a teacher"),
    ),
}
_GUARDIAN_BUTTONS: Final = {
    _HINGLISH: _buttons((GUARDIAN_YES, "Haan, unhe pata hai"), (GUARDIAN_NO, "Abhi nahi")),
    _HINDI: _buttons((GUARDIAN_YES, "हाँ, उन्हें पता है"), (GUARDIAN_NO, "अभी नहीं")),
    _ENGLISH: _buttons((GUARDIAN_YES, "Yes, they know"), (GUARDIAN_NO, "Not yet")),
}
_DELETE_BUTTONS: Final = {
    _HINGLISH: _buttons((DELETE_YES, "Haan, delete karo"), (DELETE_NO, "Nahi, rehne do")),
    _HINDI: _buttons((DELETE_YES, "हाँ, डिलीट करो"), (DELETE_NO, "नहीं, रहने दो")),
    _ENGLISH: _buttons((DELETE_YES, "Yes, delete"), (DELETE_NO, "No, keep it")),
}
_CHILD_TALK_BUTTONS: Final = {
    _HINGLISH: _buttons((CHILD_TALK_YES, "Haan, baat kare"), (CHILD_TALK_NO, "Abhi nahi")),
    _HINDI: _buttons((CHILD_TALK_YES, "हाँ, बात करे"), (CHILD_TALK_NO, "अभी नहीं")),
    _ENGLISH: _buttons((CHILD_TALK_YES, "Yes, they can"), (CHILD_TALK_NO, "Not now")),
}
NO_BUTTONS: Final[dict[Language, tuple[ReplyButton, ...]]] = dict.fromkeys(Language, ())

CHILD_FALLBACK: Final = {
    _HINGLISH: "aapka bachcha",
    _HINDI: "आपका बच्चा",
    _ENGLISH: "your child",
}

_INTRO: Final = {
    _HINGLISH: (
        "Namaste! Main Marg hoon — padhai, career aur bachchon ki seekh mein aapka saathi. Aap "
        "bolkar ya likhkar kuch bhi pooch sakte hain. Aapki madad ke liye hum sirf zaroori "
        "jaankari save karenge (jaise class, zila, ya bachche ki umar). Naam ya number kisi ko "
        "nahi diya jayega. Kabhi bhi 'mera data hatao' bolkar sab delete kar sakte hain. Kya aap "
        "sahmat hain? (English ya हिंदी mein baat karni ho toh bas wahi likhiye.)"
    ),
    _HINDI: (
        "नमस्ते! मैं मार्ग हूँ — पढ़ाई, करियर और बच्चों की सीख में आपका साथी। आप बोलकर या लिखकर "
        "कुछ भी पूछ सकते हैं। आपकी मदद के लिए हम सिर्फ़ ज़रूरी जानकारी सेव करेंगे (जैसे कक्षा, "
        "ज़िला, या बच्चे की उम्र)। नाम या नंबर किसी को नहीं दिया जाएगा। कभी भी 'मेरा डेटा हटाओ' "
        "बोलकर सब डिलीट कर सकते हैं। क्या आप सहमत हैं? (Hinglish या English में बात करनी हो तो "
        "बस वही लिखिए।)"
    ),
    _ENGLISH: (
        "Hi! I'm Marg — your guide for studies, careers and children's learning. You can ask "
        "anything by voice or text. To help you, we only save what's needed (like class, "
        "district, or a child's age). Your name and number are never shared. Say 'delete my "
        "data' any time to erase everything. Do you agree? (To talk in Hindi or Hinglish, just "
        "type it.)"
    ),
}
_QUESTION_REMEMBERED: Final = {
    _HINGLISH: "Aapka sawaal yaad hai — bas 2-3 chhote sawaalon ke baad jawab doonga.",
    _HINDI: "आपका सवाल याद है — बस 2-3 छोटे सवालों के बाद जवाब दूँगा।",
    _ENGLISH: "I've noted your question — I'll answer after 2-3 quick questions.",
}

_TEXTS: Final[dict[CopyKey, dict[Language, str]]] = {
    CopyKey.INTRO_CONSENT: _INTRO,
    CopyKey.INTRO_CONSENT_WITH_QUESTION: {
        language: f"{_QUESTION_REMEMBERED[language]}\n\n{_INTRO[language]}" for language in _INTRO
    },
    CopyKey.CONSENT_DECLINED: {
        _HINGLISH: (
            "Koi baat nahi. Humne aapka kuch bhi save nahi kiya. Jab mann ho, dobara 'Hi' bhejiye."
        ),
        _HINDI: "कोई बात नहीं। हमने आपका कुछ भी सेव नहीं किया। जब मन हो, दोबारा 'Hi' भेजिए।",
        _ENGLISH: "No problem. We haven't saved anything about you. Send 'Hi' whenever you like.",
    },
    CopyKey.ASK_ROLE: {
        _HINGLISH: "Aap kisi chhote bachche ke mummy-papa hain, student hain, ya teacher?",
        _HINDI: "आप किसी छोटे बच्चे के माता-पिता हैं, विद्यार्थी हैं, या शिक्षक?",
        _ENGLISH: "Are you a parent of a young child, a student, or a teacher?",
    },
    CopyKey.STUDENT_COMING_SOON: {
        _HINGLISH: (
            "Abhi Marg chhote bachchon ke mummy-papa aur teachers ke saath shuru ho raha hai. "
            "Students ke liye jald aayega! Tab tak ghar ya school mein kisi bade ko Marg ke baare "
            "mein bataiye."
        ),
        _HINDI: (
            "अभी मार्ग छोटे बच्चों के माता-पिता और शिक्षकों के साथ शुरू हो रहा है। विद्यार्थियों के "
            "लिए जल्द आएगा! तब तक घर या स्कूल में किसी बड़े को मार्ग के बारे में बताइए।"
        ),
        _ENGLISH: (
            "Marg is starting with parents of young children and with teachers. It's coming for "
            "students soon! Until then, tell a parent or teacher about Marg."
        ),
    },
    CopyKey.ASK_GUARDIAN: {
        _HINGLISH: (
            "Kya aapke mummy-papa ya teacher ko pata hai, aur woh raazi hain ki aap Marg se baat "
            "karein?"
        ),
        _HINDI: "क्या आपके माता-पिता या शिक्षक को पता है, और वे राज़ी हैं कि आप मार्ग से बात करें?",
        _ENGLISH: "Do your parents or a teacher know, and agree, that you're talking to Marg?",
    },
    CopyKey.GUARDIAN_NEEDED: {
        _HINGLISH: "Theek hai. Pehle ghar par ya teacher se pooch lijiye, phir 'Haan' dabaiye.",
        _HINDI: "ठीक है। पहले घर पर या शिक्षक से पूछ लीजिए, फिर 'हाँ' दबाइए।",
        _ENGLISH: "Okay. Please ask at home or a teacher first, then tap 'Yes'.",
    },
    CopyKey.ASK_GRADE_STUDENT: {
        _HINGLISH: "Aap kaunsi class mein padhte hain? (1 se 12)",
        _HINDI: "आप कौन-सी कक्षा में पढ़ते हैं? (1 से 12)",
        _ENGLISH: "Which class are you in? (1 to 12)",
    },
    CopyKey.ASK_SUBJECT_TEACHER: {
        _HINGLISH: "Aap kaunsa subject padhate hain?",
        _HINDI: "आप कौन-सा विषय पढ़ाते हैं?",
        _ENGLISH: "Which subject do you teach?",
    },
    CopyKey.ASK_GRADE_TEACHER: {
        _HINGLISH: "Zyadatar kaunsi class ko padhate hain? (1 se 12)",
        _HINDI: "ज़्यादातर कौन-सी कक्षा को पढ़ाते हैं? (1 से 12)",
        _ENGLISH: "Which class do you mostly teach? (1 to 12)",
    },
    CopyKey.ASK_DISTRICT: {
        _HINGLISH: "Aap kaunse zile se hain?",
        _HINDI: "आप किस ज़िले से हैं?",
        _ENGLISH: "Which district are you from?",
    },
    CopyKey.INVALID_GRADE: {
        _HINGLISH: "Class 1 se 12 ke beech batayiye.",
        _HINDI: "कक्षा 1 से 12 के बीच बताइए।",
        _ENGLISH: "Please give a class between 1 and 12.",
    },
    CopyKey.ASK_CHILD: {
        _HINGLISH: (
            "Aapke bachche ki umar kitni hai? Chahein toh ghar ka chhota naam bhi bataiye, jaise "
            "'Munni, 5 saal'. Poora naam mat likhiye."
        ),
        _HINDI: (
            "आपके बच्चे की उम्र कितनी है? चाहें तो घर का छोटा नाम भी बताइए, जैसे 'मुन्नी, 5 साल'। "
            "पूरा नाम मत लिखिए।"
        ),
        _ENGLISH: (
            "How old is your child? You can add a short home name too, like 'Munni, 5 years'. "
            "Please don't write their full name."
        ),
    },
    CopyKey.CHILD_INVALID_AGE: {
        _HINGLISH: "Umar 2 se 19 saal ke beech batayiye, jaise '5 saal'.",
        _HINDI: "उम्र 2 से 19 साल के बीच बताइए, जैसे '5 साल'।",
        _ENGLISH: "Please give an age between 2 and 19, like '5 years'.",
    },
    CopyKey.CHILD_NICKNAME_TOO_LONG: {
        _HINGLISH: (
            "Bas ghar ka chhota naam kaafi hai (jaise 'Munni'), ya naam chhod dijiye. Umar zaroor "
            "bataiye."
        ),
        _HINDI: "बस घर का छोटा नाम काफ़ी है (जैसे 'मुन्नी'), या नाम छोड़ दीजिए। उम्र ज़रूर बताइए।",
        _ENGLISH: (
            "Just a short home name is enough (like 'Munni'), or leave it out. Please do give the "
            "age."
        ),
    },
    CopyKey.MAX_CHILDREN: {
        _HINGLISH: "Abhi hum teen bachchon tak hi saath chal sakte hain.",
        _HINDI: "अभी हम तीन बच्चों तक ही साथ चल सकते हैं।",
        _ENGLISH: "For now, Marg can follow up to three children.",
    },
    CopyKey.QUESTION_NOTED: {
        _HINGLISH: "Aapka sawaal yaad hai, profile poori hote hi jawab doonga.",
        _HINDI: "आपका सवाल याद है, प्रोफ़ाइल पूरी होते ही जवाब दूँगा।",
        _ENGLISH: "I've noted your question and will answer once your profile is complete.",
    },
    CopyKey.NOT_UNDERSTOOD: {
        _HINGLISH: "Maaf kijiye, samajh nahi aaya.",
        _HINDI: "माफ़ कीजिए, समझ नहीं आया।",
        _ENGLISH: "Sorry, I didn't understand that.",
    },
    CopyKey.PROFILE_DONE: {
        _HINGLISH: "Shukriya! Ab aap kuch bhi pooch sakte hain — career, padhai, ya koi sapna.",
        _HINDI: "शुक्रिया! अब आप कुछ भी पूछ सकते हैं — करियर, पढ़ाई, या कोई सपना।",
        _ENGLISH: "Thank you! Ask me anything now — careers, studies, or a dream.",
    },
    CopyKey.PROFILE_DONE_TEACHER: {
        _HINGLISH: (
            "Shukriya! Ab agla chapter batayiye (jaise 'Kal class 8 mein Force and Pressure hai'): "
            "aapko us chapter se jude teen asli kshetra aur 5 minute ki class activity milegi. "
            "Chhote bachchon ke parents ke liye yeh link bhi apni class ke group mein bhejiye: "
            "{invite_link}"
        ),
        _HINDI: (
            "शुक्रिया! अब अगला अध्याय बताइए (जैसे 'कल कक्षा 8 में बल और दाब है'): आपको उस अध्याय से "
            "जुड़े तीन असली क्षेत्र और 5 मिनट की कक्षा गतिविधि मिलेगी। छोटे बच्चों के माता-पिता के लिए "
            "यह लिंक भी अपनी कक्षा के ग्रुप में भेजिए: {invite_link}"
        ),
        _ENGLISH: (
            "Thank you! Now tell me your next chapter (like 'Class 8 Force and Pressure "
            "tomorrow'): you'll get three real-world fields it leads to and a 5-minute class "
            "activity. Please "
            "also share this link with the parents of young children in your class: {invite_link}"
        ),
    },
    CopyKey.TEACHER_WAITING: {
        _HINGLISH: (
            "Marg abhi parents ke saath shuru ho raha hai; teachers ke liye jald aayega. Tab tak "
            "yeh link apni class ke parents ko bhejiye: {invite_link}"
        ),
        _HINDI: (
            "मार्ग अभी माता-पिता के साथ शुरू हो रहा है; शिक्षकों के लिए जल्द आएगा। तब तक यह लिंक "
            "अपनी कक्षा के माता-पिता को भेजिए: {invite_link}"
        ),
        _ENGLISH: (
            "Marg is starting with parents; it's coming for teachers soon. Until then, please "
            "share this link with your class's parents: {invite_link}"
        ),
    },
    CopyKey.PROFILE_DONE_PARENT: {
        _HINGLISH: (
            "Shukriya! Ab roz ek chhoti khoj — bachche ke saath 2 minute. Pehli khoj abhi bhej "
            "raha hoon."
        ),
        _HINDI: "शुक्रिया! अब रोज़ एक छोटी खोज — बच्चे के साथ 2 मिनट। पहली खोज अभी भेज रहा हूँ।",
        _ENGLISH: (
            "Thank you! Now a small discovery every day — 2 minutes with your child. Sending the "
            "first one now."
        ),
    },
    CopyKey.ASK_CHILD_TALK: {
        _HINGLISH: (
            "Ek sawaal: kya {child} khud bhi Marg se baat kar sakte hain? Sirf awaaz se, 10 "
            "minute tak, aur har baar aapko chhota sa saar milega."
        ),
        _HINDI: (
            "एक सवाल: क्या {child} खुद भी मार्ग से बात कर सकते हैं? सिर्फ़ आवाज़ से, 10 मिनट तक, "
            "और हर बार आपको छोटा-सा सार मिलेगा।"
        ),
        _ENGLISH: (
            "One question: may {child} talk to Marg directly too? Voice only, up to 10 minutes, "
            "and you get a short summary every time."
        ),
    },
    CopyKey.CHILD_TALK_ENABLED: {
        _HINGLISH: (
            "Theek hai! Jab {child} baat karna chahein, 'Main bachcha hoon' dabayein ya bolein. "
            "Har baat ke baad aapko saar milega."
        ),
        _HINDI: (
            "ठीक है! जब {child} बात करना चाहें, 'मैं बच्चा हूँ' दबाएँ या बोलें। हर बात के बाद आपको "
            "सार मिलेगा।"
        ),
        _ENGLISH: (
            "Done! When {child} wants to talk, they can tap or say 'I'm the child'. You'll get a "
            "summary after every talk."
        ),
    },
    CopyKey.CHILD_TALK_OFF: {
        _HINGLISH: "Theek hai, bachche se seedhi baat band hai. Kabhi bhi chalu kar sakte hain.",
        _HINDI: "ठीक है, बच्चे से सीधी बात बंद है। कभी भी चालू कर सकते हैं।",
        _ENGLISH: "Okay, direct talk with your child is off. You can turn it on any time.",
    },
    CopyKey.LANGUAGE_CHANGED: {
        _HINGLISH: "Theek hai, ab main Hinglish mein baat karunga.",
        _HINDI: "ठीक है, अब मैं हिंदी में बात करूँगा।",
        _ENGLISH: "Okay, I'll talk in English from now on.",
    },
    CopyKey.CONFIRM_DELETE: {
        _HINGLISH: (
            "Kya aap sach mein apna saara data delete karna chahte hain? Aapki profile, bachchon "
            "ki jaankari aur baatein hamesha ke liye mit jayengi."
        ),
        _HINDI: (
            "क्या आप सच में अपना सारा डेटा डिलीट करना चाहते हैं? आपकी प्रोफ़ाइल, बच्चों की जानकारी "
            "और बातें हमेशा के लिए मिट जाएँगी।"
        ),
        _ENGLISH: (
            "Do you really want to delete all your data? Your profile, your children's details "
            "and your conversations will be erased for good."
        ),
    },
    CopyKey.DELETE_CANCELLED: {
        _HINGLISH: "Theek hai, kuch delete nahi kiya.",
        _HINDI: "ठीक है, कुछ डिलीट नहीं किया।",
        _ENGLISH: "Okay, nothing was deleted.",
    },
    CopyKey.DATA_DELETED: {
        _HINGLISH: (
            "Aapka saara data delete ho gaya. Dobara baat karni ho toh kabhi bhi 'Hi' bhejiye."
        ),
        _HINDI: "आपका सारा डेटा डिलीट हो गया। दोबारा बात करनी हो तो कभी भी 'Hi' भेजिए।",
        _ENGLISH: "All your data has been deleted. Send 'Hi' any time to start again.",
    },
}  # fmt: skip

_BUTTONS_FOR: Final[dict[CopyKey, dict[Language, tuple[ReplyButton, ...]]]] = {
    CopyKey.INTRO_CONSENT: _CONSENT_BUTTONS,
    CopyKey.INTRO_CONSENT_WITH_QUESTION: _CONSENT_BUTTONS,
    CopyKey.ASK_ROLE: _ROLE_BUTTONS,
    CopyKey.ASK_GUARDIAN: _GUARDIAN_BUTTONS,
    CopyKey.GUARDIAN_NEEDED: _GUARDIAN_BUTTONS,
    CopyKey.CONFIRM_DELETE: _DELETE_BUTTONS,
    CopyKey.ASK_CHILD_TALK: _CHILD_TALK_BUTTONS,
}

COPY: Final[dict[tuple[CopyKey, Language], CopyEntry]] = {
    (key, language): CopyEntry(body=text, buttons=_BUTTONS_FOR.get(key, NO_BUTTONS)[language])
    for key, texts in _TEXTS.items()
    for language, text in texts.items()
}
