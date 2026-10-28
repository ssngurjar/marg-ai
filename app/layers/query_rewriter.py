"""QueryRewriter: a student's question as an English search with exam and scheme names
(s11 §4.6). It lives with the mentor and roadmap layers, since rag may not import prompts.
Behind QUERY_REWRITE_ENABLED (off by default, decision B9): it is switched on only if the
retrieval eval shows recall@5 improve by at least 0.05.

A failed rewrite never fails the turn: retrieval goes ahead with the student's own words.
"""

from collections.abc import Sequence
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.errors import ProviderError
from app.domain.enums import CorpusTopic
from app.domain.models.retrieval import RetrievalQuery
from app.domain.models.turn import Exchange
from app.domain.models.usage import StepUsage
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

type Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class RewrittenQuery(BaseModel):
    """The rewrite (strict schema: every field required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    english_query: str = Field(min_length=1, max_length=200)
    keywords: list[Name] = Field(max_length=8)
    topics: list[CorpusTopic] = Field(max_length=3)


QUERY_REWRITE: Final = PromptSpec(prompt_id="query_rewrite", output_type=RewrittenQuery)


class QueryRewriter:
    def __init__(self, llm: LanguageModel, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    async def rewrite(
        self, user_text: str, recent: Sequence[Exchange], grade: int | None
    ) -> tuple[RetrievalQuery, StepUsage | None, str | None]:
        """The query, its usage, and None, or the student's own words, None and the reason the
        rewrite failed (the caller records the step as DEGRADED)."""
        conversation = "\n".join(
            f"Student: {exchange.user_text}\nMarg: {exchange.reply_text}"
            for exchange in recent[-2:]
        )
        rendered = self._registry.render(
            QUERY_REWRITE,
            system_vars={"grade": str(grade) if grade is not None else "not known"},
            user_vars={"recent_conversation": conversation, "message": user_text},
        )
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderError as exc:
            return QueryRewriter.raw(user_text), None, f"query_rewrite_failed={type(exc).__name__}"
        output = result.output
        query = RetrievalQuery(
            english_query=output.english_query,
            keywords=list(output.keywords),
            topics=list(output.topics),
        )
        return query, result.usage, None

    @staticmethod
    def raw(user_text: str) -> RetrievalQuery:
        """The student's own words, as the query when rewriting is off or failed."""
        return RetrievalQuery(english_query=user_text[:1000], keywords=[], topics=[])
