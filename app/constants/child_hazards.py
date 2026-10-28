"""The d7 child-hazard words (s10b §4.10, s07 §4.5), per hazard on content/activities/_hazards.yaml.

An activity step that mentions a hazard the activity didn't declare is blocked. Matched
as whole words after PhraseFinder.normalise. Bare "well" is left out on purpose: in English it's
mostly an adverb ("mix it well"); the water well is caught as "kuan", "village well" and so on.

An answer may name or explain a hazard (TALKABLE_HAZARDS); an activity may never involve one,
except a child-safe tool with a grown-up (CHILD_SAFE_TOOL_PHRASES).

v1, written 2026-10-27: pending the owner's review.
"""

from typing import Final

CHILD_HAZARD_WORDS: Final[dict[str, tuple[str, ...]]] = {
    "water_body": (
        "pond", "river", "lake", "canal", "village well", "water well", "water tank", "talab",
        "taalab", "kuan", "kuaan", "nadi", "nahar", "jheel", "तालाब", "कुआँ", "कुआं", "नदी",
        "नहर", "झील",
    ),
    "fire": (
        "fire", "flame", "flames", "matchstick", "matches", "stove", "candle", "chulha", "aag",
        "maachis", "machis", "diya", "आग", "चूल्हा", "माचिस", "मोमबत्ती", "दीया", "दिया जलाओ",
    ),
    "sharp_tool": (
        "knife", "blade", "sickle", "scissors", "axe", "chaku", "chaaku", "hasiya", "daranti",
        "kainchi", "kulhadi", "चाकू", "हँसिया", "दरांती", "कैंची", "ब्लेड", "कुल्हाड़ी",
    ),
    "electricity": (
        "electric", "electricity", "wire", "socket", "plug", "switchboard", "bijli", "taar",
        "बिजली", "तार", "सॉकेट",
    ),
    "road": ("road", "traffic", "highway", "sadak", "सड़क", "हाईवे"),
    "height": (
        "climb", "climbing", "roof", "rooftop", "terrace", "ladder", "chhat", "seedhi",
        "chadho", "छत", "सीढ़ी", "चढ़ो", "चढ़ना",
    ),
    "wild_animal": (
        "snake", "scorpion", "stray dog", "bee hive", "saanp", "sanp", "bichhoo", "bichhu",
        "सांप", "साँप", "बिच्छू",
    ),
    "unknown_plant": (
        "berries", "wild fruit", "mushroom", "mushrooms", "jangli phal", "जंगली फल",
    ),
    "medicine": (
        "medicine", "tablet", "syrup", "dawai", "dawa", "goli", "दवाई", "दवा", "गोली",
    ),
}  # fmt: skip

NEVER_TALK_ABOUT: Final = frozenset({"medicine"})
"""Hazards no answer discusses (owner, 2026-10-28): medicine questions go to the anganwadi
worker, the ASHA didi or a doctor."""

TALKABLE_HAZARDS: Final = frozenset(CHILD_HAZARD_WORDS) - NEVER_TALK_ABOUT
"""Hazards an answer may name or explain, asked about or not, when they make the best example
(owner, 2026-10-28: "the sickle's thin edge", "fire needs air"). Talked about, never done: the
activity part of a reply is still checked against every hazard word."""

CHILD_SAFE_TOOL_PHRASES: Final[tuple[str, ...]] = (
    "round-tip scissors", "rounded scissors", "child-safe scissors",
    "children's scissors", "gol nok wali kainchi", "gol nok ki kainchi", "bachchon wali kainchi",
    "bachchon ki kainchi", "गोल नोक वाली कैंची", "गोल नोक की कैंची", "बच्चों वाली कैंची",
    "बच्चों की कैंची",
)  # fmt: skip
"""Tools a child's activity may use with a grown-up (owner, 2026-10-28: "cut paper with
round-tip children's scissors, with Mummy" is fine). Masked before the activity's d7 check."""
