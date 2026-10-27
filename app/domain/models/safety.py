"""A safety check's result (contracts.md §2.5). Produced by s07's gate; read by the trace."""

from typing import Literal

from app.domain.enums import SafetyCategory, SafetyDecision
from app.domain.models.base import DomainModel


class SafetyVerdict(DomainModel):
    decision: SafetyDecision
    categories: list[SafetyCategory]  # empty when ALLOW
    source: Literal["llama_guard", "domain_policy", "fixed"]


class CrisisLexicon(DomainModel):
    """The reviewed phrase lists the crisis rules match (s07 §4.5); values live in
    app/constants/crisis_lexicon.py, so domain code stays free of copy."""

    version: str
    self_harm_phrases: tuple[str, ...]  # any one, as a whole-word sequence → SELF_HARM
    abuse_people: tuple[str, ...]  # a family or authority word…
    abuse_harms: tuple[
        str, ...
    ]  # …within `abuse_window_tokens` of a harm phrase → ABUSE_DISCLOSURE
    abuse_window_tokens: int
