"""Words the voice says badly, and what is spoken instead (s06; owner's listening tests).

Swapped in a reply's spoken text just before text-to-speech; the written reply keeps the model's
words. Whole words only. Every swap means the same thing, said a way MMS-TTS pronounces right.
"""

from typing import Final

SPOKEN_WORD_SWAPS: Final[dict[str, str]] = {
    # 2026-10-29: "पूछिए" was heard as "पूखिए", "बिठाइए" as "बिखाए"; these were heard right.
    "पूछिए": "पूछ लीजिए",
    "पूछिये": "पूछ लीजिए",
    "बिठाइए": "बैठाइए",
    "बिठाइये": "बैठाइए",
}
