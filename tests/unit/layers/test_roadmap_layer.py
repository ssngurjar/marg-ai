"""RoadmapLayer: show the stored plan, or draft a sourced one returned as a write (s12 §4.4)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import HttpUrl

from app.constants.student_copy import MAKE_A_PLAN, NEW_PLAN_BUTTON, PLAN_UNVERIFIABLE
from app.domain.enums import Language, RoadmapStatus, RoadmapStepStatus
from app.domain.models.student import ProfileMemory, Roadmap, RoadmapStep
from app.domain.models.writes import SaveRoadmap
from app.layers.mentor_context import MentorContextBuilder
from app.layers.mentor_layer import MentorLayer, MentorSettings
from app.layers.roadmap_layer import RoadmapDraft, RoadmapLayer
from tests.fakes.language_model import FakeLanguageModel
from tests.support.prompts import shipped_registry
from tests.support.student import (
    ROADMAP_DRAFT,
    ROADMAP_STEPS,
    corpus_retriever,
    retrieved,
    student_ctx,
)

pytestmark = pytest.mark.unit

H = Language.HINGLISH
ASK = "class 8 scholarship ka plan banao"
AT = datetime(2026, 10, 1, tzinfo=UTC)
STORED = Roadmap(
    id=UUID(int=77),
    goal="NMMS scholarship",
    status=RoadmapStatus.ACTIVE,
    steps=[
        RoadmapStep(position=1, action="Teacher se poocho", timeframe="is hafte", cost_inr=None,
                    source_url=HttpUrl("https://scholarships.gov.in/doc1"),
                    status=RoadmapStepStatus.TODO),
        RoadmapStep(position=2, action="Roz padho", timeframe="roz", cost_inr=None,
                    source_url=None, status=RoadmapStepStatus.TODO),
    ],
    created_at=AT,
)  # fmt: skip


def layer(llm: FakeLanguageModel, *, relevant: bool = True) -> RoadmapLayer:
    retriever, _ = corpus_retriever(relevant=relevant)
    mentor = MentorLayer(
        llm, shipped_registry(), retriever, MentorSettings(query_rewrite_enabled=False)
    )
    return RoadmapLayer(llm, shipped_registry(), mentor)


async def test_a_new_plan_is_a_save_write_with_sources_resolved_to_pages() -> None:
    llm = FakeLanguageModel([ROADMAP_DRAFT])
    result = await layer(llm).handle(student_ctx(ASK), ASK, [], H)
    [write] = result.writes
    assert isinstance(write, SaveRoadmap)
    assert write.goal == "Class 8 mein NMMS scholarship"
    assert [str(step.source_url) if step.source_url else None for step in write.steps] == [
        "https://scholarships.gov.in/doc1", "https://scholarships.gov.in/doc2", None,
    ]  # fmt: skip
    assert write.abandon_roadmap_id is None
    assert write.prompt_version == "1.0.1"
    body = result.reply.body
    assert body.startswith("Aapka plan: Class 8 mein NMMS scholarship\n1. Teacher se NMMS form")
    assert "— is hafte [1]" in body
    assert "3. Roz ek ghanta maths aur mental ability practice karo — roz\n" in body
    assert "Sources (official):" in body


async def test_asking_again_shows_the_stored_plan_without_a_model_call() -> None:
    llm = FakeLanguageModel([])
    ctx = student_ctx("mera plan dikhao").model_copy(update={"active_roadmap": STORED})
    result = await layer(llm).handle(ctx, "mera plan dikhao", [], H)
    assert llm.prompts == []
    assert result.writes == []
    assert result.reply.body.startswith(
        "Aapka plan: NMMS scholarship\n1. Teacher se poocho — is hafte"
    )
    assert result.reply.buttons == [NEW_PLAN_BUTTON[H]]


@pytest.mark.parametrize(("text", "ids"), [("naya plan banao", []), ("", [MAKE_A_PLAN])])
async def test_a_new_plan_with_one_active_abandons_the_old(text: str, ids: list[str]) -> None:
    ctx = student_ctx(ASK).model_copy(update={"active_roadmap": STORED})
    result = await layer(FakeLanguageModel([ROADMAP_DRAFT])).handle(ctx, text or ASK, ids, H)
    [write] = result.writes
    assert isinstance(write, SaveRoadmap)
    assert write.abandon_roadmap_id == STORED.id


async def test_nothing_relevant_drafts_and_stores_nothing() -> None:
    llm = FakeLanguageModel([])
    result = await layer(llm, relevant=False).handle(student_ctx(ASK), ASK, [], H)
    assert llm.prompts == []
    assert result.writes == []
    assert result.reply.body == PLAN_UNVERIFIABLE[H]


def test_a_short_request_is_searched_with_the_students_ambitions() -> None:
    memory = ProfileMemory(summary="s", ambitions=["doctor (NEET)"], constraints=[], updated_at=AT)
    ctx = student_ctx("plan banao").model_copy(update={"memory": memory})
    assert RoadmapLayer.search_text(ctx, "plan banao") == "plan banao doctor (NEET)"
    long_ask = "mujhe class 10 ke baad polytechnic karni hai plan banao"
    assert RoadmapLayer.search_text(ctx, long_ask) == long_ask


@pytest.mark.parametrize(
    ("step_change", "problem"),
    [
        ({"source": "C9"}, "C9 were not provided"),
        ({"cost_inr": 500, "source": None}, "cost_inr needs a source"),
        ({"free_now": False}, "at least one step must be free"),
    ],
)
def test_each_plan_check_names_its_problem(step_change: dict[str, object], problem: str) -> None:
    steps = [{**step, **step_change} for step in ROADMAP_STEPS]
    draft = RoadmapDraft.model_validate({**ROADMAP_DRAFT, "steps": steps})
    context = MentorContextBuilder.build(student_ctx(), [retrieved(1), retrieved(2)], "q")
    assert problem in " | ".join(RoadmapLayer.problems(draft, context, H))


@pytest.mark.parametrize("count", [2, 7])
def test_a_plan_has_three_to_six_steps(count: int) -> None:
    step = ROADMAP_STEPS[0]
    with pytest.raises(ValueError, match="steps"):
        RoadmapDraft.model_validate({**ROADMAP_DRAFT, "steps": [step] * count})


def test_a_negative_cost_is_refused() -> None:
    step = {**ROADMAP_STEPS[0], "cost_inr": -1}
    with pytest.raises(ValueError, match="cost_inr"):
        RoadmapDraft.model_validate({**ROADMAP_DRAFT, "steps": [step] * 3})


def test_a_cost_without_a_valid_source_is_never_stored() -> None:
    draft = RoadmapDraft.model_validate(
        {
            **ROADMAP_DRAFT,
            "steps": [{**step, "cost_inr": Decimal(100)} for step in ROADMAP_STEPS],
        }
    )
    context = MentorContextBuilder.build(student_ctx(), [retrieved(1), retrieved(2)], "q")
    write, _ = RoadmapLayer.resolved(draft, context, student_ctx(), H, "1.0.0")
    assert [step.cost_inr for step in write.steps] == [Decimal(100), Decimal(100), None]
