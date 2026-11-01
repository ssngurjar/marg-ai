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
KHOJ_ABOUT = "jrn:about"  # + ":<learner activity id>": which khoj a report is about (2026-11-01)

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
# After a reported khoj: the obvious next step (owner's judge walkthrough, 2026-10-29: the
# reflection offered only "Another child").
ONE_MORE_KHOJ_BUTTON: Final[dict[Language, ReplyButton]] = {
    _HINGLISH: ReplyButton(id=KHOJ_TODAY, title="Ek aur khoj"),
    _HINDI: ReplyButton(id=KHOJ_TODAY, title="एक और खोज"),
    _ENGLISH: ReplyButton(id=KHOJ_TODAY, title="One more khoj"),
}
# A parent says they have another child (intent reading): the existing add-child flow starts
# from its button (owner, 2026-10-29).
# A greeting or a thank-you with no khoj open (owner's demo, 2026-10-29: "Hi" made the parent
# answer ask the child's age, which Marg already knows). {child}: the nickname, or a fallback.
# "ok", "theek hai", "thanks" after Marg suggested something (owner's demo, 2026-11-01)
ACKNOWLEDGED: Final[dict[Language, str]] = {
    _HINGLISH: "Bahut badhiya! Saath mein maza kijiye, aur bataiye bachche ne kya kaha.",
    _HINDI: "बहुत बढ़िया! साथ में मज़ा कीजिए, और बताइए बच्चे ने क्या कहा।",
    _ENGLISH: "Great! Enjoy it together, and tell me what your child says.",
}
HELLO_NOTHING_OPEN: Final[dict[Language, str]] = {
    _HINGLISH: "Namaste! {child} ke saath aaj ki khoj karni hai, ya kuch poochhna hai?",
    _HINDI: "नमस्ते! {child} के साथ आज की खोज करनी है, या कुछ पूछना है?",
    _ENGLISH: "Hello! Would you like today's khoj with {child}, or do you have a question?",
}
CHILD_IN_HELLO: Final[dict[Language, str]] = {
    _HINGLISH: "bachche",
    _HINDI: "बच्चे",
    _ENGLISH: "your child",
}
TODAY_KHOJ_BUTTON: Final[dict[Language, ReplyButton]] = {
    _HINGLISH: ReplyButton(id=KHOJ_TODAY, title="Aaj ki khoj"),
    _HINDI: ReplyButton(id=KHOJ_TODAY, title="आज की खोज"),
    _ENGLISH: ReplyButton(id=KHOJ_TODAY, title="Today's khoj"),
}
ADD_CHILD_PROMPT: Final[dict[Language, str]] = {
    _HINGLISH: "Zaroor! Neeche 'Doosra bachcha' dabaiye, phir unki umar bataiye.",
    _HINDI: "ज़रूर! नीचे 'दूसरा बच्चा' दबाइए, फिर उनकी उम्र बताइए।",
    _ENGLISH: "Of course! Tap 'Another child' below, then tell me their age.",
}
ADD_CHILD_BUTTON: Final[dict[Language, ReplyButton]] = {
    _HINGLISH: ReplyButton(id="onb:add-child", title="Doosra bachcha"),
    _HINDI: ReplyButton(id="onb:add-child", title="दूसरा बच्चा"),
    _ENGLISH: ReplyButton(id="onb:add-child", title="Another child"),
}
# A longer message read as "delete my data" (owner, 2026-11-01): the button starts the usual
# deletion, which asks once more before anything is deleted.
DELETE_DATA_OFFER: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Kya aap chahte hain ki Marg aapka aur bachchon ka sab data mita de? Neeche dabaiye; kuch "
        "bhi mitane se pehle main ek baar aur poochunga."
    ),
    _HINDI: (
        "क्या आप चाहते हैं कि मार्ग आपका और बच्चों का सारा डेटा मिटा दे? नीचे दबाइए; कुछ भी मिटाने से "
        "पहले मैं एक बार और पूछूँगा।"
    ),
    _ENGLISH: (
        "Do you want Marg to delete everything it keeps about you and your children? Tap below; "
        "I'll ask once more before anything is deleted."
    ),
}
DELETE_DATA_BUTTON: Final[dict[Language, ReplyButton]] = {
    _HINGLISH: ReplyButton(id="onb:delete:ask", title="Data mitao"),
    _HINDI: ReplyButton(id="onb:delete:ask", title="डेटा मिटाओ"),
    _ENGLISH: ReplyButton(id="onb:delete:ask", title="Delete my data"),
}
# "Sab band karo, mujhe ye nahi chahiye": stop the daily message, or delete everything? Marg
# asks; deleting still asks once more (critic review D1, owner 2026-11-01).
STOP_WHICH: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Kya band karein? Sirf roz ka message band kar sakte hain, ya Marg aapka aur bachchon ka"
        " sab data mita de. Neeche chuniye."
    ),
    _HINDI: (
        "क्या बंद करें? सिर्फ़ रोज़ का संदेश बंद कर सकते हैं, या मार्ग आपका और बच्चों का सारा डेटा मिटा दे। नीचे चुनिए।"
    ),
    _ENGLISH: (
        "What should I stop? I can stop just the daily message, or delete everything Marg keeps"
        " about you and your children. Choose below."
    ),
}
STOP_DAILY_BUTTON: Final[dict[Language, ReplyButton]] = {
    _HINGLISH: ReplyButton(id="nudge:off", title="Roz ka message band"),
    _HINDI: ReplyButton(id="nudge:off", title="रोज़ का संदेश बंद"),
    _ENGLISH: ReplyButton(id="nudge:off", title="Stop daily message"),
}
# A child's home name given or changed after onboarding (owner, 2026-11-01)
NICKNAME_SAVED: Final[dict[Language, str]] = {
    _HINGLISH: "Theek hai, ab se main {child} ka naam lekar baat karunga.",
    _HINDI: "ठीक है, अब से मैं {child} का नाम लेकर बात करूँगा।",
    _ENGLISH: "Got it, I'll call your child {child} from now on.",
}
NICKNAME_ONLY: Final[dict[Language, str]] = {
    _HINGLISH: "Bas ghar ka chhota naam bataiye, jaise 'Munni'. Poora naam nahi chahiye.",
    _HINDI: "बस घर का छोटा नाम बताइए, जैसे 'मुन्नी'। पूरा नाम नहीं चाहिए।",
    _ENGLISH: "Just a short home name is enough, like 'Munni'. Please don't send a full name.",
}
# A report that may be about another recent khoj (owner's demo, 2026-11-01)
WHICH_KHOJ: Final[dict[Language, str]] = {
    _HINGLISH: "Yeh kis khoj ke baare mein hai?",
    _HINDI: "यह किस खोज के बारे में है?",
    _ENGLISH: "Which khoj is this about?",
}
# A parent's progress summary, built by code from the record (owner, 2026-11-01)
PROGRESS_HEADER: Final[dict[Language, str]] = {
    _HINGLISH: "{name}, pichhle 30 din:",
    _HINDI: "{name}, पिछले 30 दिन:",
    _ENGLISH: "{name}, the last 30 days:",
}
PROGRESS_DONE: Final[dict[Language, str]] = {
    _HINGLISH: "• Ki gayi khoj: {count} ({titles})",
    _HINDI: "• की गई खोजें: {count} ({titles})",
    _ENGLISH: "• Khojs done: {count} ({titles})",
}
PROGRESS_SKIPPED: Final[dict[Language, str]] = {
    _HINGLISH: "• Chhodi: {count}",
    _HINDI: "• छोड़ी: {count}",
    _ENGLISH: "• Skipped: {count}",
}
PROGRESS_EXPLORED: Final[dict[Language, str]] = {
    _HINGLISH: "• Jaana-samjha: {topics}",
    _HINDI: "• जाना-समझा: {topics}",
    _ENGLISH: "• Explored: {topics}",
}
PROGRESS_ASKED: Final[dict[Language, str]] = {
    _HINGLISH: "• Marg se khud poochha: {topics}",
    _HINDI: "• मार्ग से खुद पूछा: {topics}",
    _ENGLISH: "• Asked Marg about: {topics}",
}
PROGRESS_NOTHING_YET: Final[dict[Language, str]] = {
    _HINGLISH: "{name} ne abhi tak koi khoj nahi ki. Aaj ki khoj maangiye, shuru karte hain!",
    _HINDI: "{name} ने अभी तक कोई खोज नहीं की। आज की खोज माँगिए, शुरू करते हैं!",
    _ENGLISH: "{name} hasn't done a khoj yet. Ask for today's khoj to begin!",
}
# "Done" with nothing said (owner's demo, 2026-11-01)
DONE_THANKS: Final[dict[Language, str]] = {
    _HINGLISH: "Shukriya, aapne saath mein khoj ki! {child} ne karte hue kya kaha ya kya dekha?",
    _HINDI: "शुक्रिया, आपने साथ में खोज की! {child} ने करते हुए क्या कहा या क्या देखा?",
    _ENGLISH: "Thank you for doing it together! What did {child} say or notice while doing it?",
}
NO_DETAILS_SUMMARY: Final = "Done; the parent didn't say how it went."  # the learner record
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
# A greeting or a thank-you while a khoj is open: not a report (owner, 2026-10-29).
KHOJ_STILL_OPEN: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Namaste! Aaj ki khoj abhi baaki hai: {title}. Bachche ke saath karke 'Ho gaya ✓'"
        " dabaiye, ya mujhse kuch bhi poochhiye."
    ),
    _HINDI: (
        "नमस्ते! आज की खोज अभी बाकी है: {title}। बच्चे के साथ करके 'हो गया ✓' दबाइए, या मुझसे कुछ भी पूछिए।"
    ),
    _ENGLISH: (
        "Hello! Today's khoj is still waiting: {title}. Try it with your child and tap"
        " 'Done ✓', or ask me anything."
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

# The daily khoj message (s10b §4.11): when to send it, and what the parent hears back. Button
# ids carry the IST hour; "off" turns it off.
NUDGE_AT_8 = "nudge:08"
NUDGE_AT_18 = "nudge:18"
NUDGE_OFF = "nudge:off"
NUDGE_ASK: Final[dict[Language, str]] = {
    _HINGLISH: "Roz ki khoj ka message kab bhejein?",
    _HINDI: "रोज़ की खोज का संदेश कब भेजें?",
    _ENGLISH: "When should I send the daily discovery?",
}
NUDGE_BUTTONS: Final[dict[Language, tuple[ReplyButton, ...]]] = {
    _HINGLISH: (
        ReplyButton(id=NUDGE_AT_8, title="Subah 8 baje"),
        ReplyButton(id=NUDGE_AT_18, title="Shaam 6 baje"),
        ReplyButton(id=NUDGE_OFF, title="Khud poochhenge"),
    ),
    _HINDI: (
        ReplyButton(id=NUDGE_AT_8, title="सुबह 8 बजे"),
        ReplyButton(id=NUDGE_AT_18, title="शाम 6 बजे"),
        ReplyButton(id=NUDGE_OFF, title="खुद पूछेंगे"),
    ),
    _ENGLISH: (
        ReplyButton(id=NUDGE_AT_8, title="8 in the morning"),
        ReplyButton(id=NUDGE_AT_18, title="6 in the evening"),
        ReplyButton(id=NUDGE_OFF, title="I'll ask myself"),
    ),
}
NUDGE_ON: Final[dict[Language, str]] = {
    _HINGLISH: (
        'Theek hai! Roz {time} baje aaj ki khoj bhejenge. Badalna ho toh "time badlo" likhiye.'
    ),
    _HINDI: 'ठीक है! रोज़ {time} बजे आज की खोज भेजेंगे। बदलना हो तो "समय बदलो" लिखिए।',
    _ENGLISH: (
        "Done! I'll send the day's discovery at {time} every day. Write \"change time\" to"
        " change it."
    ),
}
NUDGE_TIME_NAMES: Final[dict[str, dict[Language, str]]] = {
    NUDGE_AT_8: {_HINGLISH: "subah 8", _HINDI: "सुबह 8", _ENGLISH: "8 am"},
    NUDGE_AT_18: {_HINGLISH: "shaam 6", _HINDI: "शाम 6", _ENGLISH: "6 pm"},
}
NUDGE_OFF_REPLY: Final[dict[Language, str]] = {
    _HINGLISH: 'Theek hai, roz ka message nahi aayega. Jab chahein "aaj ki khoj" likhiye.',
    _HINDI: 'ठीक है, रोज़ का संदेश नहीं आएगा। जब चाहें "आज की खोज" लिखिए।',
    _ENGLISH: 'Okay, no daily message. Write "today\'s khoj" whenever you like.',
}
