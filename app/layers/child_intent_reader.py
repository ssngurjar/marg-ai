"""ChildIntentReader: what a child's free text means inside a child-talk session, read by Muse
Spark into a fixed set (s10b §4.16; owner, 2026-11-20).

The session rules only knew fixed phrases, so "main khelne ja rhi hoon", "ab man nhi hai" or
"mummy aagyi ab unse baat kro" were answered as questions: the session went on and the parent got
no summary. This reads only the child's typed or spoken words. Buttons, crisis and safety, the
session and daily limits, and the rules' fast path ("bye", "ok") stay deterministic and never
reach it. Code acts on the intent. When the call fails, or the model is unsure, the caller's
rules decide, and the child is still answered.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.errors import ProviderError
from app.domain.enums import ChildIntent, Language, LeavingReason
from app.domain.models.turn import Exchange
from app.domain.models.usage import StepUsage
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel

MARG_SAID_MAX_CHARS: Final = 800
"""How much of Marg's last reply the reading sees, from its end: a child reply runs to about 720
characters, and its question back sits after the answer and the find-out, so a bare "nahi" can be
read against it (owner, 2026-11-20: after "Aur kuch jaanna hai?" it's going; after "Kya tumne
kabhi titli dekhi hai?" it's an answer)."""


class ChildIntentReading(BaseModel):
    """The model's reading (strict schema; how the fields fit together: `_ReadingChecks`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: ChildIntent
    asked_language: Language | None  # talk or language_switch: the language asked for
    leaving_after: bool  # talk only: the child also says they are going; answer, then goodbye
    handover_after: bool  # talk only: a grown-up has the phone too; answer, then the button
    leaving_reason: LeavingReason | None  # leaving only: why the child is going; optional

    @model_validator(mode="before")
    @classmethod
    def _absent_reason_is_no_reason(cls, data: object) -> object:
        """A reading with no leaving_reason key at all is read as none given. The schema still
        asks for it (strict mode lists every key); this only keeps a model that leaves it out
        from failing the whole reading (owner, 2026-11-20)."""
        if isinstance(data, Mapping) and "leaving_reason" not in data:
            return {**data, "leaving_reason": None}
        return data

    @field_validator("leaving_reason", mode="before")
    @classmethod
    def _odd_reason_is_no_reason(cls, value: object) -> object:
        """An odd reason (not one of LeavingReason) counts as none given, never as a failed
        reading: the reason only picks the opening goodbye's words, and "leaving" is acted on
        with or without it (owner, 2026-11-20)."""
        known = {reason.value for reason in LeavingReason}
        return value if value is None or value in known else None


CHILD_INTENT: Final = PromptSpec(prompt_id="child_intent", output_type=ChildIntentReading)


@dataclass(frozen=True, slots=True)
class ChildIntentRead:
    intent: ChildIntent | None  # None: the call failed
    asked_language: Language | None
    leaving_after: bool  # "ye kya hai? ab main ja rahi hoon": the answer, then the goodbye
    handover_after: bool  # "ye kya hai? mummy se baat karo": the answer, then "I'm the parent"
    # with LEAVING: "khelne ja rhi hoon" → PLAY; None: none given, or odd (the goodbye says
    # "other"); always None with any other intent, whatever the model wrote
    leaving_reason: LeavingReason | None
    usage: StepUsage | None
    prompt_versions: dict[str, str]
    failed: str | None  # "child_intent_failed=<error>" when the call failed

    @property
    def rules_decide(self) -> bool:
        """The reading failed, or the model couldn't tell: the session rules decide, as before
        intent reading, so the child is still answered (owner, 2026-11-20)."""
        return self.intent is None or self.intent is ChildIntent.UNSURE


class _ReadingChecks:
    """The semantic check: a reading whose fields contradict each other gets the one repair
    turn, then fails (the rules decide). Never repaired by code."""

    WITH_A_LANGUAGE: ClassVar[frozenset[ChildIntent]] = frozenset(
        {ChildIntent.TALK, ChildIntent.LANGUAGE_SWITCH}
    )

    @staticmethod
    def problems(reading: ChildIntentReading) -> list[str]:
        problems: list[str] = []
        if reading.intent is ChildIntent.LANGUAGE_SWITCH and reading.asked_language is None:
            problems.append("asked_language: language_switch needs the language asked for")
        if (
            reading.asked_language is not None
            and reading.intent not in _ReadingChecks.WITH_A_LANGUAGE
        ):
            problems.append("asked_language: null unless the intent is talk or language_switch")
        if reading.leaving_after and reading.intent is not ChildIntent.TALK:
            problems.append("leaving_after: true only with talk; else false")
        if reading.handover_after and reading.intent is not ChildIntent.TALK:
            problems.append("handover_after: true only with talk; else false")
        if reading.leaving_after and reading.handover_after:
            problems.append("leaving_after: false when handover_after is true (the grown-up first)")
        # leaving_reason is never a problem: missing, odd or misplaced, it is dropped, and the
        # reading stands (owner, 2026-11-20: never the rules just because of the reason)
        return problems


class ChildIntentReader:
    def __init__(self, llm: LanguageModel, registry: PromptRegistry, timeout: timedelta) -> None:
        """`timeout`: TIMEOUT_ROUTE_S, as for a student's reading. A reading slower than that
        fails, and the rules decide: the child's answer isn't held up by it."""
        self._llm = llm
        self._registry = registry
        self._timeout = timeout

    async def read(
        self, child_message: str, nickname: str | None, recent: Sequence[Exchange]
    ) -> ChildIntentRead:
        """`nickname`: the talking child's home name, so "main Munni ki mummy hoon" reads as a
        grown-up. `recent`: the last exchange tells what the child is answering. Raises
        ValueError for an empty message: a turn with no words (a button) is never read."""
        if not child_message.strip():
            raise ValueError("a child's message to read has no words")
        marg_said = recent[-1].reply_text[-MARG_SAID_MAX_CHARS:] if recent else ""
        rendered = self._registry.render(
            CHILD_INTENT,
            system_vars={},
            user_vars={
                "child": nickname or "",
                "marg_said": marg_said,
                "child_message": child_message,
            },
            semantic_check=_ReadingChecks.problems,
        )
        versions = {CHILD_INTENT.prompt_id: rendered.request.prompt.prompt_version}
        try:
            async with asyncio.timeout(self._timeout.total_seconds()):
                result = await self._llm.generate(rendered.request)
        except (ProviderError, TimeoutError) as exc:
            failed = f"child_intent_failed={type(exc).__name__}"
            return ChildIntentRead(
                intent=None,
                asked_language=None,
                leaving_after=False,
                handover_after=False,
                leaving_reason=None,
                usage=None,
                prompt_versions=versions,
                failed=failed,
            )
        reading = result.output
        return ChildIntentRead(
            reading.intent,
            reading.asked_language,
            reading.leaving_after,
            reading.handover_after,
            reading.leaving_reason if reading.intent is ChildIntent.LEAVING else None,
            result.usage,
            versions,
            None,
        )
