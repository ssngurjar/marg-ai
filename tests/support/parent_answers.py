"""Model outputs for ParentAnswer in each register, valid for the layer's script check."""

from collections.abc import Mapping
from typing import Final

from app.domain.enums import Language

HINGLISH_ANSWER: Final[Mapping[str, object]] = {
    "answer": "Rang sikhane ke liye ghar ki cheezon se khel kheliye.",
    "try_this": "Aaj teen laal cheezein saath dhoondhiye.",
    "spoken_text": "रंग सिखाने के लिए घर की चीज़ों से खेल खेलिए। आज तीन लाल चीज़ें साथ ढूंढिए।",
}
HINDI_ANSWER: Final[Mapping[str, object]] = {
    "answer": "रंग सिखाने के लिए घर की चीज़ों से खेल खेलिए।",
    "try_this": "आज तीन लाल चीज़ें साथ ढूंढिए।",
    "spoken_text": "रंग सिखाने के लिए घर की चीज़ों से खेल खेलिए। आज तीन लाल चीज़ें साथ ढूंढिए।",
}
ENGLISH_ANSWER: Final[Mapping[str, object]] = {
    "answer": "Play colour games with things you already have at home.",
    "try_this": "Today, find three red things together.",
    "spoken_text": "Play colour games with things at home. Today, find three red things together.",
}
ANSWER_IN: Final[Mapping[Language, Mapping[str, object]]] = {
    Language.HINGLISH: HINGLISH_ANSWER,
    Language.HINDI: HINDI_ANSWER,
    Language.ENGLISH: ENGLISH_ANSWER,
}
