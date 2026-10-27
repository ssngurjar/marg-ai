"""Fixed journey text (s10b §4.7, §4.10): the supervision line, body labels, buttons, and the
replies that need no model. Three languages; reviewed copy.

v1, written 2026-10-27: pending the owner's review.
"""

from typing import Final

from app.domain.enums import Language
from app.domain.models.reply import ReplyButton

_HINGLISH = Language.HINGLISH
_HINDI = Language.HINDI
_ENGLISH = Language.ENGLISH

KHOJ_TODAY = "jrn:today"  # + ":<learner id>" when it names a child
KHOJ_DONE = "jrn:done"
KHOJ_OTHER = "jrn:other"

SUPERVISION_LINE: Final[dict[Language, str]] = {
    _HINGLISH: "Yeh khoj bachche ke saath, aapki nazar mein hi karein.",
    _HINDI: "यह खोज बच्चे के साथ, आपकी नज़र में ही करें।",
    _ENGLISH: "Do this with your child, always where you can see them.",
}
ASK_LABEL: Final[dict[Language, str]] = {
    _HINGLISH: "Poochiye:",
    _HINDI: "पूछिए:",
    _ENGLISH: "Ask:",
}
LISTEN_LABEL: Final[dict[Language, str]] = {
    _HINGLISH: "Dhyan dijiye:",
    _HINDI: "ध्यान दीजिए:",
    _ENGLISH: "Listen for:",
}
KHOJ_BUTTONS: Final[dict[Language, tuple[ReplyButton, ...]]] = {
    _HINGLISH: (
        ReplyButton(id=KHOJ_DONE, title="Ho gaya ✓"),
        ReplyButton(id=KHOJ_OTHER, title="Doosri khoj"),
    ),
    _HINDI: (
        ReplyButton(id=KHOJ_DONE, title="हो गया ✓"),
        ReplyButton(id=KHOJ_OTHER, title="दूसरी खोज"),
    ),
    _ENGLISH: (
        ReplyButton(id=KHOJ_DONE, title="Done ✓"),
        ReplyButton(id=KHOJ_OTHER, title="Another one"),
    ),
}
ADD_CHILD_BUTTON: Final[dict[Language, ReplyButton]] = {
    _HINGLISH: ReplyButton(id="onb:add-child", title="Doosra bachcha"),
    _HINDI: ReplyButton(id="onb:add-child", title="दूसरा बच्चा"),
    _ENGLISH: ReplyButton(id="onb:add-child", title="Another child"),
}
WHICH_CHILD: Final[dict[Language, str]] = {
    _HINGLISH: "Aaj ki khoj kis bachche ke liye bhejun?",
    _HINDI: "आज की खोज किस बच्चे के लिए भेजूँ?",
    _ENGLISH: "Which child is today's discovery for?",
}
UNNAMED_CHILD: Final[dict[Language, str]] = {
    _HINGLISH: "{age} saal ka bachcha",
    _HINDI: "{age} साल का बच्चा",
    _ENGLISH: "Child, {age} years",
}
AGE_COMING_SOON: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Abhi roz ki khoj 3 se 8 saal ke bachchon ke liye hai; is umar ke liye jald aayegi. "
        "Tab tak ek baat: bachche se din mein ek baar poochiye 'aaj tumne kya naya dekha?', aur "
        "poore dhyan se suniye."
    ),
    _HINDI: (
        "अभी रोज़ की खोज 3 से 8 साल के बच्चों के लिए है; इस उम्र के लिए जल्द आएगी। तब तक एक बात: "
        "बच्चे से दिन में एक बार पूछिए 'आज तुमने क्या नया देखा?', और पूरे ध्यान से सुनिए।"
    ),
    _ENGLISH: (
        "The daily discovery is for children aged 3 to 8 for now; it's coming for this age "
        "soon. Until then, once a day ask your child 'what did you notice today?' and listen "
        "closely."
    ),
}
REFLECTION_FALLBACK: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Bahut accha! Bachche ki baat sunna hi sabse badi seekh hai. Ek aur sawaal poochiye:"
    ),
    _HINDI: "बहुत अच्छा! बच्चे की बात सुनना ही सबसे बड़ी सीख है। एक और सवाल पूछिए:",
    _ENGLISH: "Lovely! Listening to your child is the biggest lesson. Try one more question:",
}
NO_ACTIVITY_LEFT: Final[dict[Language, str]] = {
    _HINGLISH: "Aaj ke liye nayi khoj nahi hai. Kal ek nayi khoj bhejunga!",
    _HINDI: "आज के लिए नई खोज नहीं है। कल एक नई खोज भेजूँगा!",
    _ENGLISH: "There's no new discovery left for today. I'll send a new one tomorrow!",
}

# The curiosity moment (s10b §4.15, C11): labels for its parts, and the honest answer used when
# the model isn't confident of a true, simple one.
FIND_OUT_LABEL: Final[dict[Language, str]] = {
    _HINGLISH: "Saath mein pata lagaiye (2 minute):",
    _HINDI: "साथ में पता लगाइए (2 मिनट):",
    _ENGLISH: "Find out together (2 minutes):",
}
ASK_BACK_LABEL: Final[dict[Language, str]] = {
    _HINGLISH: "Phir bachche se poochiye:",
    _HINDI: "फिर बच्चे से पूछिए:",
    _ENGLISH: "Then ask your child:",
}
LETS_FIND_OUT: Final[dict[Language, str]] = {
    _HINGLISH: "Bahut accha sawaal hai! Chaliye, saath mein pata lagaate hain.",
    _HINDI: "बहुत अच्छा सवाल है! चलिए, साथ में पता लगाते हैं।",
    _ENGLISH: "What a good question! Let's find out together.",
}
# Sent when the curiosity answer fails its checks twice (e.g. a question about snakes, which the
# d7 rule keeps out of every journey reply): no answer, but the child's thinking is still served.
CURIOSITY_FALLBACK: Final[dict[Language, str]] = {
    _HINGLISH: (
        'Bahut accha sawaal hai! Iska jawab abhi nahi de paaye. Bachche se poochiye: "Tumhe kya'
        ' lagta hai, aur kyun?" Unki soch sunna hi sabse badi seekh hai.'
    ),
    _HINDI: (
        'बहुत अच्छा सवाल है! इसका जवाब अभी नहीं दे पाए। बच्चे से पूछिए: "तुम्हें क्या लगता है, और'
        ' क्यों?" उनकी सोच सुनना ही सबसे बड़ी सीख है।'
    ),
    _ENGLISH: (
        "What a good question! I can't answer it just now. Ask your child: \"What do you think,"
        ' and why?" Listening to their thinking is the biggest lesson.'
    ),
}
