"""Braj: how to tell a Braj speaker, and how Marg speaks light Braj back (owner, 2026-10-28).

Braj Bhasha is the Hindi of the Mathura, Agra and Bharatpur area. Marg answers in light Braj when
the user writes in it, or lives in a Braj district; everyone else keeps standard Hindi or
Hinglish. The words below are matched whole, after PhraseFinder.normalise.

v1, written 2026-10-28 from common Braj forms: pending the owner's review with Braj speakers in
the village (wrong or stiff words get dropped; real everyday ones get added).
"""

from typing import Final

from app.domain.enums import Language

BRAJ_MARKERS: Final = (
    # Devanagari
    "मेरो", "तेरो", "वाको", "याको", "हमाओ", "तिहारो", "गयो", "आयो", "कियो", "जायगो",
    "करैगो", "नाय", "नाहीं", "हतो", "हती", "मोय", "तोय", "ह्यां", "ह्वां", "कहां ते",
    "का कर रए", "रए हो", "छोरा", "छोरी", "लली", "कछु", "देखतो", "करतो", "जातो", "वाकू",
    "बोलत", "करत", "खेलत", "देखत", "रह्यो", "वाय",
    # Roman
    "mero", "tero", "vako", "yako", "hamao", "tiharo", "gayo", "aayo", "kiyo", "jaayego",
    "jayego", "karaigo", "naay", "naay hai", "hato", "hati", "moy", "toy", "hyan", "hvan",
    "ka kar rae", "kar rae", "rae ho", "chhora", "chhori", "lali", "vaako", "waako", "vaaku",
    "kachhu", "kachu", "dekhto", "karto", "jaato", "aato", "bolat", "karat", "khelat", "dekhat",
    "rahyo", "vaay", "waay",
)  # fmt: skip
"""Forms a Braj speaker uses and a standard-Hindi speaker wouldn't. Two together count (one
alone, like "chhora", is common across north India)."""

BRAJ_DISTRICTS: Final = (
    "mathura", "agra", "bharatpur", "dholpur", "karauli", "aligarh", "hathras", "firozabad",
    "etah", "kasganj", "mainpuri", "deeg", "palwal", "मथुरा", "आगरा", "भरतपुर", "धौलपुर",
    "करौली", "अलीगढ़", "हाथरस", "फ़िरोज़ाबाद", "फिरोजाबाद", "एटा", "कासगंज", "मैनपुरी", "डीग",
)  # fmt: skip

BRAJ_RULE: Final[dict[Language, str]] = {
    Language.HINDI: (
        "This person speaks Braj (the Hindi of Mathura, Agra and Bharatpur). Write in light, easy "
        "Braj where it comes naturally: मेरो, तेरो, वाको; गयो, आयो, कियो; जायगो; नाय for no; "
        "हतो for was; छोरा, छोरी, लाला, लली for children. Keep every sentence clear to any "
        "Hindi speaker, and don't overdo it. Take examples from Braj village life: the chaupal, "
        "the kund or pokhar, cows and buffaloes, mustard and bajra fields, the temple bell."
    ),
    Language.HINGLISH: (
        "This person speaks Braj (the Hindi of Mathura, Agra and Bharatpur). Write in light, easy "
        "Braj where it comes naturally, in Roman script: mero, tero, vako; gayo, aayo, kiyo; "
        "jaayego; naay for no; hato for was; chhora, chhori, lala, lali for children. Keep every "
        "sentence clear to any Hindi speaker, and don't overdo it. Take examples from Braj "
        "village life: the chaupal, the kund or pokhar, cows and buffaloes, mustard and bajra "
        "fields, the temple bell."
    ),
}

VILLAGE_RULE: Final = (
    "Take examples from village life (fields and crops, cattle, the hand pump, the weekly haat, "
    "the chaupal, the school courtyard, festivals, cooking at home). Never assume a city, a car, "
    "a computer at home or money to spend."
)
