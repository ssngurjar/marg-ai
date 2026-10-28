"""What SAM 3.1 looks for before a photo is used (s10b §4.14; owner, 2026-10-28).

Spike F: SAM's `person` finds a hand on its own, so any person, a hand included, refuses the
photo; `face` also catches a face cut off at the edge or on a poster.
"""

from typing import Final

PERSON_PHRASES: Final[tuple[str, ...]] = ("person", "face")
