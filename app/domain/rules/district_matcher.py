"""DistrictMatcher: which LGD district a typed answer names (critic review D4, 2026-11-01). Pure.

Only an exact name (in English, or LGD's Devanagari name) is taken as sure. A close spelling, a
name typed in Hindi script that sounds like an English one ("बहराइच" → Bahraich), or the first
word of a longer name ("Bengaluru" → Bengaluru Urban / Rural / South) comes back as up to three
candidates for the person to confirm. A state named alone ("Delhi") says so, so Marg can ask
which district. Nothing found is said plainly; what to do then is the caller's rule.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Final

from app.domain.models.district import LgdDistrict


@dataclass(frozen=True, slots=True)
class DistrictMatch:
    found: LgdDistrict | None  # one district, named exactly
    candidates: tuple[LgdDistrict, ...]  # up to MAX_CANDIDATES to confirm, when not sure
    state_named: str | None  # only a state named, with too many districts to offer

    @property
    def is_empty(self) -> bool:
        return self.found is None and not self.candidates and self.state_named is None


NOTHING = DistrictMatch(None, (), None)


class DistrictMatcher:
    MAX_CANDIDATES: ClassVar[int] = 3  # WhatsApp shows at most three buttons
    SHORTEST_PREFIX: ClassVar[int] = 4  # "Bengaluru" offers its districts; "Ban" offers none
    SHORT_SKELETON: ClassVar[int] = 4  # below this, a skeleton must match exactly
    # Words around a district name in an answer ("mera zila Barmer hai", "district Sitapur, UP")
    FILLER: ClassVar[frozenset[str]] = frozenset(
        {
            "district", "distt", "dist", "zila", "jila", "zilla", "jilla", "zile", "jile",
            "zilay", "janpad", "mera",
            "meri", "mere", "hamara", "hai", "hain", "se", "hoon", "hun", "hu", "main", "mai",
            "me", "mein", "in", "my", "is", "from", "the", "ka", "ki", "ke", "i", "am", "live",
            "rehta", "rehti", "rahta", "rahti", "state", "जिला", "ज़िला", "जिले", "ज़िले", "जनपद",
            "मेरा", "मैं", "है",
            "से", "में", "हूँ", "हूं", "का", "की", "के", "हमारा",
        }
    )  # fmt: skip
    # How a Devanagari letter sounds in Roman letters, for the skeleton (vowels are dropped)
    _DEVANAGARI_SOUNDS: ClassVar[dict[str, str]] = {
        "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j",
        "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t",
        "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh",
        "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s",
        "ह": "h", "ं": "n", "ँ": "n",
    }  # fmt: skip
    # Devanagari vowel signs aren't \w: they are kept, or "से" would shrink to "स"
    _DEVANAGARI_VOWELS: ClassVar[dict[str, str]] = {
        "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ए": "e", "ऐ": "a",
        "ओ": "o", "औ": "a",
    }  # fmt: skip
    _NOT_A_LETTER: ClassVar[re.Pattern[str]] = re.compile(r"[^\w\s\u0900-\u097f]")

    @staticmethod
    def match(text: str, districts: Sequence[LgdDistrict]) -> DistrictMatch:
        words = DistrictMatcher._words(text)
        if not words:
            return NOTHING
        whole = DistrictMatcher._exact(" ".join(words), districts)
        if whole is not None:
            return whole
        state, rest = DistrictMatcher._state_and_rest(words, districts)
        in_state = [district for district in districts if state in {None, district.state}]
        query = " ".join(rest)
        if not query:
            return DistrictMatcher._state_only(state, in_state)
        return (
            DistrictMatcher._exact(query, in_state)
            or DistrictMatcher._first_word(query, in_state)
            or DistrictMatcher._close_spelling(query, in_state)
            or DistrictMatcher._same_sound(query, in_state)
            or NOTHING
        )

    # --- the steps, in order -------------------------------------------------------------------

    @staticmethod
    def _exact(query: str, districts: Sequence[LgdDistrict]) -> DistrictMatch | None:
        squeezed = query.replace(" ", "")
        named = [
            district
            for district in districts
            if DistrictMatcher._key(district.name).replace(" ", "") == squeezed
            or (
                district.local_name is not None
                and DistrictMatcher._normalise(district.local_name).replace(" ", "") == squeezed
            )
        ]
        return DistrictMatcher._as_match(named)

    @staticmethod
    def _state_and_rest(
        words: list[str], districts: Sequence[LgdDistrict]
    ) -> tuple[str | None, list[str]]:
        """The state the answer names, if any, and the words left without it."""
        states = sorted({district.state for district in districts}, key=len, reverse=True)
        for state in states:
            state_words = DistrictMatcher._key(state).split()
            for start in range(len(words) - len(state_words) + 1):
                if words[start : start + len(state_words)] == state_words:
                    rest = words[:start] + words[start + len(state_words) :]
                    return state, rest
        return None, words

    @staticmethod
    def _state_only(state: str | None, in_state: Sequence[LgdDistrict]) -> DistrictMatch:
        if state is None:
            return NOTHING
        if len(in_state) <= DistrictMatcher.MAX_CANDIDATES:
            return DistrictMatch(None, tuple(in_state), None)
        return DistrictMatch(None, (), state)

    @staticmethod
    def _first_word(query: str, districts: Sequence[LgdDistrict]) -> DistrictMatch | None:
        """ "Bengaluru" → Bengaluru Urban, Bengaluru Rural, Bengaluru South: never sure."""
        if len(query) < DistrictMatcher.SHORTEST_PREFIX:
            return None
        starting = [
            district
            for district in districts
            if DistrictMatcher._key(district.name).startswith(f"{query} ")
        ]
        if not starting:
            return None
        return DistrictMatch(None, tuple(starting[: DistrictMatcher.MAX_CANDIDATES]), None)

    @staticmethod
    def _close_spelling(query: str, districts: Sequence[LgdDistrict]) -> DistrictMatch | None:
        """Names a few letters away ("Karoli" → Karauli), closest first."""
        allowed = DistrictMatcher._allowed_typos(query)
        scored: list[tuple[int, LgdDistrict]] = []
        for district in districts:
            name = DistrictMatcher._key(district.name)
            if name[:1] != query[:1]:
                continue  # a typo rarely changes the first letter ("Gurgaon" is not "Marigaon")
            distance = DistrictMatcher.edit_distance(query, name)
            if distance <= allowed:
                scored.append((distance, district))
        return DistrictMatcher._closest(scored, query)

    @staticmethod
    def _same_sound(query: str, districts: Sequence[LgdDistrict]) -> DistrictMatch | None:
        """Consonants only, in Roman letters: "बहराइच" and "Behraich" both sound like
        Bahraich. Exact for short names, one sound off for longer ones."""
        heard = DistrictMatcher.skeleton(query)
        if not heard:
            return None
        allowed = 0 if len(heard) < DistrictMatcher.SHORT_SKELETON else 1
        scored: list[tuple[int, LgdDistrict]] = []
        for district in districts:
            sounds = DistrictMatcher.skeleton(district.name)
            if sounds[:1] != heard[:1]:
                continue
            distance = DistrictMatcher.edit_distance(heard, sounds)
            if distance <= allowed:
                scored.append((distance, district))
        nearest = min((distance for distance, _ in scored), default=0)
        return DistrictMatcher._closest([pair for pair in scored if pair[0] == nearest], query)

    # --- helpers ---------------------------------------------------------------------------------

    @staticmethod
    def _as_match(named: Sequence[LgdDistrict]) -> DistrictMatch | None:
        """One: sure. Two or more (the same name in two states): confirm. None: no match."""
        if len(named) == 1:
            return DistrictMatch(named[0], (), None)
        if named:
            return DistrictMatch(None, tuple(named[: DistrictMatcher.MAX_CANDIDATES]), None)
        return None

    @staticmethod
    def _closest(scored: list[tuple[int, LgdDistrict]], said: str) -> DistrictMatch | None:
        """Fewest changes first; among equals, a name that starts with the sound said first
        ("उदयपुर" → Udaipur before Dholpur)."""
        if not scored:
            return None
        initial = DistrictMatcher._first_sound(said)
        scored.sort(
            key=lambda pair: (
                pair[0],
                not pair[1].name.casefold().startswith(initial),
                pair[1].name,
            )
        )
        closest = tuple(district for _, district in scored[: DistrictMatcher.MAX_CANDIDATES])
        return DistrictMatch(None, closest, None)

    @staticmethod
    def _first_sound(said: str) -> str:
        """The first letter said, in Roman letters: "u" for "उदयपुर", "k" for "करौली"."""
        first = said[:1]
        if "a" <= first <= "z":
            return first
        return DistrictMatcher._DEVANAGARI_VOWELS.get(
            first, DistrictMatcher._DEVANAGARI_SOUNDS.get(first, "")
        )[:1]

    @staticmethod
    def _allowed_typos(query: str) -> int:
        short, medium = 5, 10
        if len(query) <= short:
            return 1
        return 2 if len(query) <= medium else 3

    @staticmethod
    def _words(text: str) -> list[str]:
        """The words that can name a place: filler dropped, from answers and names alike ("The
        Nilgiris" is matched as "nilgiris")."""
        words = DistrictMatcher._normalise(text).split()
        return [word for word in words if word not in _FILLER]

    @staticmethod
    def _key(name: str) -> str:
        return " ".join(DistrictMatcher._words(name))

    @staticmethod
    def _normalise(text: str) -> str:
        """Lower case, no punctuation, no nukta (ड़ and ढ़ sound as र); Devanagari kept."""
        composed = unicodedata.normalize("NFC", text).casefold()
        composed = composed.replace("\u0921\u093c", "र").replace("\u0922\u093c", "र")
        composed = composed.replace("\u093c", "")
        return " ".join(DistrictMatcher._NOT_A_LETTER.sub(" ", composed).split())

    @staticmethod
    def skeleton(text: str) -> str:
        """The consonants of a name in Roman letters, h and repeats dropped: "Jhunjhunu" and
        "झुंझुनूं" are both "jnjn"."""
        decomposed = unicodedata.normalize("NFD", text.casefold())
        decomposed = decomposed.replace("ड़", "r").replace("ढ़", "r")
        sounds: list[str] = []
        for letter in decomposed:
            if letter in DistrictMatcher._DEVANAGARI_SOUNDS:
                sounds.append(DistrictMatcher._DEVANAGARI_SOUNDS[letter])
            elif "a" <= letter <= "z":
                sounds.append(letter)
        roman = "".join(sounds).replace("ck", "k").replace("ow", "o")
        roman = roman.replace("w", "v").replace("q", "k").replace("z", "j")
        # y goes too: "उदयपुर" has a य where "Udaipur" has a vowel
        consonants = [letter for letter in roman if letter not in "aeiouhy"]
        collapsed: list[str] = []
        for letter in consonants:
            if not collapsed or collapsed[-1] != letter:
                collapsed.append(letter)
        return "".join(collapsed)

    @staticmethod
    def edit_distance(first: str, second: str) -> int:
        """Letters to add, drop or change to turn one into the other (Levenshtein)."""
        previous_row = list(range(len(second) + 1))
        for row, first_letter in enumerate(first, start=1):
            current_row = [row]
            for column, second_letter in enumerate(second, start=1):
                substitution = previous_row[column - 1] + (first_letter != second_letter)
                current_row.append(
                    min(previous_row[column] + 1, current_row[column - 1] + 1, substitution)
                )
            previous_row = current_row
        return previous_row[-1]


_FILLER: Final = frozenset(DistrictMatcher._normalise(word) for word in DistrictMatcher.FILLER)
