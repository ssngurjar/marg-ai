"""SmallCountSuppressor: the k-anonymity floor (s13 §4.7), applied once, before anything renders.

A number drawn from fewer than `floor` distinct children is shown as "fewer than <floor>"
(None here), never as its value. The admin view uses K_ANONYMITY_FLOOR_ADMIN, every other view
K_ANONYMITY_FLOOR (owner, 2026-10-28).
"""

from collections.abc import Mapping


class SmallCountSuppressor:
    @staticmethod
    def count(value: int, floor: int) -> int | None:
        return value if value >= floor else None

    @staticmethod
    def counts[KeyT](counts: Mapping[KeyT, int], floor: int) -> dict[KeyT, int | None]:
        suppressed: dict[KeyT, int | None] = {}
        for key, value in counts.items():
            suppressed[key] = SmallCountSuppressor.count(value, floor)
        return suppressed
