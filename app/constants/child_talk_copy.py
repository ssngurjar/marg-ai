"""Fixed text for child talk (s10b §4.16, C13): to the child, and the parent's summary.

Written for a 3-8-year-old: very short sentences, no question marks in crisis texts, nothing
asked about the child. Helpline numbers come from crisis_replies (copied from official pages),
never typed here. Spoken text for Hinglish uses the Hindi (Devanagari) version, like every fixed
reply. v1, written 2026-10-27: pending the owner's review (ideally a counsellor's too).
"""

from datetime import timedelta
from typing import Final

from app.constants.crisis_replies import CHILD_HELPLINE, TELE_MANAS
from app.domain.enums import (
    CuriosityDomain,
    DailyTalkLimit,
    FixedReplyVariant,
    Language,
    LeavingReason,
)
from app.domain.models.reply import ReplyButton
from app.domain.rules.child_daily_limit_rules import ChildDailyLimitRules

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
# The child's time for today is used up (s10b §4.16; owner, 2026-11-13): instead of starting a
# session, and after the last answer when it runs out mid-session. Approved by the owner,
# 2026-11-13.
CHILD_DAILY_LIMIT_REACHED: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Aaj ki baatein poori ho gayi! Kal phir baat karenge. Tab tak ghar mein kuch naya"
        " dhoondho, aur Mummy-Papa ko batao!"
    ),
    _HINDI: "आज की बातें पूरी हो गईं! कल फिर बात करेंगे। तब तक घर में कुछ नया ढूँढो, और मम्मी-पापा को बताओ!",
    _ENGLISH: (
        "That's all our talking for today! Let's talk again tomorrow. Until then, find something"
        " new at home, and tell Mummy and Papa!"
    ),
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
# The child's "ok" twice in a row: said differently the second time (2026-11-02)
CHILD_ACKNOWLEDGED_AGAIN: Final[dict[Language, str]] = {
    _HINGLISH: "Theek hai! Jab man kare, poochho.",
    _HINDI: "ठीक है! जब मन करे, पूछो।",
    _ENGLISH: "Okay! Ask me whenever you like.",
}
# A child's hello in the middle of a talk: answered at once, not counted as a question
CHILD_GREETED: Final[dict[Language, str]] = {
    _HINGLISH: "Namaste! Mujhse kuch bhi poochho: kyun, kaise, kya.",
    _HINDI: "नमस्ते! मुझसे कुछ भी पूछो: क्यों, कैसे, क्या।",
    _ENGLISH: "Hello! Ask me anything: why, how, what.",
}
# A child's "ok", thanks or emoji: a quick fixed reply that doesn't use up a question (owner,
# 2026-11-02: small talk is answered alike for every persona)
CHILD_ACKNOWLEDGED: Final[dict[Language, str]] = {
    _HINGLISH: "Accha! Aur kuch jaanna hai? Mujhse kuch bhi poochho.",
    _HINDI: "अच्छा! और कुछ जानना है? मुझसे कुछ भी पूछो।",
    _ENGLISH: "Okay! Want to know something else? Ask me anything.",
}
# A child asked for a language ("Hindi"): this session only, never the account (owner, 2026-10-29)
# A parent taking the phone back during child talk (owner, 2026-11-01)
PARENT_TAKEOVER_ASK: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Kya aap Mummy ya Papa hain? Neeche dabaiye: {name} ki baat khatam hogi aur aap apni chat"
        " par laut aayenge."
    ),
    _HINDI: ("क्या आप मम्मी या पापा हैं? नीचे दबाइए: {name} की बात ख़त्म होगी और आप अपनी चैट पर लौट आएँगे।"),
    _ENGLISH: "Is this Mummy or Papa? Tap below to end {name}'s talk and go back to your own chat.",
}
PARENT_TAKEOVER_BUTTON: Final[dict[Language, str]] = {
    _HINGLISH: "Haan, main hoon",
    _HINDI: "हाँ, मैं हूँ",
    _ENGLISH: "Yes, I'm the parent",
}
PARENT_TAKEOVER_DONE: Final[dict[Language, str]] = {
    _HINGLISH: "{name} ki baat khatam hui. Ab aap apni chat mein hain.",
    _HINDI: "{name} की बात ख़त्म हुई। अब आप अपनी चैट में हैं।",
    _ENGLISH: "{name}'s talk has ended. You're back in your own chat.",
}
CHILD_LANGUAGE_SWITCHED: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Theek hai, ab Hindi mein baat karte hain! Mujhse kuch bhi poochho, jo tum jaanna"
        " chahte ho."
    ),
    _HINDI: "ठीक है, अब हिंदी में बात करते हैं! मुझसे कुछ भी पूछो, जो तुम जानना चाहते हो।",
    _ENGLISH: "Okay, let's talk in English! Ask me anything you want to know.",
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
# An opening that says the child is going ("Main Munni hoon, ab man nahi hai"): the session opens
# and ends at once. Nothing was talked about, so not "Aaj bahut maza aaya!" (CHILD_GOODBYE): a
# hello by name, "okay", a kind line for why they're going, and telling Mummy-Papa, as a session's
# start and end do (CLAUDE.md §11). No summary follows: nothing was asked. v1, 2026-11-20, pending
# the owner's review.
CHILD_OPENING_GOODBYE: Final[dict[LeavingReason, dict[Language, str]]] = {
    LeavingReason.NOT_IN_THE_MOOD: {
        _HINGLISH: (
            "Namaste {name}! Theek hai, abhi man nahi hai toh koi baat nahi. Jab man kare, tab"
            " baat karenge. Kuch pareshaani ho, toh Mummy-Papa ko batana."
        ),
        _HINDI: (
            "नमस्ते {name}! ठीक है, अभी मन नहीं है तो कोई बात नहीं। जब मन करे, तब बात करेंगे। कुछ परेशानी हो,"
            " तो मम्मी-पापा को बताना।"
        ),
        _ENGLISH: (
            "Hello {name}! That's okay if you don't feel like talking now. We can talk when you"
            " want to. If something is bothering you, tell Mummy and Papa."
        ),
    },
    LeavingReason.PLAY: {
        _HINGLISH: (
            "Namaste {name}! Theek hai, jao khoob khelo! Khel mein kuch naya dikhe, toh Mummy-Papa"
            " ko batana."
        ),
        _HINDI: "नमस्ते {name}! ठीक है, जाओ खूब खेलो! खेल में कुछ नया दिखे, तो मम्मी-पापा को बताना।",
        _ENGLISH: "Hello {name}! Okay, go and play! If you see something new, tell Mummy and Papa.",
    },
    LeavingReason.SLEEP: {
        _HINGLISH: (
            "Namaste {name}! Theek hai, ab aaram se so jao. Sapne mein kya dekha, uthkar"
            " Mummy-Papa ko batana."
        ),
        _HINDI: "नमस्ते {name}! ठीक है, अब आराम से सो जाओ। सपने में क्या देखा, उठकर मम्मी-पापा को बताना।",
        _ENGLISH: (
            "Hello {name}! Okay, sleep well. When you wake up, tell Mummy and Papa what you dreamt."
        ),
    },
    LeavingReason.FOOD: {
        _HINGLISH: (
            "Namaste {name}! Theek hai, jao pet bhar ke khana khao. Khane mein kya bana,"
            " Mummy-Papa se poochhna."
        ),
        _HINDI: "नमस्ते {name}! ठीक है, जाओ पेट भर के खाना खाओ। खाने में क्या बना, मम्मी-पापा से पूछना।",
        _ENGLISH: (
            "Hello {name}! Okay, go and have a good meal. Ask Mummy and Papa what they cooked."
        ),
    },
    LeavingReason.STUDY: {
        _HINGLISH: (
            "Namaste {name}! Theek hai, jao man se padhna. Aaj kya seekha, Mummy-Papa ko batana."
        ),
        _HINDI: "नमस्ते {name}! ठीक है, जाओ मन से पढ़ना। आज क्या सीखा, मम्मी-पापा को बताना।",
        _ENGLISH: (
            "Hello {name}! Okay, go and study well. Tell Mummy and Papa what you learn today."
        ),
    },
    LeavingReason.OTHER: {
        _HINGLISH: (
            "Namaste {name}! Theek hai, phir baat karenge, jab man kare. Mummy-Papa ko bhi batana"
            " ki tumne aaj kya kiya!"
        ),
        _HINDI: (
            "नमस्ते {name}! ठीक है, फिर बात करेंगे, जब मन करे। मम्मी-पापा को भी बताना कि तुमने आज क्या किया!"
        ),
        _ENGLISH: (
            "Hello {name}! Okay, we can talk later, whenever you like. Tell Mummy and Papa what"
            " you did today!"
        ),
    },
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


# --- The parent's daily limit for each child (s10b §4.16; owner, 2026-11-13) ----------------------
# Approved by the owner, 2026-11-13. 20, 30 and 60 minutes are buttons; no limit is typed
# (WhatsApp allows three buttons). "10 minute" and "aadha ghanta" are the session limits.

CHILD_TALK_LIMIT_BUTTON: Final = "jrn:limit"
"""+ ":<DailyTalkLimit value>:<learner id>" sets it; + ":ask:<learner id>" asks for that child."""
LIMITS_ON_BUTTONS: Final = (
    DailyTalkLimit.MINUTES_20,
    DailyTalkLimit.MINUTES_30,
    DailyTalkLimit.MINUTES_60,
)
DAILY_LIMIT_NAMES: Final[dict[DailyTalkLimit, dict[Language, str]]] = {
    DailyTalkLimit.MINUTES_20: {_HINGLISH: "20 minute", _HINDI: "20 मिनट", _ENGLISH: "20 minutes"},
    DailyTalkLimit.MINUTES_30: {_HINGLISH: "30 minute", _HINDI: "30 मिनट", _ENGLISH: "30 minutes"},
    DailyTalkLimit.MINUTES_60: {_HINGLISH: "1 ghanta", _HINDI: "1 घंटा", _ENGLISH: "1 hour"},
    DailyTalkLimit.NO_LIMIT: {
        _HINGLISH: "koi limit nahi",
        _HINDI: "कोई लिमिट नहीं",
        _ENGLISH: "no limit",
    },
}
# To the parent: after their yes to child talk, and whenever they ask about the limit.
CHILD_TALK_LIMIT_ASK: Final[dict[Language, str]] = {
    _HINGLISH: (
        "{child} roz kitni der Marg se baat karein: 20 minute, 30 minute ya 1 ghanta? Abhi:"
        ' {current}. Koi limit nahi chahiye toh likhiye: "limit hata do".'
    ),
    _HINDI: (
        "{child} रोज़ कितनी देर मार्ग से बात करें: 20 मिनट, 30 मिनट या 1 घंटा? अभी: {current}। कोई"
        ' लिमिट नहीं चाहिए तो लिखिए: "लिमिट हटा दो"।'
    ),
    _ENGLISH: (
        "How long may {child} talk to Marg each day: 20 minutes, 30 minutes or 1 hour? Now:"
        ' {current}. For no limit, type: "no limit".'
    ),
}
CHILD_TALK_LIMIT_SET: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Theek hai! Ab {child} roz {limit} tak Marg se baat kar sakte hain. Kabhi bhi badal"
        ' sakte hain: likhiye "limit badlo".'
    ),
    _HINDI: (
        "ठीक है! अब {child} रोज़ {limit} तक मार्ग से बात कर सकते हैं। कभी भी बदल सकते हैं: लिखिए"
        ' "लिमिट बदलो"।'
    ),
    _ENGLISH: (
        "Done! {child} can now talk to Marg for {limit} a day. You can change it any time:"
        ' type "change limit".'
    ),
}
CHILD_TALK_NO_LIMIT_SET: Final[dict[Language, str]] = {
    _HINGLISH: (
        "Theek hai, {child} ke liye roz ki koi limit nahi. Har baat phir bhi 10 minute tak hi"
        " chalegi, aur do baaton ke beech aadha ghanta aaram. Limit phir lagani ho toh likhiye"
        ' "limit badlo".'
    ),
    _HINDI: (
        "ठीक है, {child} के लिए रोज़ की कोई लिमिट नहीं। हर बात फिर भी 10 मिनट तक ही चलेगी, और दो"
        ' बातों के बीच आधा घंटा आराम। लिमिट फिर लगानी हो तो लिखिए "लिमिट बदलो"।'
    ),
    _ENGLISH: (
        "Done, no daily limit for {child}. Each talk still lasts at most 10 minutes, with half"
        ' an hour\'s break between talks. To set a limit again, type "change limit".'
    ),
}
CHILD_TALK_LIMIT_WHICH_CHILD: Final[dict[Language, str]] = {
    _HINGLISH: "Kis bachche ki limit?",
    _HINDI: "किस बच्चे की लिमिट?",
    _ENGLISH: "Which child's limit?",
}


def limit_buttons(learner_id: str, language: Language) -> tuple[ReplyButton, ...]:
    """The three limits on buttons, for one child."""
    return tuple(
        ReplyButton(
            id=f"{CHILD_TALK_LIMIT_BUTTON}:{limit.value}:{learner_id}",
            title=DAILY_LIMIT_NAMES[limit][language],
        )
        for limit in LIMITS_ON_BUTTONS
    )


# --- Time used, in the parent's summary (s10b §4.16; owner, 2026-11-13) ---------------------------
# Approved by the owner, 2026-11-13. One line under the topics: the child's time that day
# across all their talks, and their daily limit. Never in a crisis summary (C15).

PARENT_TALK_TIME: Final[dict[Language, str]] = {
    _HINGLISH: "⏱️ Aaj kul baat: {used}. Roz ki limit: {limit}.",
    _HINDI: "⏱️ आज कुल बात: {used}। रोज़ की लिमिट: {limit}।",
    _ENGLISH: "⏱️ Talk today: {used} in all. Daily limit: {limit}.",
}
PARENT_TALK_TIME_NO_LIMIT: Final[dict[Language, str]] = {
    _HINGLISH: "⏱️ Aaj kul baat: {used}. Roz ki koi limit nahi.",
    _HINDI: "⏱️ आज कुल बात: {used}। रोज़ की कोई लिमिट नहीं।",
    _ENGLISH: "⏱️ Talk today: {used} in all. No daily limit.",
}
PARENT_TALK_TIME_USED_UP: Final[dict[Language, str]] = {
    _HINGLISH: (
        "⏱️ Aaj kul baat: {used}. Roz ki {limit} ki limit poori ho gayi; kal phir baat kar sakte"
        " hain."
    ),
    _HINDI: "⏱️ आज कुल बात: {used}। रोज़ की {limit} की लिमिट पूरी हो गई; कल फिर बात कर सकते हैं।",
    _ENGLISH: (
        "⏱️ Talk today: {used} in all, so today's limit ({limit}) is used up; they can talk again"
        " tomorrow."
    ),
}
TALK_MINUTES: Final[dict[Language, str]] = {
    _HINGLISH: "{minutes} minute",
    _HINDI: "{minutes} मिनट",
    _ENGLISH: "{minutes} minutes",
}
TALK_ONE_MINUTE: Final[dict[Language, str]] = {
    _HINGLISH: "1 minute",
    _HINDI: "1 मिनट",
    _ENGLISH: "1 minute",
}
TALK_UNDER_A_MINUTE: Final[dict[Language, str]] = {
    _HINGLISH: "1 minute se kam",
    _HINDI: "1 मिनट से कम",
    _ENGLISH: "less than a minute",
}


def minutes_said(duration: timedelta, language: Language) -> str:
    """ "14 minute", "1 minute", "1 minute se kam": whole minutes rounded half up."""
    whole = ChildDailyLimitRules.whole_minutes(duration)
    if whole == 0:
        return TALK_UNDER_A_MINUTE[language]
    if whole == 1:
        return TALK_ONE_MINUTE[language]
    return TALK_MINUTES[language].format(minutes=whole)


# --- Time left today, when the parent asks (s10b §4.16; owner, 2026-11-13) ------------------------
# Approved by the owner, 2026-11-13. Two sentences: the child's time today, then
# what's left of their limit (or that it's used up, or that there is none), and how to change it.

TALKED_TODAY: Final[dict[Language, str]] = {
    _HINGLISH: "⏱️ Aaj {child} ne Marg se {used} baat ki.",
    _HINDI: "⏱️ आज {child} ने मार्ग से {used} बात की।",
    _ENGLISH: "⏱️ {child} has talked with Marg for {used} today.",
}
NOT_TALKED_TODAY: Final[dict[Language, str]] = {
    _HINGLISH: "⏱️ {child} ne aaj abhi tak Marg se baat nahi ki.",
    _HINDI: "⏱️ {child} ने आज अभी तक मार्ग से बात नहीं की।",
    _ENGLISH: "⏱️ {child} hasn't talked with Marg yet today.",
}
TIME_LEFT_TODAY: Final[dict[Language, str]] = {
    _HINGLISH: "Roz ki limit {limit} hai, toh aaj {left} aur baaki hain.",
    _HINDI: "रोज़ की लिमिट {limit} है, तो आज {left} और बाकी हैं।",
    _ENGLISH: "The daily limit is {limit}, so there's {left} left today.",
}
TIME_USED_UP_TODAY: Final[dict[Language, str]] = {
    _HINGLISH: "Roz ki {limit} ki limit poori ho gayi; kal phir baat kar sakte hain.",
    _HINDI: "रोज़ की {limit} की लिमिट पूरी हो गई; कल फिर बात कर सकते हैं।",
    _ENGLISH: "Today's limit ({limit}) is used up; they can talk again tomorrow.",
}
NO_DAILY_LIMIT: Final[dict[Language, str]] = {
    _HINGLISH: "Roz ki koi limit nahi hai.",
    _HINDI: "रोज़ की कोई लिमिट नहीं है।",
    _ENGLISH: "There's no daily limit.",
}
CHANGE_LIMIT_HINT: Final[dict[Language, str]] = {
    _HINGLISH: 'Limit badalni ho toh likhiye "limit badlo".',
    _HINDI: 'लिमिट बदलनी हो तो लिखिए "लिमिट बदलो"।',
    _ENGLISH: 'To change it, type "change limit".',
}
