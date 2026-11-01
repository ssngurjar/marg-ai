"""What SAM 3.1 looks for before a photo is used (s10b §4.14).

Only a face refuses the photo (owner, 2026-11-01): a child's hands holding what they collected
are fine, so `person`, which finds a hand on its own (spike F), is no longer asked. `face` also
catches a face cut off at the edge or on a poster.
"""

from typing import Final

PERSON_PHRASES: Final[tuple[str, ...]] = ("face",)
