"""MentorContext: what every mentor and roadmap prompt is given, within a token budget (s12 §4.2).

In order: the profile (class, district, language: never a hash or number), the student's memory,
their active plan, the retrieved chunks labelled C1…Cn, the recent exchanges, then the message.
The memory, plan and exchanges come from the student, so they go in user slots; the chunks are
curated and go in the system part. Over budget, the oldest exchanges go first (the latest one
always stays), then the lowest-ranked chunks; a chunk is never cut.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from app.domain.models.retrieval import RetrievedChunk
from app.domain.models.turn import TurnContext
from app.rag.chunker import Chunker


@dataclass(frozen=True, slots=True)
class LabelledChunk:
    label: str  # "C1"
    chunk: RetrievedChunk


@dataclass(frozen=True, slots=True)
class MentorContext:
    profile_block: str
    memory_block: str
    plan_block: str
    chunks: list[LabelledChunk]
    exchange_blocks: list[str]
    message: str

    @property
    def sources(self) -> str:
        return "\n\n".join(
            f"[{labelled.label}] {labelled.chunk.title} — {labelled.chunk.heading_path}\n"
            f"{labelled.chunk.text}"
            for labelled in self.chunks
        )

    @property
    def recent_conversation(self) -> str:
        return "\n".join(self.exchange_blocks)

    def tokens(self) -> int:
        parts = [
            self.profile_block,
            self.memory_block,
            self.plan_block,
            self.sources,
            self.recent_conversation,
            self.message,
        ]
        return sum(Chunker.approx_tokens(part) for part in parts)


class MentorContextBuilder:
    BUDGET_TOKENS: ClassVar[int] = 6000

    @staticmethod
    def build(ctx: TurnContext, chunks: Sequence[RetrievedChunk], message: str) -> MentorContext:
        context = MentorContext(
            profile_block=MentorContextBuilder._profile(ctx),
            memory_block=MentorContextBuilder._memory(ctx),
            plan_block=MentorContextBuilder._plan(ctx),
            chunks=[
                LabelledChunk(f"C{position}", chunk)
                for position, chunk in enumerate(chunks, start=1)
            ],
            exchange_blocks=[
                f"Student: {exchange.user_text}\nMarg: {exchange.reply_text}"
                for exchange in ctx.recent_exchanges
            ],
            message=message,
        )
        return MentorContextBuilder._fitted(context)

    @staticmethod
    def _fitted(context: MentorContext) -> MentorContext:
        exchanges = list(context.exchange_blocks)
        chunks = list(context.chunks)
        fitted = context
        while fitted.tokens() > MentorContextBuilder.BUDGET_TOKENS:
            if len(exchanges) > 1:
                exchanges = exchanges[1:]  # the oldest goes first
            elif chunks:
                chunks = chunks[:-1]  # then the lowest-ranked chunk, whole
            else:
                break  # only what must stay is left
            fitted = MentorContext(
                context.profile_block,
                context.memory_block,
                context.plan_block,
                chunks,
                exchanges,
                context.message,
            )
        return fitted

    @staticmethod
    def _profile(ctx: TurnContext) -> str:
        profile = ctx.profile
        grade = f"class {profile.grade}" if profile.grade else "class not known"
        district = profile.district or "district not known"
        language = profile.language.value if profile.language else "not known"
        return f"{grade}, {district}, prefers {language}"

    @staticmethod
    def _memory(ctx: TurnContext) -> str:
        memory = ctx.memory
        if memory is None:
            return ""
        return (
            f"{memory.summary}\nAmbitions: {'; '.join(memory.ambitions) or '-'}\n"
            f"What holds them back: {'; '.join(memory.constraints) or '-'}"
        )

    @staticmethod
    def _plan(ctx: TurnContext) -> str:
        roadmap = ctx.active_roadmap
        if roadmap is None:
            return ""
        steps = "\n".join(f"{step.position}. {step.action}" for step in roadmap.steps)
        return f"Current plan: {roadmap.goal}\n{steps}"
