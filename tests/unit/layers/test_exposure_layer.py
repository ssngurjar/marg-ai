"""ExposureLayer: a chapter connected to three real-world fields, safely (s10)."""

from datetime import UTC, datetime
from typing import Final

import pytest

from app.constants.crisis_replies import CHILD_HELPLINE
from app.constants.small_talk_copy import ACKNOWLEDGED_AGAIN, OTHER_ROLE_REPLY
from app.constants.teacher_copy import (
    ASK_CHAPTER,
    MORE_ACTIVITY,
    NEW_CHAPTER,
    TEACHER_ACKNOWLEDGED,
    TEACHER_CONCERN,
    TEACHER_HELLO,
    TEACHER_OUT_OF_SCOPE,
)
from app.core.errors import DomainError, ProviderUnavailable
from app.domain.enums import Language, Role, Route, StepOutcome
from app.domain.models.turn import Exchange, TurnContext
from app.layers.curriculum_catalogue import ChapterCatalogue
from app.layers.exposure_layer import ExposureBridge, ExposureLayer
from app.layers.teacher_intent_reader import TeacherIntentReader
from app.layers.teaching_layer import TeachingAnswer, TeachingLayer
from tests.fakes.language_model import FakeLanguageModel, PromptRoutedLanguageModel, ScriptedOutput
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
        update={"grade": 8, "subject": "science", "district": "Karauli, Rajasthan"}
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


# --- teaching help, not only bridges (owner, 2026-11-01) -----------------------------------------

TEACHING: dict[str, object] = {
    "opening": "Ask: at the haat, why do sacks slide forward when the cart stops?",
    "steps": [
        "Things keep doing what they do until a push or pull changes it.",
        "A heavier thing needs more force to start or stop.",
        "Every push has an equal push back.",
    ],
    "check_question": "Why do we lean forward when the bus stops?",
    "common_mistake": "Students think force keeps things moving; force changes motion.",
    "spoken_text": "Ask the class why sacks slide forward when the cart stops.",
}
LAST_BRIDGE = Exchange(
    user_text="Class 9 newtons laws of motion",
    reply_text="Topic: Newton's laws of motion (class 9)\nThree fields this chapter leads to: …",
    route=Route.EXPOSURE,
    at=datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
)


def teacher_reading(intent: str, topic: str | None = None) -> dict[str, object]:
    return {"intent": intent, "topic": topic}


ABOUT_MARG_REPLY: Final = {
    "answer": "Marg never sells or shares your information for ads.",
    "unknown": False,
    "spoken_text": "Marg never sells or shares your information for ads.",
}


def reading_layer(
    reading: ScriptedOutput, teaching: ScriptedOutput = TEACHING, bridge: ScriptedOutput = BRIDGE
) -> tuple[ExposureLayer, PromptRoutedLanguageModel]:
    llm = PromptRoutedLanguageModel(
        {
            "teacher_intent": FakeLanguageModel([reading]),
            "teaching_answer": FakeLanguageModel([teaching]),
            "exposure": FakeLanguageModel([bridge]),
            "about_marg": FakeLanguageModel([ABOUT_MARG_REPLY]),
        }
    )
    registry = shipped_registry()
    return (
        ExposureLayer(
            llm,
            registry,
            ChapterCatalogue(()),
            intents=TeacherIntentReader(llm, registry),
            teaching=TeachingLayer(llm, registry),
        ),
        llm,
    )


async def test_how_to_start_the_class_gets_teaching_help_for_the_last_chapter() -> None:
    # Owner's demo: "how to start in class so everyone understands it" got "which chapter?"
    layer_with_reader, llm = reading_layer(teacher_reading("teaching"))
    text = "Can you tell me first how to start in class so everyone understand it"
    result = await layer_with_reader.generate(teacher_ctx(text, [LAST_BRIDGE]), text, [], E)
    assert result.reply.body.startswith("Topic: Newton's laws of motion\n")
    assert "Start the class like this:" in result.reply.body
    assert "1. Things keep doing" in result.reply.body
    [prompt] = llm.by_prompt["teaching_answer"].prompts
    assert "The chapter: Newton's laws of motion." in prompt.system
    assert llm.by_prompt["exposure"].prompts == []
    assert result.prompt_versions == {"teacher_intent": "1.3.0", "teaching_answer": "1.0.0"}


async def test_a_teaching_question_naming_its_topic_uses_that_topic() -> None:
    layer_with_reader, _ = reading_layer(teacher_reading("teaching", "mass and weight"))
    text = "students confuse mass and weight"
    result = await layer_with_reader.generate(teacher_ctx(text, [LAST_BRIDGE]), text, [], E)
    assert result.reply.body.startswith("Topic: mass and weight\n")


async def test_a_teaching_question_with_no_chapter_anywhere_asks_for_one() -> None:
    layer_with_reader, llm = reading_layer(teacher_reading("teaching"))
    result = await layer_with_reader.generate(
        teacher_ctx("how do I start it"), "how do I start it", [], E
    )
    assert result.reply.body == ASK_CHAPTER[E]
    assert llm.by_prompt["teaching_answer"].prompts == []


async def test_a_chapter_read_as_a_bridge_gets_the_three_fields() -> None:
    layer_with_reader, llm = reading_layer(teacher_reading("bridge", "Force and Pressure"))
    result = await layer_with_reader.generate(
        teacher_ctx(), "Kal class 8 Force and Pressure", [], E
    )
    assert len(llm.by_prompt["exposure"].prompts) == 1
    assert llm.by_prompt["teaching_answer"].prompts == []
    assert result.outcome is StepOutcome.OK


async def test_if_the_reading_fails_the_bridge_is_made_and_the_turn_says_so() -> None:
    layer_with_reader, llm = reading_layer(ProviderUnavailable("503", provider="meta_model_api"))
    result = await layer_with_reader.generate(
        teacher_ctx(), "Kal class 8 Force and Pressure", [], E
    )
    assert len(llm.by_prompt["exposure"].prompts) == 1
    assert result.outcome is StepOutcome.DEGRADED
    assert result.degraded_reason == "teacher_intent_failed=ProviderUnavailable"


@pytest.mark.parametrize("register", list(Language))
async def test_a_worry_about_a_child_gets_the_fixed_steps_and_the_helpline_never_a_lesson(
    register: Language,
) -> None:
    # critic review D2, 2026-11-01: a welfare concern must never get a lesson plan
    layer_with_reader, llm = reading_layer(teacher_reading("concern", "Force and Pressure"))
    text = "ek bachcha roz chot ke nishaan lekar aata hai, kal Force and Pressure padhana hai"
    result = await layer_with_reader.generate(teacher_ctx(text, [LAST_BRIDGE]), text, [], register)
    assert result.reply.body == TEACHER_CONCERN[register]
    assert CHILD_HELPLINE.number in result.reply.body
    assert llm.by_prompt["exposure"].prompts == []
    assert llm.by_prompt["teaching_answer"].prompts == []
    assert result.reply.buttons == []
    assert result.prompt_versions == {"teacher_intent": "1.3.0"}


async def test_a_message_not_about_teaching_gets_an_honest_reply_and_no_bridge() -> None:
    layer_with_reader, llm = reading_layer(teacher_reading("out_of_scope"))
    text = "mera transfer kaise hoga"
    result = await layer_with_reader.generate(teacher_ctx(text, [LAST_BRIDGE]), text, [], E)
    assert result.reply.body == TEACHER_OUT_OF_SCOPE[E]
    assert llm.by_prompt["exposure"].prompts == []
    assert llm.by_prompt["teaching_answer"].prompts == []
    assert result.outcome is StepOutcome.OK
    assert result.step_note == "off_topic=true"  # counted, like a parent's


async def test_a_teachers_question_about_marg_is_answered_not_turned_away() -> None:
    # owner, 2026-11-01: "do you sell our data?" got "I can't help with that"
    layer_with_reader, llm = reading_layer(teacher_reading("about_marg"))
    text = "do you sell our data?"
    result = await layer_with_reader.generate(teacher_ctx(text, [LAST_BRIDGE]), text, [], E)
    assert result.reply.body == ABOUT_MARG_REPLY["answer"]
    assert llm.by_prompt["exposure"].prompts == []
    assert result.prompt_versions == {"teacher_intent": "1.3.0", "about_marg": "1.2.0"}


async def test_a_teacher_who_wants_to_be_a_parent_is_told_how() -> None:
    layer_with_reader, llm = reading_layer(teacher_reading("other_role"))
    text = "I want to use this as a parent for my own child"
    result = await layer_with_reader.generate(teacher_ctx(text, [LAST_BRIDGE]), text, [], E)
    assert result.reply.body == OTHER_ROLE_REPLY[E]
    assert llm.by_prompt["exposure"].prompts == []


def test_the_concern_reply_gives_the_sourced_helpline_in_every_language() -> None:
    # the number is copied from an official page (crisis_replies), never typed into copy
    for register in Language:
        assert f"{CHILD_HELPLINE.number}" in TEACHER_CONCERN[register]
    assert CHILD_HELPLINE.source_url.endswith(".gov.in")


@pytest.mark.parametrize("text", ["Ok", "ok ji", "thank you", "👍"])
async def test_a_teachers_ok_is_answered_at_once_never_out_of_scope(text: str) -> None:
    # owner's field test, 2026-11-02: "Ok" got "I can't help with that"
    layer_with_reader, llm = reading_layer(teacher_reading("out_of_scope"))
    result = await layer_with_reader.generate(teacher_ctx(text, [LAST_BRIDGE]), text, [], E)
    assert result.reply.body == TEACHER_ACKNOWLEDGED[E]
    assert llm.by_prompt["teacher_intent"].prompts == []


@pytest.mark.parametrize("text", ["Namaste", "hello ji", "good morning"])
async def test_a_teachers_hello_is_answered_at_once(text: str) -> None:
    layer_with_reader, llm = reading_layer(teacher_reading("out_of_scope"))
    result = await layer_with_reader.generate(teacher_ctx(text, [LAST_BRIDGE]), text, [], E)
    assert result.reply.body == TEACHER_HELLO[E]
    assert llm.by_prompt["teacher_intent"].prompts == []


async def test_a_teachers_second_ok_in_a_row_is_said_differently() -> None:
    said = Exchange(user_text="ok", reply_text=TEACHER_ACKNOWLEDGED[E], route=Route.EXPOSURE, at=AT)
    layer_with_reader, _ = reading_layer(teacher_reading("out_of_scope"))
    result = await layer_with_reader.generate(teacher_ctx("ok", [said]), "ok", [], E)
    assert result.reply.body == ACKNOWLEDGED_AGAIN[E]


async def test_buttons_never_call_the_reader() -> None:
    layer_with_reader, llm = reading_layer(teacher_reading("teaching"))
    await layer_with_reader.generate(teacher_ctx("", [LAST_BRIDGE]), "", [MORE_ACTIVITY], E)
    assert llm.by_prompt["teacher_intent"].prompts == []


@pytest.mark.parametrize(
    ("first_line", "topic"),
    [
        ("Topic: Newton's laws of motion (class 9)", "Newton's laws of motion"),
        ("Chapter: Bal aur dabav (class 8)", "Bal aur dabav"),
        ("अध्याय: बल और दाब", "बल और दाब"),
        ("अध्याय: गणित (कक्षा 6)", "गणित"),
        ("Which chapter are you teaching next?", None),
    ],
)
def test_the_last_chapter_is_read_from_the_last_teacher_reply(
    first_line: str, topic: str | None
) -> None:
    earlier = LAST_BRIDGE.model_copy(update={"reply_text": f"{first_line}\nmore"})
    assert ExposureLayer.last_topic([earlier]) == topic


@pytest.mark.parametrize(
    "text", ["Use a projector to show it.", "Ask them to buy a magnet.", "A mechanic earns 2 lakh."]
)
def test_teaching_help_needing_a_device_purchase_or_money_is_sent_back(text: str) -> None:
    answer = TeachingAnswer.model_validate({**TEACHING, "opening": text})
    assert TeachingLayer.problems(answer, E) != []
