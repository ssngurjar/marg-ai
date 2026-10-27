"""Phrases a reply to a child must never contain (s07 d8, the d1 child rule; s10b §4.16).

Matched as whole words after PhraseFinder.normalise, in Hinglish, Hindi and English.
v1, written 2026-10-27: pending the owner's review (ideally a counsellor's too).
"""

from typing import Final

# d8: secrecy, exclusivity, attachment
CHILD_MANIPULATION_PHRASES: Final = (
    "secret", "our secret", "kisi ko mat batana", "kisi ko na batana", "mat batana",
    "mummy ko mat batana", "papa ko mat batana", "don't tell", "do not tell", "dont tell",
    "only i understand", "sirf main samajhta", "sirf main samajhti", "sirf mujhse",
    "best friend", "sabse achha dost", "sabse accha dost", "hamesha mujhse hi baat karna",
    "only talk to me", "राज़", "किसी को मत बताना", "मत बताना", "सिर्फ़ मैं समझता",
    "सिर्फ मैं समझता", "सबसे अच्छा दोस्त",
)  # fmt: skip

# d1, child rule: a question about any of these
CHILD_PERSONAL_TOPICS: Final = (
    "school", "schools", "address", "ghar kahan", "gaon ka naam", "village", "street", "gali",
    "phone", "phone number", "mobile", "photo", "picture", "full name", "poora naam", "pura naam",
    "surname", "papa ka naam", "mummy ka naam", "papa kya kaam", "mummy kya kaam",
    "father's name", "mother's name", "स्कूल", "पता", "गाँव का नाम", "फ़ोन", "फोन", "फ़ोन नंबर",
    "फ़ोटो", "फोटो", "पूरा नाम", "पापा का नाम", "मम्मी का नाम",
)  # fmt: skip
QUESTION_WORDS: Final = (
    "kya", "kaun", "kaunsa", "kaunsi", "kahan", "kitna", "what", "which", "where", "who",
    "क्या", "कौन", "कौनसा", "कहाँ", "कितना",
)  # fmt: skip
