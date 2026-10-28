"""Turn records and cases for the eval harness's own tests (no database, no model)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import HttpUrl

from app.domain.enums import Language, Route, SafetyDecision
from app.domain.models.base import TurnId
from app.domain.models.reply import CanonicalReply, Citation
from app.domain.models.safety import SafetyVerdict
from app.evals.golden_case import GoldenCase
from app.evals.turn_capture import TurnRecord
from app.store.repositories.eval_repository import EvalPart, EvalStep, EvalTurnSnapshot, SourceText

AT = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
CHUNK = UUID(int=42)


def verdict(decision: SafetyDecision = SafetyDecision.ALLOW) -> SafetyVerdict:
    return SafetyVerdict(decision=decision, categories=[], source="llama_guard")


def step(name: str, outcome: str = "ok", detail: str | None = None, **extra: object) -> EvalStep:
    return EvalStep(
        step=name,
        outcome=outcome,
        failure_kind=str(extra["failure_kind"]) if "failure_kind" in extra else None,
        duration_ms=100,
        cost_usd=Decimal("0.001"),
        detail=detail,
        model=None,
        started_at=AT,
    )


def part(text: str | None = "Namaste", kind: str = "text", **flags: bool) -> EvalPart:
    return EvalPart(
        part_no=int(flags.get("part_no", 0)),
        kind=kind,
        text=text,
        has_audio=flags.get("has_audio", False),
        has_image=flags.get("has_image", False),
        status="sent",
        button_titles=[],
    )


def snapshot(  # noqa: PLR0913  # one keyword per field a check reads
    *,
    route: Route | None = Route.JOURNEY,
    reply_text: str = "Bahut accha! Munni ke saath patte ikatthe kijiye.",
    register: Language | None = Language.HINGLISH,
    fixed: str | None = None,
    steps: list[EvalStep] | None = None,
    parts: list[EvalPart] | None = None,
) -> EvalTurnSnapshot:
    return EvalTurnSnapshot(
        turn_id=TurnId(UUID(int=1)),
        status="completed",
        route=route,
        fixed_reply_kind=fixed,
        reply_text=reply_text,
        reply_register=register,
        steps=steps if steps is not None else [step("safety_in"), step("generate")],
        parts=parts if parts is not None else [part(reply_text)],
        latency_ms=4200,
    )


def record(  # noqa: PLR0913  # one keyword per thing a test changes
    *,
    shot: EvalTurnSnapshot | None = None,
    safety_in: SafetyVerdict | None = None,
    safety_out: SafetyVerdict | None = None,
    citations: list[Citation] | None = None,
    sources: list[SourceText] | None = None,
    spoken: list[str] | None = None,
    later: list[EvalTurnSnapshot] | None = None,
    media_left: int = 0,
    card_prompts: list[str] | None = None,
) -> TurnRecord:
    taken = shot or snapshot()
    return TurnRecord(
        snapshot=taken,
        safety_in=safety_in or verdict(),
        safety_out=safety_out or verdict(),
        generated=CanonicalReply(
            body=taken.reply_text or "",
            body_language=Language.HINGLISH,
            spoken_text=None,
            citations=citations or [],
            buttons=[],
            fixed_kind=None,
        ),
        spoken_texts=spoken if spoken is not None else ["बहुत अच्छा।"],
        sources=sources or [],
        later_turns=later or [],
        media_left=media_left,
        card_prompts=card_prompts or [],
    )


def citation(chunk_id: UUID = CHUNK) -> Citation:
    return Citation(
        title="NMMS", source_url=HttpUrl("https://scholarships.gov.in/nmms"), chunk_id=chunk_id
    )


def source(chunk_id: UUID = CHUNK) -> SourceText:
    return SourceText(chunk_id, "NMMS", "https://scholarships.gov.in/nmms", "NMMS is for class 8.")


def case(**fields: object) -> GoldenCase:
    base: dict[str, object] = {
        "id": "parent-journey-901",
        "title": "a test case",
        "profile": {"role": "parent", "language": "hinglish"},
        "learner": {"relation": "parent", "nickname": "Munni", "age": 5},
        "turns": [{"user": "Aaj ki khoj batao"}],
        "expect": {"route": "journey", "must": ["gives an activity"]},
    }
    base.update(fields)
    return GoldenCase.model_validate(base)
