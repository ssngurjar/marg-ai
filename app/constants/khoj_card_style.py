"""What a khoj card looks like (s10b §4.13, C6): the fixed style and a scene per activity.

The image prompt is this style plus the scene. The child's name and the parent's words never
go in, and the model never draws text (the words go in the WhatsApp caption). Style from
spike F (scripts/spikes/image_eval.py), which produced textless, fitting images.
v1, written 2026-10-27: pending the owner's review, ideally against a few generated cards.
"""

from typing import Final

from app.domain.enums import CuriosityDomain

CARD_STYLE_VERSION: Final = "1"
CARD_STYLE: Final = (
    "A warm Indian folk-art illustration in the style of Madhubani and Warli painting, soft earthy "
    "colours, a rural Indian village setting. Absolutely no text, letters, numbers or writing "
    "anywhere in the image. No realistic faces and no identifiable child: if people appear at all, "
    "they are small stylised folk-art figures seen from behind or far away. No wells, ponds, "
    "rivers or other open water, no fire, no roads or vehicles. Subject: "
)
ACTIVITY_SCENES: Final[dict[str, str]] = {
    "animal-walks": "a cow, a hen and a goat walking across a mud courtyard, leaving footprints",
    "ant-watch": "a line of tiny ants carrying grains of rice past a neem tree's roots",
    "dough-shapes": (
        "wheat dough shaped into a long rope, small balls and a flat roti on a steel plate"
    ),
    "home-helper": "a small broom, folded clothes and a steel glass, neatly kept in a village home",
    "leaf-families": "fallen leaves of different shapes and sizes sorted into rows on a charpai",
    "shadow-time": (
        "a tree's shadow on a mud courtyard at morning, noon and evening, the sun moving"
    ),
    "sink-or-float": (
        "a steel bowl of water with a leaf and a twig floating and a stone at the bottom"
    ),
    "sound-hunt": "a bell, a steel spoon on a plate and a bird on a branch, with soft sound lines",
    "stone-tower": "smooth round stones stacked into a small tower on a mud courtyard",
    "yesterday-story": (
        "a small folk-art figure telling a story under a tree, little pictures in the air"
    ),
}
DOMAIN_SCENES: Final[dict[CuriosityDomain, str]] = {
    CuriosityDomain.NATURE_LIVING: "leaves, flowers and small birds around a neem tree",
    CuriosityDomain.EARTH_SKY: "the sun, clouds and the moon over a quiet village",
    CuriosityDomain.NUMBERS_PATTERNS: "small stones and seeds laid out in patterns and rows",
    CuriosityDomain.WORDS_STORIES: "a storyteller figure under a tree, pictures floating around",
    CuriosityDomain.MAKING_BUILDING: "a tiny house built from mud and twigs near a tree",
    CuriosityDomain.MOVEMENT_BODY: "folk-art figures playing and jumping in a courtyard",
    CuriosityDomain.ART_MUSIC: "a dholak, colours and dancing folk-art figures",
    CuriosityDomain.PEOPLE_FEELINGS: "a family of folk-art figures sitting together under a tree",
    CuriosityDomain.EVERYDAY_WORK: "a village kitchen with steel pots, a broom and a basket",
}
