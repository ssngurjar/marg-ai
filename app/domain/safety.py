"""A safety check's result (contracts.md §2.5). Produced by s07's gate; read by the trace."""

from typing import Literal

from app.domain.enums import SafetyCategory, SafetyDecision
from app.domain.models import DomainModel


class SafetyVerdict(DomainModel):
    decision: SafetyDecision
    categories: list[SafetyCategory]  # empty when ALLOW
    source: Literal["llama_guard", "domain_policy", "fixed"]
