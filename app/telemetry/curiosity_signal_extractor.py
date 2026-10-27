"""CuriositySignalExtractor: what a child engaged with, from a parent's report or the child's
own words (s13 §4.4). Runs after the reply is sent; its output is telemetry, never shown.
"""

from dataclasses import dataclass
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import CuriosityDomain
from app.domain.models.curiosity import CuriositySignals, CuriositySourceKind, ExtractSignals
from app.domain.models.usage import StepUsage
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class CuriosityExtraction(BaseModel):
    """The model's answer (strict schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domains: list[CuriosityDomain] = Field(max_length=3)
    engagement: int = Field(ge=0, le=3)
    child_asked_question: bool


CURIOSITY_EXTRACT: Final = PromptSpec(
    prompt_id="curiosity_extract", output_type=CuriosityExtraction
)
UNKNOWN_AGE: Final = "3 to 8"


@dataclass(frozen=True, slots=True)
class ExtractedSignals:
    signals: CuriositySignals
    usage: StepUsage
    prompt_version: str


class CuriositySignalExtractor:
    SOURCE_RULES: ClassVar[dict[CuriositySourceKind, str]] = {
        "parent_report": (
            "The text is a parent's report of what their child said or did during today's "
            "activity{title}. Judge only the child, as the parent describes them."
        ),
        "child_words": "The text is what the child said to you themselves.",
        "relayed_question": (
            "The text is a parent passing on a question their child asked. The child asked their "
            "own question."
        ),
    }

    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def extract(self, task: ExtractSignals) -> ExtractedSignals:
        """Raises ProviderError when the model can't give valid signals."""
        source = task.source
        title = f' ("{source.activity_title}")' if source.activity_title else ""
        rendered = self._registry.render(
            CURIOSITY_EXTRACT,
            system_vars={
                "child_age": task.child_age if task.child_age is not None else UNKNOWN_AGE,
                "source_rule": self.SOURCE_RULES[source.kind].format(title=title),
                "hint_domains": ", ".join(domain.value for domain in source.hint_domains),
            },
            user_vars={"child_words": task.user_text},
            semantic_check=lambda extraction: _ExtractionChecks.problems(extraction, source.kind),
        )
        result = await self._llm.generate(rendered.request)
        extraction = result.output
        signals = CuriositySignals(
            domains=list(extraction.domains),
            engagement=extraction.engagement,
            # a relayed question is the child's own question by definition
            child_asked_question=(
                extraction.child_asked_question or source.kind == "relayed_question"
            ),
        )
        return ExtractedSignals(signals, result.usage, rendered.request.prompt.prompt_version)


class _ExtractionChecks:
    """s13 §4.4: no duplicates; no engagement means no question; engaged means a domain."""

    ENGAGED: ClassVar[int] = 2  # rubric level "an engaged answer or question"

    @staticmethod
    def problems(extraction: CuriosityExtraction, kind: CuriositySourceKind) -> list[str]:
        problems: list[str] = []
        if len(set(extraction.domains)) != len(extraction.domains):
            problems.append("domains: list each at most once")
        if extraction.engagement == 0 and extraction.child_asked_question:
            problems.append("child_asked_question: can't be true when engagement is 0")
        if extraction.engagement >= _ExtractionChecks.ENGAGED and not extraction.domains:
            problems.append("domains: name at least one when engagement is 2 or more")
        if kind == "relayed_question" and extraction.engagement == 0:
            problems.append("engagement: a child who asked a question engaged (at least 1)")
        return problems
