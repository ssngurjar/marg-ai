"""Fixed replies: reviewed copy keyed by (kind, variant, language) (contracts §6).

Never generated, never translated. Each kind is added, in every language, by the step that first
sends it: S4 added TRY_AGAIN_LATER; S5 adds HOLDING, REPEAT_PLEASE, UNSUPPORTED_MEDIA, REFUSE and
CRISIS (texts in crisis_replies.py); S6, S7, S8 and S10b add theirs. Written for parents; worded
without grammatical gender for the speaker. S5 copy (v1) is pending the owner's review.
`FixedReplyService` reads these; a startup check makes sure every kind exists in every language.
"""

from dataclasses import dataclass
from typing import Final

from app.constants.crisis_replies import CRISIS_TEXTS, CRISIS_VERSION
from app.domain.enums import FixedReplyKind, FixedReplyVariant, Language

FALLBACK_LANGUAGE: Final = Language.HINGLISH  # used when the user's language isn't known yet


@dataclass(frozen=True, slots=True)
class FixedText:
    text: str
    spoken_text: str  # what TTS reads: no URLs, markdown or emoji
    version: str


@dataclass(frozen=True, slots=True)
class FixedTextKey:
    kind: FixedReplyKind
    variant: FixedReplyVariant
    language: Language


_TRY_AGAIN_LATER_HINGLISH = (
    "Maaf kijiye, abhi jawab dene mein dikkat aa rahi hai. Thodi der baad phir se message kijiye."
)
_TRY_AGAIN_LATER_HINDI = "माफ़ कीजिए, अभी जवाब देने में दिक्कत आ रही है। थोड़ी देर बाद फिर से संदेश भेजिए।"
_TRY_AGAIN_LATER_ENGLISH = (
    "Sorry, I can't reply right now. Please send your message again in a little while."
)


_K = FixedReplyKind
_V = FixedReplyVariant
_HINGLISH = Language.HINGLISH
_HINDI = Language.HINDI
_ENGLISH = Language.ENGLISH

# (kind, variant) → {language: text}. Spoken text is the same as the text, except Hinglish:
# the Hindi voice reads only Devanagari, so a Hinglish reply is spoken from the reviewed Hindi
# text of the same reply (s06 §4.6; owner, 2026-10-27).
_PLAIN_TEXTS: Final[dict[tuple[FixedReplyKind, FixedReplyVariant], dict[Language, str]]] = {
    (_K.TRY_AGAIN_LATER, _V.DEFAULT): {
        _HINGLISH: _TRY_AGAIN_LATER_HINGLISH,
        _HINDI: _TRY_AGAIN_LATER_HINDI,
        _ENGLISH: _TRY_AGAIN_LATER_ENGLISH,
    },
    (_K.HOLDING, _V.DEFAULT): {
        _HINGLISH: (
            "Abhi aapka message dekhne mein dikkat aa rahi hai. Kripya kuch minute baad dobara "
            "bhejiye."
        ),
        _HINDI: "अभी आपका संदेश देखने में दिक्कत आ रही है। कृपया कुछ मिनट बाद दोबारा भेजिए।",
        _ENGLISH: "I'm having trouble right now. Please send your message again in a few minutes.",
    },
    (_K.REPEAT_PLEASE, _V.DEFAULT): {
        # v2 (S6): no longer says "write it", so it fits a voice note that wasn't understood
        _HINGLISH: "Aapka message samajh nahi aaya. Kya aap ek baar phir se bhejenge?",
        _HINDI: "आपका संदेश समझ नहीं आया। क्या आप एक बार फिर से भेजेंगे?",
        _ENGLISH: "I couldn't understand that. Could you send it again?",
    },
    (_K.TOO_LONG, _V.DEFAULT): {
        _HINGLISH: (
            "Aapka voice message bahut lamba hai. Kripya chhota message bhejiye, ya apni baat do"
            " hisson mein bhejiye."
        ),
        _HINDI: "आपका वॉइस मैसेज बहुत लंबा है। कृपया छोटा मैसेज भेजिए, या अपनी बात दो हिस्सों में भेजिए।",
        _ENGLISH: (
            "Your voice message is too long. Please send a shorter one, or split it into two."
        ),
    },
    (_K.UNSUPPORTED_MEDIA, _V.DEFAULT): {
        _HINGLISH: "Is tarah ka message abhi samajh nahi paate. Kripya apni baat likh kar bhejiye.",
        _HINDI: "इस तरह का संदेश अभी समझ नहीं पाते। कृपया अपनी बात लिखकर भेजिए।",
        _ENGLISH: "I can't read this kind of message yet. Please type what you'd like to say.",
    },
    # Activity photos (s10b §4.14, C7; owner 2026-10-28: any person, a hand too, is refused).
    (_K.PHOTO_HAS_PERSON, _V.DEFAULT): {
        _HINGLISH: (
            "Is photo mein koi insaan dikh raha hai, isliye humne ise turant hata diya. Kripya sirf"
            " bachche ki banayi ya ikatthi cheezon ki photo bhejiye, kisi ka chehra ya haath nahi."
        ),
        _HINDI: (
            "इस फ़ोटो में कोई इंसान दिख रहा है, इसलिए हमने इसे तुरंत हटा दिया। कृपया सिर्फ़ बच्चे की"
            " बनाई या इकट्ठी चीज़ों की फ़ोटो भेजिए, किसी का चेहरा या हाथ नहीं।"
        ),
        _ENGLISH: (
            "This photo shows a person, so we deleted it right away. Please send a photo of only"
            " the things your child made or collected, without anyone's face or hands."
        ),
    },
    (_K.PHOTO_NOT_NEEDED, _V.DEFAULT): {
        _HINGLISH: (
            "Photo ke liye shukriya! Photo tab kaam aati hai jab aap khoj ke baad bachche ki banayi"
            ' ya ikatthi cheezein dikhate hain. Nayi khoj ke liye "Aaj ki khoj" likhiye.'
        ),
        _HINDI: (
            "फ़ोटो के लिए धन्यवाद! फ़ोटो तब काम आती है जब आप खोज के बाद बच्चे की बनाई या इकट्ठी"
            ' चीज़ें दिखाते हैं। नई खोज के लिए "आज की खोज" लिखिए।'
        ),
        _ENGLISH: (
            "Thanks for the photo! Photos help after a khoj, to show what your child made or"
            ' collected. Type "Aaj ki khoj" to start one.'
        ),
    },
    # The daily nudge template's body, recorded on the NUDGE turn (s10b §4.11). Must match the
    # templates submitted in WhatsApp Manager word for word.
    (_K.NUDGE, _V.DEFAULT): {
        _HINGLISH: "Aaj ki khoj taiyaar hai! 2 minute, bachche ke saath.",
        _HINDI: "आज की खोज तैयार है! 2 मिनट, बच्चे के साथ।",
        _ENGLISH: "Today's discovery is ready! 2 minutes, with your child.",
    },
    (_K.REFUSE, _V.HARMFUL): {
        _HINGLISH: (
            "Is baare mein madad nahi kar sakte. Padhai, khel, career ya bachchon ki seekh ke "
            "baare mein poochhiye."
        ),
        _HINDI: ("इस बारे में मदद नहीं कर सकते। पढ़ाई, खेल, करियर या बच्चों की सीख के बारे में पूछिए।"),
        _ENGLISH: (
            "I can't help with that. Ask me about studies, play, careers or children's learning."
        ),
    },
    (_K.REFUSE, _V.PRIVACY): {
        _HINGLISH: (
            "Kisi aur ki jaankari hum kabhi share nahi karte, aur aapke message bhi private rehte"
            " hain."
        ),
        _HINDI: "किसी और की जानकारी हम कभी साझा नहीं करते, और आपके संदेश भी निजी रहते हैं।",
        _ENGLISH: "I never share anything about other people, and your messages stay private too.",
    },
    (_K.REFUSE, _V.MEDICAL): {
        _HINGLISH: (
            "Dawai ya beemari ke baare mein salah nahi de sakte. Kripya anganwadi didi, ASHA didi"
            " ya doctor se baat kijiye."
        ),
        _HINDI: (
            "दवाई या बीमारी के बारे में सलाह नहीं दे सकते। कृपया आंगनवाड़ी दीदी, आशा दीदी या "
            "डॉक्टर से बात कीजिए।"
        ),
        _ENGLISH: (
            "I can't advise on medicines or illness. Please talk to your anganwadi worker, ASHA "
            "didi or a doctor."
        ),
    },
    (_K.REFUSE, _V.GENERAL): {
        _HINGLISH: (
            "Is baare mein baat nahi kar sakte. Aaiye, bachche ki khoj aur seekhne ki baat karein."
        ),
        _HINDI: "इस बारे में बात नहीं कर सकते। आइए, बच्चे की खोज और सीखने की बात करें।",
        _ENGLISH: (
            "I can't talk about that. Let's talk about your child's discoveries and learning."
        ),
    },
    (_K.REFUSE, _V.GENERIC): {
        _HINGLISH: (
            "Is sawaal ka jawab abhi nahi de paaye. Kya aap ise thoda alag tareeke se pooch sakte"
            " hain?"
        ),
        _HINDI: "इस सवाल का जवाब अभी नहीं दे पाए। क्या आप इसे थोड़ा अलग तरीके से पूछ सकते हैं?",
        _ENGLISH: "I couldn't answer that just now. Could you ask it in a different way?",
    },
}

_VERSIONS: Final[dict[FixedReplyKind, str]] = {_K.REPEAT_PLEASE: "2"}  # all others "1"


def _spoken_language(language: Language) -> Language:
    return _HINDI if language is _HINGLISH else language


def _plain_texts() -> dict[FixedTextKey, FixedText]:
    built: dict[FixedTextKey, FixedText] = {}
    for (kind, variant), texts in _PLAIN_TEXTS.items():
        version = _VERSIONS.get(kind, "1")
        for language, text in texts.items():
            spoken = texts[_spoken_language(language)]
            built[FixedTextKey(kind, variant, language)] = FixedText(text, spoken, version)
    return built


def _crisis_texts() -> dict[FixedTextKey, FixedText]:
    built: dict[FixedTextKey, FixedText] = {}
    for (variant, language), crisis in CRISIS_TEXTS.items():
        spoken = CRISIS_TEXTS[(variant, _spoken_language(language))].spoken_text
        key = FixedTextKey(_K.CRISIS, variant, language)
        built[key] = FixedText(crisis.text, spoken, version=CRISIS_VERSION)
    return built


FIXED_TEXTS: Final[dict[FixedTextKey, FixedText]] = {**_plain_texts(), **_crisis_texts()}
