"""Districts as the Local Government Directory lists them (critic review D4, 2026-11-01). The list
itself is data in `app/constants/lgd_districts.py`; this is its shape."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LgdDistrict:
    code: int  # LGD's district code, stable across renames
    name: str  # as LGD writes it in English ("Karauli", "Bengaluru Urban")
    state: str  # the state or union territory, as LGD writes it
    local_name: str | None  # LGD's Devanagari name, where it has one

    @property
    def label(self) -> str:
        """How a verified district is stored and shown: "Karauli, Rajasthan"."""
        return f"{self.name}, {self.state}"
