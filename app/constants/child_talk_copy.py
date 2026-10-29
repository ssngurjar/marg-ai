"""Fixed text for child talk (s10b §4.16, C13): to the child, and the parent's summary.

Written for a 3-8-year-old: very short sentences, no question marks in crisis texts, nothing
asked about the child. Helpline numbers come from crisis_replies (copied from official pages),
never typed here. Spoken text for Hinglish uses the Hindi (Devanagari) version, like every fixed
reply. v1, written 2026-10-27: pending the owner's review (ideally a counsellor's too).
"""

from typing import Final

from app.constants.crisis_replies import CHILD_HELPLINE, TELE_MANAS
from app.domain.enums import CuriosityDomain, FixedReplyVariant, Language
from app.domain.models.reply import ReplyButton

_HINGLISH = Language.HINGLISH
_HINDI = Language.HINDI
_ENGLISH = Language.ENGLISH
_D = CuriosityDomain

KID_START_TITLE: Final[dict[Language, str]] = {
    _HINGLISH: "Main bachcha hoon 🙋",
    _HINDI: "मैं बच्चा हूँ 🙋",
    _ENGLISH: "I'm the child 🙋",
}

# To the parent, when a child tries to talk before it's switched on (button: turn it on).
CHILD_TALK_NOT_ENABLED: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Bachche ka Marg se khud baat karna abhi chalu nahi hai. Agar aap chahein ki {name}"
        ' khud Marg se sawaal pooche, toh "Haan, baat kare" dabaiye.'
    ),
    _HINDI: (
        "बच्चे का मार्ग से खुद बात करना अभी चालू नहीं है। अगर आप चाहें कि {name} खुद मार्ग से"
        ' सवाल पूछे, तो "हाँ, बात करे" दबाइए।'
    ),
    _ENGLISH: (
        "Talking directly with your child isn't switched on yet. If you'd like {name} to ask"
        ' Marg questions themselves, tap "Yes, they can".'
    ),
}
CHILD_TALK_ON_BUTTON: Final[dict[Language, str]] = {
    _HINGLISH: "Haan, baat kare",
    _HINDI: "हाँ, बात करे",
    _ENGLISH: "Yes, they can",
}
CHILD_TALK_COOLDOWN: Final[dict[Language, str]] = {
    _HINGLISH: "Thodi der baad phir baat karenge! Tab tak jaao, ghar mein kuch naya dhoondho.",
    _HINDI: "थोड़ी देर बाद फिर बात करेंगे! तब तक जाओ, घर में कुछ नया ढूँढो।",
    _ENGLISH: "Let's talk again a little later! Until then, go and find something new at home.",
}
WHICH_CHILD_IS_TALKING: Final[dict[Language, str]] = {
    _HINGLISH: 'Namaste! Apna naam bolo: "Main ... hoon".',
    _HINDI: 'नमस्ते! अपना नाम बोलो: "मैं ... हूँ"।',
    _ENGLISH: 'Hello! Say your name: "I\'m ...".',
}

# To the child
CHILD_HELLO: Final[dict[Language, str]] = {
    _HINGLISH: "Namaste {name}! Mujhse kuch bhi poochho, jo tum jaanna chahte ho.",
    _HINDI: "नमस्ते {name}! मुझसे कुछ भी पूछो, जो तुम जानना चाहते हो।",
    _ENGLISH: "Hello {name}! Ask me anything you want to know.",
}
TELL_YOUR_PARENTS: Final[dict[Language, str]] = {
    _HINGLISH: "Mummy-Papa ko bhi batana!",
    _HINDI: "मम्मी-पापा को भी बताना!",
    _ENGLISH: "Tell Mummy and Papa too!",
}
ASK_A_GROWNUP: Final[dict[Language, str]] = {
    _HINGLISH: "Yeh kaam Mummy-Papa karenge. Tum mujhse kuch aur poochho!",
    _HINDI: "यह काम मम्मी-पापा करेंगे। तुम मुझसे कुछ और पूछो!",
    _ENGLISH: "Mummy and Papa will do that. Ask me something else!",
}
CHILD_GOODBYE: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Aaj bahut maza aaya! Ab jaao, ghar mein teen alag rang ki cheezein dhoondho."
        " Mummy-Papa ko bhi batao ki tumne kya dhoondha!"
    ),
    _HINDI: (
        "आज बहुत मज़ा आया! अब जाओ, घर में तीन अलग रंग की चीज़ें ढूँढो। मम्मी-पापा को भी बताओ कि तुमने क्या ढूँढा!"
    ),
    _ENGLISH: (
        "That was fun! Now go and find three things of different colours at home. Tell Mummy"
        " and Papa what you found!"
    ),
}
CHILD_REFUSE: Final[dict[Language, str]] = {
    _HINGLISH: "Yeh baat Mummy-Papa ya doctor se poochho. Mujhse kuch aur poochho!",
    _HINDI: "यह बात मम्मी-पापा या डॉक्टर से पूछो। मुझसे कुछ और पूछो!",
    _ENGLISH: "Ask Mummy, Papa or a doctor about that. Ask me something else!",
}
# Fixed refusals by reason (owner, 2026-10-28: "ask a doctor" only fits a medical question).
# Sent when a blocked message can't get a model-written redirect, or the redirect fails.
CHILD_REFUSE_DANGER: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Yeh cheez bahut khatarnak hai, isliye ise sirf bade log sambhalte hain, bachche kabhi"
        " nahi chhoote. Mujhse poochho: aawaz kaise chalti hai, ya cheezein kaise udti hain?"
    ),
    _HINDI: (
        "यह चीज़ बहुत ख़तरनाक है, इसलिए इसे सिर्फ़ बड़े लोग संभालते हैं, बच्चे कभी नहीं छूते। मुझसे"
        " पूछो: आवाज़ कैसे चलती है, या चीज़ें कैसे उड़ती हैं?"
    ),
    _ENGLISH: (
        "That is very dangerous, so only grown-ups handle it, and children never touch it. Ask"
        " me how sound travels, or how things fly!"
    ),
}
CHILD_REFUSE_HURTING: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Gussa aana theek hai, par maarne se chot lagti hai. Mummy-Papa ya teacher ko batao,"
        " woh madad karenge. Mujhse kuch aur poochho!"
    ),
    _HINDI: (
        "गुस्सा आना ठीक है, पर मारने से चोट लगती है। मम्मी-पापा या टीचर को बताओ, वो मदद करेंगे।"
        " मुझसे कुछ और पूछो!"
    ),
    _ENGLISH: (
        "It's okay to feel angry, but hitting hurts. Tell Mummy, Papa or your teacher, they"
        " will help. Ask me something else!"
    ),
}
CHILD_REFUSE_OTHER: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Yeh baat bade log sambhalte hain. Agar kuch tumhe pareshan kar raha hai, to"
        " Mummy-Papa ko zaroor batao. Mujhse kuch aur poochho!"
    ),
    _HINDI: (
        "यह बात बड़े लोग संभालते हैं। अगर कुछ तुम्हें परेशान कर रहा है, तो मम्मी-पापा को ज़रूर बताओ। मुझसे कुछ और पूछो!"
    ),
    _ENGLISH: (
        "Grown-ups take care of that. If something is bothering you, do tell Mummy and Papa."
        " Ask me something else!"
    ),
}
CHILD_REFUSE_BY_VARIANT: Final[dict[FixedReplyVariant, dict[Language, str]]] = {
    FixedReplyVariant.DANGEROUS_MAKING: CHILD_REFUSE_DANGER,
    FixedReplyVariant.HARMFUL: CHILD_REFUSE_OTHER,
}
"""A blocked child message's fixed reply; MEDICAL keeps CHILD_REFUSE, every other variant gets
CHILD_REFUSE_OTHER. HARMFUL covers sexual content too, so it never assumes anger."""
CHILD_FALLBACK: Final[dict[Language, str]] = {
    _HINGLISH: "Bahut accha sawaal! Tumhe kya lagta hai? Mummy-Papa ke saath milkar socho.",
    _HINDI: "बहुत अच्छा सवाल! तुम्हें क्या लगता है? मम्मी-पापा के साथ मिलकर सोचो।",
    _ENGLISH: "What a good question! What do you think? Think about it with Mummy and Papa.",
}

# Crisis in a child's words (s07 §4.6, C15): no question marks; the session ends after it.
_CHILD_CRISIS_TEMPLATES: Final[dict[FixedReplyVariant, dict[Language, str]]] = {
    FixedReplyVariant.SELF_HARM: {
        _HINGLISH: (
            "Tum udaas ho, yeh theek hai. Yeh tumhari galti nahi hai. Abhi Mummy, Papa ya teacher"
            " ko batao. {child} par phone karke bhi madad milti hai."
        ),
        _HINDI: (
            "तुम उदास हो, यह ठीक है। यह तुम्हारी गलती नहीं है। अभी मम्मी, पापा या टीचर को बताओ।"
            " {child} पर फ़ोन करके भी मदद मिलती है।"
        ),
        _ENGLISH: (
            "It's okay to feel sad. It is not your fault. Tell Mummy, Papa or a teacher now."
            " You can also call {child} for help."
        ),
    },
    FixedReplyVariant.ABUSE: {
        _HINGLISH: (
            "Tumne bataya, yeh bahut achha kiya. Yeh tumhari galti nahi hai. Kisi bade ko batao"
            " jis par tumhe bharosa ho, jaise teacher ya anganwadi didi. {child} par phone karke"
            " madad milti hai."
        ),
        _HINDI: (
            "तुमने बताया, यह बहुत अच्छा किया। यह तुम्हारी गलती नहीं है। किसी बड़े को बताओ जिस पर"
            " तुम्हें भरोसा हो, जैसे टीचर या आंगनवाड़ी दीदी। {child} पर फ़ोन करके मदद मिलती है।"
        ),
        _ENGLISH: (
            "You did well to tell me. It is not your fault. Tell a grown-up you trust, like a"
            " teacher or the anganwadi didi. You can call {child} for help."
        ),
    },
}


def _spoken_digits(number: str) -> str:
    return " ".join(number)


CHILD_CRISIS_TEXTS: Final[dict[tuple[FixedReplyVariant, Language], str]] = {
    (variant, language): template.format(child=CHILD_HELPLINE.number)
    for variant, texts in _CHILD_CRISIS_TEMPLATES.items()
    for language, template in texts.items()
}
CHILD_CRISIS_SPOKEN: Final[dict[tuple[FixedReplyVariant, Language], str]] = {
    (variant, language): template.format(child=_spoken_digits(CHILD_HELPLINE.number))
    for variant, texts in _CHILD_CRISIS_TEMPLATES.items()
    for language, template in texts.items()
}

# To the parent, after the session (topics only, never the child's words)
PARENT_SUMMARY: Final[dict[Language, str]] = {
    _HINGLISH: (
        "👪 Mummy-Papa ke liye: Aaj {name} ne Marg se {topics} ke baare mein baatein ki. Shaam ko"
        " unse poochiye ki unhone kya naya jaana!"
    ),
    _HINDI: (
        "👪 मम्मी-पापा के लिए: आज {name} ने मार्ग से {topics} के बारे में बातें कीं। शाम को उनसे"
        " पूछिए कि उन्होंने क्या नया जाना!"
    ),
    _ENGLISH: (
        "👪 For Mummy and Papa: today {name} talked with Marg about {topics}. This evening, ask"
        " them what they found out!"
    ),
}
PARENT_SUMMARY_NO_TOPICS: Final[dict[Language, str]] = {
    _HINGLISH: "👪 Mummy-Papa ke liye: Aaj {name} ne Marg se baatein ki. Unse poochiye kaisa laga!",
    _HINDI: "👪 मम्मी-पापा के लिए: आज {name} ने मार्ग से बातें कीं। उनसे पूछिए कैसा लगा!",
    _ENGLISH: "👪 For Mummy and Papa: today {name} talked with Marg. Ask them how it went!",
}
# After a self-harm or deep-sadness signal: gentle, with the adult helpline, nothing the child
# said. After an abuse disclosure no summary is sent at all (C15).
PARENT_SUMMARY_AFTER_SADNESS: Final[dict[Language, str]] = {
    _HINGLISH: (
        "👪 Mummy-Papa ke liye: Aaj baat karte hue {name} udaas lage. Pyaar se unke saath baith"
        f"kar baat kijiye. Zaroorat ho toh Tele-MANAS {TELE_MANAS.number} par baat kar sakte hain."
    ),
    _HINDI: (
        "👪 मम्मी-पापा के लिए: आज बात करते हुए {name} उदास लगे। प्यार से उनके साथ बैठकर बात"
        f" कीजिए। ज़रूरत हो तो टेली-मानस {TELE_MANAS.number} पर बात कर सकते हैं।"
    ),
    _ENGLISH: (
        "👪 For Mummy and Papa: {name} seemed sad while talking today. Sit with them and talk"
        f" gently. If you need to, you can call Tele-MANAS on {TELE_MANAS.number}."
    ),
}
UNNAMED_CHILD_NAME: Final[dict[Language, str]] = {
    _HINGLISH: "aapke bachche",
    _HINDI: "आपके बच्चे",
    _ENGLISH: "your child",
}
TOPIC_LABELS: Final[dict[CuriosityDomain, dict[Language, str]]] = {
    _D.NATURE_LIVING: {_HINGLISH: "ped-paudhe aur jaanwar", _HINDI: "पेड़-पौधे और जानवर",
                       _ENGLISH: "plants and animals"},
    _D.EARTH_SKY: {_HINGLISH: "aasmaan aur mausam", _HINDI: "आसमान और मौसम",
                   _ENGLISH: "the sky and weather"},
    _D.NUMBERS_PATTERNS: {_HINGLISH: "ginti aur pattern", _HINDI: "गिनती और पैटर्न",
                          _ENGLISH: "numbers and patterns"},
    _D.WORDS_STORIES: {_HINGLISH: "shabd aur kahaniyan", _HINDI: "शब्द और कहानियाँ",
                       _ENGLISH: "words and stories"},
    _D.MAKING_BUILDING: {_HINGLISH: "cheezein banana", _HINDI: "चीज़ें बनाना",
                         _ENGLISH: "making things"},
    _D.MOVEMENT_BODY: {_HINGLISH: "khel aur daudna", _HINDI: "खेल और दौड़ना",
                       _ENGLISH: "play and movement"},
    _D.ART_MUSIC: {_HINGLISH: "rang aur sangeet", _HINDI: "रंग और संगीत",
                   _ENGLISH: "colours and music"},
    _D.PEOPLE_FEELINGS: {_HINGLISH: "log aur bhavnaayein", _HINDI: "लोग और भावनाएँ",
                         _ENGLISH: "people and feelings"},
    _D.EVERYDAY_WORK: {_HINGLISH: "ghar aur kaam", _HINDI: "घर और काम",
                       _ENGLISH: "home and work"},
}  # fmt: skip


# Someone other than the parent seems to be writing (intent reading; owner, 2026-10-29): a
# family often has one phone. Marg asks, and answers nobody the parent hasn't added. {names}:
# the children aged 3-8 on the parent's list, each also a button.
WHO_IS_WRITING: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Kaun likh raha hai? Agar tum {names} ho, toh apna naam dabao. Agar tumhara naam yahan"
        " nahi hai, toh Mummy ya Papa se kaho ki pehle tumhe Marg par jod dein. Mummy-Papa hain,"
        " toh bas likhte rahiye."
    ),
    _HINDI: (
        "कौन लिख रहा है? अगर तुम {names} हो, तो अपना नाम दबाओ। अगर तुम्हारा नाम यहाँ नहीं है,"
        " तो मम्मी या पापा से कहो कि पहले तुम्हें मार्ग पर जोड़ दें। मम्मी-पापा हैं, तो बस लिखते"
        " रहिए।"
    ),
    _ENGLISH: (
        "Who's writing? If you're {names}, tap your name. If your name isn't here, please ask"
        " your Mummy or Papa to add you on Marg first. If you're the parent, just carry on."
    ),
}
WHO_IS_WRITING_NO_CHILD: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Kaun likh raha hai? Marg bachchon se tabhi baat karta hai jab Mummy ya Papa unhe jod"
        " dein, toh pehle unse kaho. Mummy-Papa hain, toh bas likhte rahiye."
    ),
    _HINDI: (
        "कौन लिख रहा है? मार्ग बच्चों से तभी बात करता है जब मम्मी या पापा उन्हें जोड़ दें, तो"
        " पहले उनसे कहो। मम्मी-पापा हैं, तो बस लिखते रहिए।"
    ),
    _ENGLISH: (
        "Who's writing? Marg talks with a child only once their Mummy or Papa has added them,"
        " so please ask them first. If you're the parent, just carry on."
    ),
}
OR_WORD: Final[dict[Language, str]] = {_HINGLISH: "ya", _HINDI: "या", _ENGLISH: "or"}


def named_kid_button(learner_id: str, nickname: str) -> ReplyButton:
    """A child's own name as the button that starts their talk ("Who's writing?")."""
    return ReplyButton(id=f"kid:start:{learner_id}", title=nickname)


def kid_start_button(learner_id: str, language: Language) -> ReplyButton:
    return ReplyButton(id=f"kid:start:{learner_id}", title=KID_START_TITLE[language])
