"""ExposureLayer: a chapter connected to three real-world fields, safely (s10)."""

from datetime import UTC, datetime

import pytest

from app.constants.teacher_copy import ASK_CHAPTER, MORE_ACTIVITY, NEW_CHAPTER
from app.core.errors import DomainError
from app.domain.enums import Language, Role, Route
from app.domain.models.turn import Exchange, TurnContext
from app.layers.curriculum_catalogue import ChapterCatalogue
from app.layers.exposure_layer import ExposureBridge, ExposureLayer
from tests.fakes.language_model import FakeLanguageModel
from tests.support.prompts import shipped_registry
from tests.support.turn_context import text_message, turn_context, user_profile

pytestmark = pytest.mark.unit

H, E = Language.HINGLISH, Language.ENGLISH
AT = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)


def field(
    name: str, kind: str = "stem", activity: str = "Students press a sandal on soft soil."
) -> dict[str, object]:
    return {
        "field": name, "field_kind": kind,
        "why_it_connects": "Pressure is force over area, which this work uses every day.",
        "example_from_india": "Handpumps across Indian villages lift water with pressure.",
        "five_minute_activity": activity, "activity_materials": ["chalk", "stones"],
        "needs_electricity": False, "needs_purchase": False,
        "careers": ["plumber", "ITI fitter"], "local_hook": "The village handpump in summer.",
    }  # fmt: skip


BRIDGE: dict[str, object] = {
    "outcome": "bridge", "topic": "Force and Pressure", "grade": 8,
    "fields": [
        field("Plumbing"),
        field("Agri-business", "non_stem"),
        field("Kabaddi coaching", "non_stem"),
    ],
    "clarifying_question": None, "extra_activity": None, "extra_activity_field": None,
    "extra_activity_materials": [],
    "spoken_text": "Force and pressure connects to plumbing, agri-business and kabaddi coaching.",
}  # fmt: skip
CLARIFY: dict[str, object] = {
    **BRIDGE, "outcome": "clarify", "topic": None, "grade": None, "fields": [],
    "clarifying_question": "Which chapter are you teaching tomorrow?",
    "spoken_text": "Which chapter are you teaching tomorrow?",
}  # fmt: skip
MORE: dict[str, object] = {
    **CLARIFY, "outcome": "more_activity", "topic": "Force and Pressure",
    "clarifying_question": None, "extra_activity": "Students push a bench with one and two hands.",
    "extra_activity_field": "Sports", "extra_activity_materials": ["bench"],
    "spoken_text": "Another activity: students push a bench.",
}  # fmt: skip


POWERED = {**field("Media"), "needs_electricity": True}
ONE_CAREER = {**field("Media"), "careers": ["one"]}


def teacher_ctx(
    text: str = "Kal class 8 Force and Pressure", exchanges: list[Exchange] | None = None
) -> TurnContext:
    profile = user_profile(role=Role.TEACHER, language=E).model_copy(
        update={"grade": 8, "subject": "science", "district": "Karauli"}
    )
    return turn_context(text_message(text), profile=profile).model_copy(
        update={"recent_exchanges": exchanges or []}
    )


def layer(llm: FakeLanguageModel) -> ExposureLayer:
    return ExposureLayer(llm, shipped_registry(), ChapterCatalogue(()))


async def test_a_bridge_names_three_fields_first_and_offers_the_two_buttons() -> None:
    llm = FakeLanguageModel([BRIDGE])
    result = await layer(llm).generate(teacher_ctx(), "Kal class 8 Force and Pressure", [], E)
    body = result.reply.body
    assert body.startswith(
        "Topic: Force and Pressure (class 8)\n"
        "Three fields this chapter leads to: Plumbing, Agri-business, Kabaddi coaching."
    )
    assert "Activity (5 minutes): Students press a sandal on soft soil." in body
    for marker in ("*", "#", "|", "`"):
        assert marker not in body
    assert [button.id for button in result.reply.buttons] == [MORE_ACTIVITY, NEW_CHAPTER]
    assert result.reply.citations == []
    [prompt] = llm.prompts
    assert "class 8, subject science, district Karauli" in prompt.system
    assert "Kal class 8 Force and Pressure" in prompt.user


async def test_a_vague_message_gets_one_question_and_no_buttons() -> None:
    result = await layer(FakeLanguageModel([CLARIFY])).generate(
        teacher_ctx("kuch naya"), "kuch naya", [], E
    )
    assert result.reply.body == "Which chapter are you teaching tomorrow?"
    assert result.reply.buttons == []


async def test_another_activity_gets_the_previous_reply_as_data() -> None:
    previous = Exchange(
        user_text="Force and Pressure",
        reply_text="Topic: Force and Pressure…",
        route=Route.EXPOSURE,
        at=AT,
    )
    mentor = Exchange(user_text="x", reply_text="a mentor reply", route=Route.MENTOR, at=AT)
    llm = FakeLanguageModel([MORE])
    result = await layer(llm).generate(teacher_ctx("", [previous, mentor]), "", [MORE_ACTIVITY], E)
    assert result.reply.body.startswith("Another activity: Force and Pressure (Sports)")
    [prompt] = llm.prompts
    assert "Topic: Force and Pressure…" in prompt.user
    assert "a mentor reply" not in prompt.user


@pytest.mark.parametrize(
    ("ids", "exchanges"),
    [([NEW_CHAPTER], []), ([MORE_ACTIVITY], [])],
    ids=["new_chapter", "more_without_a_bridge"],
)
async def test_the_fixed_ask_for_chapter_needs_no_model(
    ids: list[str], exchanges: list[Exchange]
) -> None:
    llm = FakeLanguageModel([])
    result = await layer(llm).generate(teacher_ctx("", exchanges), "", ids, H)
    assert result.reply.body == ASK_CHAPTER[H]
    assert llm.prompts == []


@pytest.mark.parametrize("role", [Role.STUDENT, Role.PARENT])
async def test_anyone_but_a_teacher_is_a_router_bug(role: Role) -> None:
    ctx = teacher_ctx().model_copy(update={"profile": user_profile(role=role)})
    with pytest.raises(DomainError, match="exposure called for role"):
        await layer(FakeLanguageModel([BRIDGE])).generate(ctx, "x", [], E)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"fields": [field("Pumps"), field("Farms", "non_stem")]}, "exactly three fields"),
        ({"fields": [field("Pumps"), field("Farms"), field("Media")]}, "non_stem"),
        ({"fields": [field("Pumps"), field("pumps", "non_stem"), field("Media")]}, "different"),
        ({"fields": [field("Pumps"), field("Farms", "non_stem"), POWERED]}, "electricity"),
        ({"outcome": "clarify"}, "clarify"),
        ({"outcome": "more_activity", "fields": []}, "more_activity"),
        ({"fields": [field("Pumps"), field("Farms", "non_stem"), ONE_CAREER]}, "careers"),
    ],
    ids=[
        "two_fields", "all_stem", "duplicate", "electricity", "clarify_with_fields",
        "more_without_activity", "one_career",
    ],
)  # fmt: skip
def test_each_bridge_rule_is_enforced(change: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ExposureBridge.model_validate({**BRIDGE, **change})


@pytest.mark.parametrize(
    ("activity", "problem"),
    [
        ("Show a video on the projector", "no projector"),
        ("Students buy a ball and kick it", "no projector"),
        ("Bachche ek gend kharidna", "no projector"),
        ("Engineers earn a salary of ₹30,000 a month", "no salaries"),
    ],
)
def test_devices_purchases_and_money_are_refused(activity: str, problem: str) -> None:
    fields = [field("Pumps", activity=activity), field("Farms", "non_stem"), field("Media")]
    bridge = ExposureBridge.model_validate({**BRIDGE, "fields": fields})
    assert problem in " | ".join(ExposureLayer.problems(bridge, E))


def test_a_clean_bridge_has_no_problems() -> None:
    assert ExposureLayer.problems(ExposureBridge.model_validate(BRIDGE), E) == []
