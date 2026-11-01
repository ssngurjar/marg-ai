"""Questions about Marg itself, answered only from the reviewed facts (owner, 2026-11-01)."""

import re

import pytest

from app.constants.crisis_replies import CHILD_HELPLINE, TELE_MANAS
from app.constants.marg_facts import MARG_FACTS
from app.core.config import Settings
from app.domain.enums import Language, Role, StepOutcome
from app.layers.about_marg_layer import AboutMargAnswer, AboutMargLayer
from app.layers.layer_result import LayerResult
from tests.fakes.language_model import FakeLanguageModel
from tests.support.prompts import shipped_registry
from tests.support.turn_context import text_message, turn_context, user_profile

pytestmark = pytest.mark.unit

ANSWER = {
    "answer": "Marg har sandesh ko bhejne se pehle suraksha ke liye jaanchta hai.",
    "unknown": False,
    "spoken_text": "मार्ग हर संदेश को भेजने से पहले सुरक्षा के लिए जाँचता है।",
}
UNKNOWN = {**ANSWER, "unknown": True}


async def ask(
    scripted: dict[str, object], role: Role | None = Role.PARENT
) -> tuple[LayerResult, FakeLanguageModel]:
    llm = FakeLanguageModel([scripted])
    layer = AboutMargLayer(llm, shipped_registry())
    text = "how do you keep my child safe?"
    ctx = turn_context(text_message(text), profile=user_profile(role=role))
    return await layer.answer(ctx, text, Language.HINGLISH), llm


async def test_the_answer_comes_from_the_reviewed_facts_and_is_counted() -> None:
    result, llm = await ask(ANSWER)
    [prompt] = llm.prompts
    for fact in MARG_FACTS:
        for_parents = fact.roles is None or Role.PARENT in fact.roles
        assert (fact.text in prompt.system) is for_parents
    assert result.reply.body == ANSWER["answer"]
    assert result.step_note == "about_marg=true"
    assert result.outcome is StepOutcome.OK


async def test_a_question_the_facts_dont_answer_is_counted_as_unknown() -> None:
    result, _ = await ask(UNKNOWN)
    assert result.step_note == "about_marg=unknown"


@pytest.mark.parametrize(
    ("role", "named"),
    [
        (Role.PARENT, "parent"),
        (Role.STUDENT, "student"),
        (Role.TEACHER, "teacher"),
        (None, "person"),
    ],
)
async def test_the_prompt_names_who_is_asking(role: Role | None, named: str) -> None:
    _, llm = await ask(ANSWER, role)
    assert f"A {named} is asking about Marg" in llm.prompts[0].system


async def test_the_question_is_data_in_its_own_slot() -> None:
    _, llm = await ask(ANSWER)
    assert "how do you keep my child safe?" not in llm.prompts[0].system


@pytest.mark.parametrize(
    "fields",
    [
        {"answer": "", "unknown": False, "spoken_text": "x"},
        {"answer": "x" * 501, "unknown": False, "spoken_text": "x"},
        {"answer": "x", "spoken_text": "x"},
        {"answer": "x", "unknown": False, "spoken_text": "x", "extra": "x"},
    ],
    ids=["empty", "long", "missing-unknown", "extra"],
)
def test_the_output_model_rejects_bad_shapes(fields: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="validation error for AboutMargAnswer"):
        AboutMargAnswer.model_validate(fields)


def test_a_wrong_script_gets_a_repair_turn() -> None:
    english = AboutMargAnswer.model_validate(
        {"answer": "Every message is checked.", "unknown": False, "spoken_text": "x"}
    )
    problems = AboutMargLayer.script_problems(english, Language.HINDI)
    assert any(problem.startswith("answer:") for problem in problems)


# --- the facts stay true: every number comes from the code or a sourced helpline ----------------


def test_the_child_talk_limits_in_the_facts_are_the_settings_defaults() -> None:
    fields = Settings.model_fields
    turns = fields["child_session_max_turns"].default
    minutes = fields["child_session_max_minutes"].default
    [fact] = [fact for fact in MARG_FACTS if fact.topic == "a child talking to Marg"]
    assert f"after {turns} questions or {minutes} minutes" in fact.text


def test_the_retention_in_the_facts_is_the_settings_default() -> None:
    days = Settings.model_fields["retention_turn_text_days"].default
    [fact] = [fact for fact in MARG_FACTS if fact.topic == "how long messages are kept"]
    assert f"after {days} days" in fact.text


def test_the_facts_say_replies_are_written_only_while_voice_replies_are_off() -> None:
    # "you can listen to the khoj" was invented once; this fact must change with the setting
    assert Settings.model_fields["voice_replies_enabled"].default is False
    [fact] = [fact for fact in MARG_FACTS if fact.topic == "can't read or write"]
    assert "Marg replies in writing" in fact.text


def test_every_number_in_the_facts_is_accounted_for() -> None:
    allowed = {
        "3", "8", "6", "12", "10", "90", "2023",
        CHILD_HELPLINE.number, TELE_MANAS.number,
    }  # fmt: skip
    for fact in MARG_FACTS:
        unexplained = set(re.findall(r"\d+", fact.text)) - allowed
        assert unexplained == set(), (fact.topic, unexplained)


def test_every_fact_names_the_code_that_makes_it_true() -> None:
    assert all(fact.where.strip() for fact in MARG_FACTS)
    topics = [(fact.topic, fact.roles) for fact in MARG_FACTS]
    assert len(topics) == len(set(topics))


@pytest.mark.parametrize(
    ("role", "says", "never"),
    [
        (Role.PARENT, "that you are a parent", "your class, your district"),
        (Role.STUDENT, "your class, your district", "that you are a parent"),
        (Role.TEACHER, "your subject, the class you teach", "that you are a student"),
    ],
)
def test_each_role_hears_only_what_marg_keeps_about_them(role: Role, says: str, never: str) -> None:
    # owner's field test, 2026-11-01: a parent was told Marg keeps their class and district
    facts = AboutMargLayer.facts_for(role)
    assert says in facts
    assert never not in facts


def test_someone_without_a_role_gets_only_the_facts_true_for_everyone() -> None:
    facts = AboutMargLayer.facts_for(None)
    assert "- what Marg keeps:" not in facts
    assert "safety checks" in facts


def test_every_role_has_its_own_what_marg_keeps() -> None:
    for role in Role:
        assert AboutMargLayer.facts_for(role).count("- what Marg keeps:") == 1
