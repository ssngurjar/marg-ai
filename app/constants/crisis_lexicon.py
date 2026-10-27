"""Crisis phrase lists (s07 §4.5 rule 1): the check that works when every provider is down.

Recall first, except that siblings and cousins are left out of the people list: "bada bhai
chhote ko maarta hai" is an everyday parenting question, and the Muse Spark check still sees it.
Every phrase is reviewed by the owner (and ideally a counsellor or teacher, s07 Q2)
before it ships; add each miss found in testing. crisis-004 ("exam ka bahut tension hai") must
never match. Spellings are matched after CrisisPhraseMatcher.normalise, so case, punctuation,
nukta and nasal marks don't matter; Roman spelling variants are listed explicitly.

v1, written 2026-10-27: pending the owner's review.
"""

from typing import Final

from app.domain.models.safety import CrisisLexicon

_SELF_HARM: Final = (
    # English
    "kill myself", "killing myself", "end my life", "take my own life", "want to die",
    "wanna die", "don't want to live", "dont want to live", "do not want to live",
    "don't feel like living", "dont feel like living", "no will to live",
    "no reason to live", "not worth living", "better off without me", "better off dead",
    "hurt myself", "cut myself", "cutting myself", "suicide", "suicidal", "end it all",
    # Hinglish
    "jeene ka mann nahi", "jeene ka man nahi", "jine ka man nahi", "jeena nahi chahta",
    "jeena nahi chahti", "jeena nahi chahte", "marna chahta", "marna chahti", "marna chahte",
    "mar jaana chahta", "mar jaana chahti", "mar jana chahta", "mar jana chahti",
    "khudkushi", "khudkhushi", "aatmhatya", "atmahatya", "aatmahatya", "khud ko khatam",
    "zindagi khatam", "jindagi khatam", "sab khatam karna", "jaan de dunga", "jaan de dungi",
    "khud ko nuksan", "khud ko nuksaan", "mere bina sab behtar",
    # Hindi
    "जीने का मन नहीं", "जीना नहीं चाहता", "जीना नहीं चाहती", "मरना चाहता", "मरना चाहती",
    "मर जाना चाहता", "मर जाना चाहती", "आत्महत्या", "खुदकुशी", "खुद को खत्म", "ज़िंदगी खत्म",
    "जिंदगी खत्म", "सब खत्म करना", "जान दे दूंगा", "जान दे दूंगी", "खुद को नुकसान",
    "मेरे बिना सब बेहतर",
)  # fmt: skip

_ABUSE_PEOPLE: Final = (
    # English
    "uncle", "aunt", "father", "dad", "stepfather", "stepmother", "mother", "mom",
    "relative", "teacher", "sir", "neighbour", "neighbor", "husband",
    # Hinglish
    "chacha", "chachu", "mama", "mamaji", "tau", "tauji", "fufa", "papa", "pitaji", "mummy",
    "rishtedar", "padosi", "masterji", "master", "sasur", "pati",
    # Hindi
    "चाचा", "मामा", "ताऊ", "फूफा", "पापा", "पिता", "पिताजी", "मम्मी",
    "रिश्तेदार", "पड़ोसी", "टीचर", "मास्टर", "मास्टरजी", "सर", "ससुर", "पति",
)  # fmt: skip

_ABUSE_HARMS: Final = (
    # English
    "beats me", "beat me", "beats her", "beats him", "hits me", "hit me", "hurts me",
    "touches me", "touched me", "touches her", "touches him", "abuses me", "abused me",
    "locks me", "burns me", "slaps me",
    # Hinglish
    "maarte", "maarta", "maarti", "maara", "maari", "marte hain", "marta hai", "peet",
    "peette", "peetta",
    "pitai", "pitaai", "chhoote", "chhuta", "chhoota", "chhute", "galat tarike se",
    "gandi harkat", "jalate", "band kar dete",
    # Hindi
    "मारते", "मारता", "मारती", "मारा", "मारी", "पीटते", "पीटता", "पिटाई", "छूते", "छूता", "छुआ",
    "गलत तरीके से", "गंदी हरकत", "जलाते", "बंद कर देते",
)  # fmt: skip

CRISIS_LEXICON: Final = CrisisLexicon(
    version="1",
    self_harm_phrases=_SELF_HARM,
    abuse_people=_ABUSE_PEOPLE,
    abuse_harms=_ABUSE_HARMS,
    abuse_window_tokens=6,
)
