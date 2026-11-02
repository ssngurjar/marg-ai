"""OnboardingAnswerParser: what an onboarding answer says, without a model (s08 §4.4 step 4). Pure.

Short, common answers in Hindi, Hinglish and English are read here: yes/no, a role, a grade,
a child's age and nickname, a language name, deletion and add-child phrases. Anything these
rules can't read goes to the ProfileExtraction model call, and from there to "not understood".

Out-of-range values are reported, not repaired: "class 13" is OUT_OF_RANGE (the user is told
1-12), never grade 12.
"""

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum, auto
from typing import ClassVar, Final

from app.domain.enums import Language, Role
from app.domain.models.conversation import MIN_CHILDREN_IN_ONE_ANSWER
from app.domain.rules.phrase_finder import PhraseFinder


class Found(Enum):
    ABSENT = auto()
    OUT_OF_RANGE = auto()
    TOO_LONG = auto()
    LOOKS_LIKE_FULL_NAME = auto()


@dataclass(frozen=True, slots=True)
class GradeParse:
    grade: int | None
    problem: Found | None  # ABSENT or OUT_OF_RANGE when grade is None


@dataclass(frozen=True, slots=True)
class ChildAgeParse:
    birth_year: int | None
    problem: Found | None  # ABSENT or OUT_OF_RANGE when birth_year is None


@dataclass(frozen=True, slots=True)
class NicknameParse:
    nickname: str | None
    problem: Found | None  # ABSENT, TOO_LONG or LOOKS_LIKE_FULL_NAME when nickname is None


@dataclass(frozen=True, slots=True)
class ChildParse:
    birth_year: int
    nickname: str


@dataclass(frozen=True, slots=True)
class ChildrenParse:
    """Several children named in one answer ("Munni 5 aur Golu 7"), in the order given."""

    children: tuple[ChildParse, ...]  # two or more, when problem is None
    problem: Found | None  # OUT_OF_RANGE, TOO_LONG or LOOKS_LIKE_FULL_NAME for any one child


class OnboardingAnswerParser:
    GRADES: ClassVar[range] = range(1, 13)
    CHILD_AGES: ClassVar[range] = range(2, 20)
    NICKNAME_MAX_CHARS: ClassVar[int] = 20
    SHORT_ANSWER_WORDS: ClassVar[int] = 5  # yes/no and role words count only in short answers
    # A deletion request on its own may carry this many other words ("please", "ji", "abhi");
    # longer messages are read by the intent model (owner, 2026-11-01).
    DELETION_EXTRA_WORDS: ClassVar[int] = 2
    FULL_NAME_LATIN_WORDS: ClassVar[int] = 2  # "Priya Sharma": two capitalised words
    FULL_NAME_DEVANAGARI_WORDS: ClassVar[int] = 3
    FIRST_BIRTH_YEAR_NUMBER: ClassVar[int] = 1000  # a number this big is a year, not an age

    GREETINGS: ClassVar[frozenset[str]] = frozenset(
        {
            "hi", "hii", "hello", "helo", "hey", "namaste", "namaskar", "ram ram", "hi marg",
            "hello marg", "good morning", "नमस्ते", "नमस्कार", "हेलो", "हाय", "राम राम",
        }
    )  # fmt: skip
    YES: ClassVar[frozenset[str]] = frozenset(
        {
            "haan", "ha", "han", "haa", "haan ji", "ha ji", "ji", "ji haan", "yes", "ok", "okay",
            "theek hai", "thik hai", "sahi hai", "manzoor", "agree", "i agree", "हाँ", "हां",
            "जी", "जी हाँ", "ठीक है", "सहमत", "हाँ ठीक है",
        }
    )  # fmt: skip
    ACKNOWLEDGEMENTS: ClassVar[frozenset[str]] = frozenset(
        {
            "ok", "okay", "okk", "k", "haan", "ha", "han", "haa", "ji", "yes", "thanks",
            "thank", "you", "thanku", "dhanyavad", "dhanyawad", "shukriya", "theek", "thik",
            "hai", "accha", "acha", "achha", "hmm", "hm", "sure", "done", "fine",
            "हाँ", "हां", "जी", "ठीक", "है", "धन्यवाद", "शुक्रिया", "अच्छा", "ओके",
        }
    )  # fmt: skip
    BRAJ_QUESTION_WORDS: ClassVar[int] = 12
    BRAJ_NAMES: ClassVar[frozenset[str]] = frozenset(
        {"braj", "vraj", "brij", "brajbhasha", "ब्रज", "बृज", "व्रज"}
    )
    GRADUATE_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "graduate", "graduation", "graduated", "grad", "college", "ba", "bsc", "bcom", "btech",
            "ma", "msc", "mcom", "postgraduate", "pg", "degree", "स्नातक", "ग्रेजुएट", "ग्रेजुएशन",
            "कॉलेज", "कालेज",
        }
    )  # fmt: skip
    NO: ClassVar[frozenset[str]] = frozenset(
        {
            "nahi", "nahin", "nai", "no", "mat karo", "abhi nahi", "nahi chahiye", "नहीं", "नही",
            "मत करो", "अभी नहीं",
        }
    )  # fmt: skip
    ROLE_WORDS: ClassVar[dict[Role, frozenset[str]]] = {
        Role.STUDENT: frozenset(
            {"student", "vidyarthi", "padhta", "padhti", "chhatra", "विद्यार्थी", "छात्र"}
        ),
        Role.TEACHER: frozenset(
            {
                "teacher", "sir", "madam", "shikshak", "shikshika", "padhata", "padhati",
                "master", "masterji", "शिक्षक", "शिक्षिका", "अध्यापक", "टीचर",
            }
        ),
        Role.PARENT: frozenset(
            {
                "parent", "parents", "mummy", "mumy", "papa", "maa", "mata", "pita",
                "abhibhavak", "mother", "father", "mom", "dad", "माता", "पिता", "अभिभावक",
                "मम्मी", "पापा", "माँ", "माता पिता",
            }
        ),
    }  # fmt: skip
    LANGUAGE_NAMES: ClassVar[dict[str, Language]] = {
        "english": Language.ENGLISH,
        "angrezi": Language.ENGLISH,
        "इंग्लिश": Language.ENGLISH,
        "अंग्रेज़ी": Language.ENGLISH,
        # The script follows what was typed (owner, 2026-10-29): Roman "Hindi" → Hinglish
        "hindi": Language.HINGLISH,
        "hinglish": Language.HINGLISH,
        "हिंदी": Language.HINDI,
        "हिन्दी": Language.HINDI,
    }
    LANGUAGE_FILLER: ClassVar[frozenset[str]] = frozenset(
        {
            # the words around a language name in "Hindi mein baat karo", "talk to me in
            # English", "मुझसे हिंदी में बात कीजिए" (owner's demo, 2026-10-29: "Hindi pleasee")
            "in", "mein", "me", "mai", "main", "please", "pls", "plz", "kripya", "language",
            "bhasha", "baat", "karo", "kariye", "kijiye", "karein", "karna", "bolo", "boliye",
            "talk", "speak", "to", "reply", "jawab", "do", "dijiye", "chahiye", "mujhse", "humse",
            "hamse", "se", "ab", "now", "only", "sirf", "switch", "change", "i", "want", "prefer",
            "chahta", "chahti", "chahte", "hoon", "hu", "hun", "hai", "hain", "ji",
            "में", "मे", "भाषा", "बात", "करो", "कीजिए", "करिए", "बोलो", "बोलिए", "मुझसे", "हमसे",
            "से", "अब", "जवाब", "दीजिए", "दो", "चाहिए", "जी", "प्लीज़",
        }
    )  # fmt: skip
    DELETION_PHRASES: ClassVar[frozenset[str]] = frozenset(
        {
            "delete my data", "delete my account", "mera data hatao", "mera data delete karo",
            "data delete", "data delete karo", "mera data mita do", "consent wapas",
            "data hata do", "data hatao", "data mita do", "data mitao", "data delete kar do",
            "remove my data", "erase my data",
            "मेरा डेटा हटाओ", "डेटा डिलीट", "मेरा डेटा डिलीट करो", "मेरा डेटा मिटा दो",
            "डेटा हटा दो", "डेटा मिटा दो", "डेटा डिलीट कर दो",
        }
    )  # fmt: skip
    ADD_CHILD_PHRASES: ClassVar[frozenset[str]] = frozenset(
        {
            "doosre bachche ke liye", "dusre bachche ke liye", "ek aur bachcha", "ek aur bachchi",
            "add another child", "another child", "दूसरे बच्चे के लिए", "एक और बच्चा",
        }
    )  # fmt: skip
    # a new child, never "for the other child" (a khoj for one already added): with an age in
    # the same message, the child is added at once (second field test, 2026-11-02)
    NEW_CHILD_ANSWER_MAX_WORDS: ClassVar[int] = 5  # "Riya, 7", "hai Golu 4 saal ka"
    NEW_CHILD_PHRASES: ClassVar[frozenset[str]] = frozenset(
        {
            "add another child", "another child", "ek aur bachcha", "ek aur bachchi",
            "एक और बच्चा", "एक और बच्ची",
        }
    )  # fmt: skip
    _AGE_UNITS: ClassVar[frozenset[str]] = frozenset(
        {"saal", "sal", "saal ka", "years", "year", "yrs", "yr", "baras", "साल", "वर्ष", "बरस"}
    )
    # "6 mahine ka hai": a baby's age in months, not years (onboarding bank, 2026-11-01)
    MONTH_UNITS: ClassVar[frozenset[str]] = frozenset(
        {"mahine", "mahina", "mahino", "mahinon", "month", "months", "महीने", "महीना", "महीनों"}
    )
    _NUMBER_WORDS: ClassVar[dict[str, int]] = {
        "do": 2, "teen": 3, "chaar": 4, "char": 4, "paanch": 5, "panch": 5, "chhah": 6,
        "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "gyarah": 11,
        "barah": 12, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "पाच": 5, "छह": 6,
        "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12,
        "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "dhai": 2, "dhaai": 2, "ढाई": 2, "dedh": 1, "डेढ़": 1,
    }  # fmt: skip
    # "saadhe teen saal" is three and a half: the age counts whole years, so the word before the
    # number moves it by this much (critic review, 2026-11-01: "saadhe" was saved as a nickname)
    _FRACTION_WORDS: ClassVar[dict[str, int]] = {
        "saadhe": 0, "sadhe": 0, "saade": 0, "sade": 0, "sawa": 0, "sava": 0, "paune": -1,
        "pone": -1, "साढ़े": 0, "साढे": 0, "सवा": 0, "पौने": -1,
    }  # fmt: skip
    # Class numbers said as words, for the class question only ("do" alone is a verb elsewhere)
    _GRADE_NUMBER_WORDS: ClassVar[dict[str, int]] = {
        "ek": 1, "one": 1, "एक": 1, "do": 2, "teen": 3, "chaar": 4, "char": 4, "paanch": 5,
        "panch": 5, "chhah": 6, "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
        "gyarah": 11, "barah": 12, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6,
        "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12, "two": 2,
        "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12,
    }  # fmt: skip
    RANGE_JOINERS: ClassVar[frozenset[str]] = frozenset({"se", "to", "tak", "से", "तक"})
    _HINDI_ORDINALS: ClassVar[dict[str, int]] = {
        "पहली": 1, "दूसरी": 2, "तीसरी": 3, "चौथी": 4, "पाँचवीं": 5, "पांचवीं": 5, "छठी": 6,
        "सातवीं": 7, "आठवीं": 8, "नौवीं": 9, "दसवीं": 10, "ग्यारहवीं": 11, "बारहवीं": 12,
    }  # fmt: skip
    _NOT_A_NAME: ClassVar[frozenset[str]] = frozenset(
        {
            "beti", "beta", "bachcha", "bachchi", "bacha", "bachi", "ladka", "ladki", "son",
            "daughter", "child", "kid", "baby", "boy", "girl", "naam", "name", "hai", "he",
            "ka", "ki", "ke", "mera", "meri", "mere", "uska", "uski", "umar", "umr", "age",
            "old", "aur", "and", "is", "my", "his", "her", "ghar", "par", "pe", "se", "hum",
            "use", "usko", "bulate", "kehte", "the", "a", "of", "hoon", "hu", "aged", "abhi",
            "बेटी", "बेटा", "बच्चा", "बच्ची", "नाम", "है", "का", "की", "के", "मेरा", "मेरी",
            "उसका", "उसकी", "उम्र", "और", "घर", "पर", "हम", "उसे", "बुलाते", "कहते", "हूँ",
            # how parents spell "child" (owner's demo, 2026-11-01: "Mera baccha 6 saal ka hai"
            # saved the nickname "baccha")
            "baccha", "bacchi", "bacche", "bachha", "bachhi", "bachhe", "bachche", "bachcho",
            "bachon", "bacchon", "bachey", "bachchey", "बच्चे", "बच्चों", "लड़का", "लड़की",
            # several children in one answer (critic review D3, 2026-11-01)
            "hain", "betiyan", "betiyaan", "betiya", "bete", "ladke", "ladkiyan", "children",
            "kids", "daughters", "sons", "हैं", "बेटियाँ", "बेटियां", "बेटे",
        }
    )  # fmt: skip
    _NUMBER: ClassVar[re.Pattern[str]] = re.compile(r"\d+")
    # Where one child's part of an answer ends: "Munni 5 aur Golu 7", "Munni 5, Golu 7"
    _CHILD_SEPARATOR: ClassVar[re.Pattern[str]] = re.compile(
        r"\s*(?:[,;&]|\band\b|\baur\b|\bor\b|और|तथा)\s*", re.IGNORECASE
    )
    # "2 bachche hain", "do betiyan": how many children, never an age
    _CHILD_COUNT: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:\d+|do|teen|two|three|दो|तीन)\s+(?:bachche|bacche|bachhe|bachchey|betiyan|betiyaan"
        r"|betiya|bete|ladke|ladkiyan|children|kids|daughters|sons|बच्चे|बेटियाँ|बेटियां|बेटे)\b",
        re.IGNORECASE,
    )

    # --- whole-message checks ------------------------------------------------------------------

    @staticmethod
    def is_greeting(text: str) -> bool:
        """Only greeting words ("Hello ji!", "नमस्ते 🙏", "Hellooo"), or nothing readable."""
        words = PhraseFinder.words(text)
        if len(words) > OnboardingAnswerParser.SHORT_ANSWER_WORDS:
            return False
        return all(_known(word, _GREETING_WORDS) in _GREETING_WORDS for word in words)

    @staticmethod
    def asks_about_braj(text: str) -> bool:
        """Names Braj in a short message: "kya aap braj bhasha mein baat kar sakte ho", "Braj aati
        hai?" (owner's field test, 2026-11-01)."""
        words = PhraseFinder.words(text)
        return len(words) <= OnboardingAnswerParser.BRAJ_QUESTION_WORDS and bool(
            set(words) & _BRAJ_NAMES
        )

    @staticmethod
    def is_graduate(text: str) -> bool:
        """A student past class 12: "mai graduate hun", "graduation kar li", "college mein hoon",
        "BA final year" (owner's field test, 2026-11-01)."""
        words = set(PhraseFinder.words(text))
        return bool(words & _GRADUATE_WORDS)

    @staticmethod
    def is_acknowledgement(text: str) -> bool:
        """Only "ok", "haan", "thanks", "theek hai" and the like: a first message that says it
        heard something, never a question to keep (owner's field test, 2026-11-01: "Ok" after a
        deletion got "I've noted your question")."""
        words = PhraseFinder.words(text)
        if not words or len(words) > OnboardingAnswerParser.SHORT_ANSWER_WORDS:
            return False
        return all(word in _ACKNOWLEDGEMENT_WORDS for word in words)

    @staticmethod
    def yes_or_no(text: str) -> bool | None:
        """True for yes, False for no, None when the short answer is neither or both."""
        if len(PhraseFinder.words(text)) > OnboardingAnswerParser.SHORT_ANSWER_WORDS:
            return None
        said_yes = PhraseFinder.contains_any(text, OnboardingAnswerParser.YES)
        said_no = PhraseFinder.contains_any(text, OnboardingAnswerParser.NO)
        if said_yes == said_no:
            return None
        return said_yes

    @staticmethod
    def role_named(text: str) -> Role | None:
        """The one role a short answer names; None if none or more than one."""
        if len(PhraseFinder.words(text)) > OnboardingAnswerParser.SHORT_ANSWER_WORDS:
            return None
        named = [
            role
            for role, words in OnboardingAnswerParser.ROLE_WORDS.items()
            if PhraseFinder.contains_any(text, words)
        ]
        return named[0] if len(named) == 1 else None

    @staticmethod
    def language_named(text: str) -> Language | None:
        """A message that only asks for a language ("english", "हिंदी mein", "Hindi pleasee",
        "talk to me in English"), else None."""
        return _language_only(text, _LANGUAGE_FILLER)

    @staticmethod
    def language_requested(text: str) -> Language | None:
        """A first message that only greets and names a language ("Hi Marg, English please",
        "नमस्ते, हिंदी में"), else None: the reply's language, with no question to keep."""
        return _language_only(text, _LANGUAGE_FILLER | _GREETING_WORDS)

    @staticmethod
    def asks_for_deletion(text: str) -> bool:
        return PhraseFinder.contains_any(text, OnboardingAnswerParser.DELETION_PHRASES)

    @staticmethod
    def asks_only_for_deletion(text: str) -> bool:
        """A deletion phrase with at most DELETION_EXTRA_WORDS other words: "mera data hatao",
        "please delete my data". Not "phone ka data delete ho gaya, khoj phir se bhejo"."""
        matched = [
            phrase
            for phrase in OnboardingAnswerParser.DELETION_PHRASES
            if PhraseFinder.contains_any(text, [phrase])
        ]
        if not matched:
            return False
        longest = max(len(PhraseFinder.words(phrase)) for phrase in matched)
        extra_words = len(PhraseFinder.words(text)) - longest
        return extra_words <= OnboardingAnswerParser.DELETION_EXTRA_WORDS

    @staticmethod
    def asks_to_add_child(text: str) -> bool:
        return PhraseFinder.contains_any(text, OnboardingAnswerParser.ADD_CHILD_PHRASES)

    @staticmethod
    def adds_a_child_with_age(text: str) -> bool:
        """ "Another child, Riya 7": a new child and an age in one message, and nothing else
        ("my son, 6, keeps hitting another child" is a worry, not a request)."""
        if not PhraseFinder.contains_any(text, OnboardingAnswerParser.NEW_CHILD_PHRASES):
            return False
        rest = OnboardingAnswerParser.without_new_child_phrase(text)
        if len(PhraseFinder.words(rest)) > OnboardingAnswerParser.NEW_CHILD_ANSWER_MAX_WORDS:
            return False
        return bool(
            OnboardingAnswerParser._numbers(rest) or OnboardingAnswerParser._spelled_ages(rest)
        )

    @staticmethod
    def without_new_child_phrase(text: str) -> str:
        """The message with "another child" (or its Hindi forms) taken out: the child's answer."""
        rest = text
        for phrase in sorted(OnboardingAnswerParser.NEW_CHILD_PHRASES, key=len, reverse=True):
            pattern = (
                r"(?<!\w)" + r"\s+".join(re.escape(word) for word in phrase.split()) + r"(?!\w)"
            )
            rest = re.sub(pattern, " ", rest, flags=re.IGNORECASE)
        return " ".join(rest.split())

    # --- values ------------------------------------------------------------------------------

    @staticmethod
    def parse_grade(text: str) -> GradeParse:
        """A class: "8", "class 8", "आठवीं", "आठ", "kaksha das". A range a teacher teaches ("2 se
        9", "दो से आठ", "6-8") is its highest class (owner's field test, 2026-11-02: a range in
        Hindi words wasn't understood, and one in digits was stored as its first class)."""
        words = PhraseFinder.words(text)
        for word in words:
            ordinal = _ORDINALS.get(word)
            if ordinal is not None:
                return GradeParse(ordinal, None)
        highest = OnboardingAnswerParser._range_top(text)
        if highest is not None:
            if highest not in OnboardingAnswerParser.GRADES:
                return GradeParse(None, Found.OUT_OF_RANGE)
            return GradeParse(highest, None)
        numbers = OnboardingAnswerParser._numbers(text) or [
            _GRADE_WORDS[word] for word in words if word in _GRADE_WORDS
        ]
        if not numbers:
            return GradeParse(None, Found.ABSENT)
        grade = numbers[0]
        if grade not in OnboardingAnswerParser.GRADES:
            return GradeParse(None, Found.OUT_OF_RANGE)
        return GradeParse(grade, None)

    @staticmethod
    def names_a_class_range(text: str) -> bool:
        return OnboardingAnswerParser._range_top(text) is not None

    @staticmethod
    def _range_top(text: str) -> int | None:
        """The higher end of "2 se 9", "दो से आठ", "6-8", "6 to 8"; None when it isn't a range."""
        spaced = text.replace("-", " - ").replace(_EN_DASH, " - ")
        tokens = PhraseFinder.words(spaced) if "-" not in spaced else spaced.casefold().split()
        values: list[int | None] = []
        for token in tokens:
            digits = OnboardingAnswerParser._numbers(token)
            values.append(digits[0] if digits else _GRADE_WORDS.get(PhraseFinder.normalise(token)))
        for index in range(1, len(tokens) - 1):
            low, high = values[index - 1], values[index + 1]
            joined = PhraseFinder.normalise(tokens[index]) in _RANGE_JOINERS or tokens[index] == "-"
            if joined and low is not None and high is not None and low < high:
                return high
        return None

    @staticmethod
    def parse_child_age(text: str, current_year: int) -> ChildAgeParse:
        """An age ("5 saal", "paanch saal", "पाँच साल", a bare number) or a birth year. An age
        given only in months ("6 mahine") is under two: out of range."""
        said = set(PhraseFinder.words(text))
        in_months = bool(said & _MONTH_UNITS) and not said & _AGE_UNITS
        if in_months:
            return ChildAgeParse(None, Found.OUT_OF_RANGE)
        numbers = OnboardingAnswerParser._numbers(text)
        for number in numbers:
            if number >= OnboardingAnswerParser.FIRST_BIRTH_YEAR_NUMBER:
                age = current_year - number
                if age in OnboardingAnswerParser.CHILD_AGES:
                    return ChildAgeParse(number, None)
                return ChildAgeParse(None, Found.OUT_OF_RANGE)
        ages = numbers or OnboardingAnswerParser._spelled_ages(text)
        if not ages:
            return ChildAgeParse(None, Found.ABSENT)
        age = ages[0]
        if age not in OnboardingAnswerParser.CHILD_AGES:
            return ChildAgeParse(None, Found.OUT_OF_RANGE)
        return ChildAgeParse(current_year - age, None)

    @staticmethod
    def parse_nickname(text: str) -> NicknameParse:
        """The short home name left after ages, numbers and relation words are taken out."""
        candidates: list[str] = []
        for token in re.split(r"[\s,.;:!?।()\-]+", unicodedata.normalize("NFC", text)):
            word = token.strip("'\"\u201c\u201d\u2018\u2019")  # straight and curly quotes
            if not word or any(character.isdigit() for character in word):
                continue
            normalised = PhraseFinder.normalise(word)
            if not normalised or not any(character.isalpha() for character in normalised):
                continue
            if (
                normalised in _NOT_A_NAME
                or normalised in _AGE_UNITS
                or normalised in _MONTH_UNITS
                or normalised in _NUMBERS
                or normalised in _FRACTIONS
            ):
                continue
            candidates.append(word)
        if not candidates:
            return NicknameParse(None, Found.ABSENT)
        capitalised_latin = [word for word in candidates if word[0].isascii() and word[0].isupper()]
        devanagari = [word for word in candidates if not word[0].isascii()]
        if (
            len(capitalised_latin) >= OnboardingAnswerParser.FULL_NAME_LATIN_WORDS
            or len(devanagari) >= OnboardingAnswerParser.FULL_NAME_DEVANAGARI_WORDS
        ):
            return NicknameParse(None, Found.LOOKS_LIKE_FULL_NAME)
        nickname = " ".join(candidates)
        if len(nickname) > OnboardingAnswerParser.NICKNAME_MAX_CHARS:
            return NicknameParse(None, Found.TOO_LONG)
        return NicknameParse(nickname, None)

    @staticmethod
    def parse_children(text: str, current_year: int) -> ChildrenParse | None:
        """Two or more children, each with one home name and an age ("Munni 5 aur Golu 7",
        "मुन्नी 5 साल, गोलू 7 साल"); None when the answer isn't that, and the one-child rules
        read it. A part without an age belongs to the child before it ("Munni 5 saal ki hai aur
        class 1 mein hai" stays one child: "class mein" is no home name)."""
        without_counts = OnboardingAnswerParser._CHILD_COUNT.sub(" ", text)
        parts: list[str] = []
        waiting: list[str] = []
        for segment in OnboardingAnswerParser._CHILD_SEPARATOR.split(without_counts):
            waiting.append(segment)
            age = OnboardingAnswerParser.parse_child_age(segment, current_year)
            if age.problem is not Found.ABSENT:  # an age, in range or not, ends a child's part
                parts.append(" ".join(waiting))
                waiting = []
        if len(parts) < MIN_CHILDREN_IN_ONE_ANSWER:
            return None
        if waiting:
            parts[-1] = " ".join([parts[-1], *waiting])
        children: list[ChildParse] = []
        for part in parts:
            nickname = OnboardingAnswerParser.parse_nickname(part)
            if nickname.problem in {Found.TOO_LONG, Found.LOOKS_LIKE_FULL_NAME}:
                return ChildrenParse((), nickname.problem)
            if nickname.nickname is None or len(nickname.nickname.split()) > 1:
                return None
            age = OnboardingAnswerParser.parse_child_age(part, current_year)
            if age.birth_year is None:
                return ChildrenParse((), Found.OUT_OF_RANGE)
            children.append(ChildParse(age.birth_year, nickname.nickname))
        return ChildrenParse(tuple(children), None)

    @staticmethod
    def _numbers(text: str) -> list[int]:
        """Every run of digits, Devanagari digits included, in order."""
        ascii_digits = "".join(
            str(unicodedata.digit(character)) if character.isdigit() else character
            for character in text
        )
        return [int(match) for match in OnboardingAnswerParser._NUMBER.findall(ascii_digits)]

    @staticmethod
    def _spelled_ages(text: str) -> list[int]:
        """Number words followed by an age unit ("paanch saal", "paune chaar saal" is 3): a bare
        "do" is just a verb."""
        words = PhraseFinder.words(text)
        ages: list[int] = []
        for index, word in enumerate(words[:-1]):
            number = _NUMBERS.get(word)
            if number is None or words[index + 1] not in _AGE_UNITS:
                continue
            word_before = words[index - 1] if index > 0 else ""
            ages.append(number + _FRACTIONS.get(word_before, 0))
        return ages


def _normalised_set(words: frozenset[str]) -> frozenset[str]:
    return frozenset(PhraseFinder.normalise(word) for word in words)


def _normalised_keys(numbers: dict[str, int]) -> dict[str, int]:
    return {PhraseFinder.normalise(word): value for word, value in numbers.items()}


# Vocabulary as PhraseFinder.words sees it (nasal marks and nukta dropped: पाँच → पाच).
_NUMBERS: Final = _normalised_keys(OnboardingAnswerParser._NUMBER_WORDS)
_ORDINALS: Final = _normalised_keys(OnboardingAnswerParser._HINDI_ORDINALS)
_GRADE_WORDS: Final = _normalised_keys(OnboardingAnswerParser._GRADE_NUMBER_WORDS)
_RANGE_JOINERS: Final = _normalised_set(OnboardingAnswerParser.RANGE_JOINERS)
_EN_DASH: Final = "\u2013"  # an en dash between two classes, as phone keyboards often type it
_FRACTIONS: Final = _normalised_keys(OnboardingAnswerParser._FRACTION_WORDS)
_NOT_A_NAME: Final = _normalised_set(OnboardingAnswerParser._NOT_A_NAME)
_AGE_UNITS: Final = _normalised_set(OnboardingAnswerParser._AGE_UNITS)
_MONTH_UNITS: Final = _normalised_set(OnboardingAnswerParser.MONTH_UNITS)
_ACKNOWLEDGEMENT_WORDS: Final = _normalised_set(OnboardingAnswerParser.ACKNOWLEDGEMENTS)
_GRADUATE_WORDS: Final = _normalised_set(OnboardingAnswerParser.GRADUATE_WORDS)
_BRAJ_NAMES: Final = _normalised_set(OnboardingAnswerParser.BRAJ_NAMES)
_GREETING_WORDS: Final = frozenset(
    word
    for greeting in (*OnboardingAnswerParser.GREETINGS, "ji", "sir", "madam", "marg", "जी")
    for word in PhraseFinder.words(greeting)
)
_LANGUAGE_NAMES: Final = {
    PhraseFinder.normalise(name): language
    for name, language in OnboardingAnswerParser.LANGUAGE_NAMES.items()
}
_LANGUAGE_FILLER: Final = _normalised_set(OnboardingAnswerParser.LANGUAGE_FILLER)
_REPEATED_LETTER: Final = re.compile(r"(.)\1+")


def _known(word: str, vocabulary: Collection[str]) -> str:
    """`word` as the vocabulary spells it when only stretched ("pleasee", "Hindii",
    "hellooo"): repeated letters squeezed to one, then to two; else `word` unchanged."""
    if word in vocabulary:
        return word
    for squeezed in (_REPEATED_LETTER.sub(r"\1", word), _REPEATED_LETTER.sub(r"\1\1", word)):
        if squeezed in vocabulary:
            return squeezed
    return word


def _language_only(text: str, allowed: Collection[str]) -> Language | None:
    """The one language `text` names when every other word is in `allowed`, else None."""
    vocabulary = set(_LANGUAGE_NAMES) | set(allowed)
    words = [_known(word, vocabulary) for word in PhraseFinder.words(text)]
    named = [_LANGUAGE_NAMES[word] for word in words if word in _LANGUAGE_NAMES]
    others = [word for word in words if word not in _LANGUAGE_NAMES and word not in allowed]
    if len(named) == 1 and not others:
        return named[0]
    return None
