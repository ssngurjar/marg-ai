"""ParentQuestionLayer: one warm answer in the parent's register (s10b §4.9 flow D, S5 exit)."""

from dataclasses import replace
from pathlib import Path

import pytest

from app.core.errors import ProviderUnavailable
from app.domain.enums import Language, StepOutcome
from app.layers.parent_question_layer import ParentAnswer, ParentQuestionLayer
from app.prompts.prompt_registry import SPOKEN_TEXT_OFF, PromptRegistry, PromptSettings
from app.wiring import PROMPT_SPECS
from tests.fakes.language_model import FakeLanguageModel
from tests.support.parent_answers import ANSWER_IN, ENGLISH_ANSWER, HINDI_ANSWER, HINGLISH_ANSWER
from tests.support.prompts import TEST_PROMPT_SETTINGS, shipped_registry
from tests.support.turn_context import text_message, turn_context

pytestmark = pytest.mark.unit

QUESTION = "Beta ko rang kaise sikhayein?"


def layer_with(llm: FakeLanguageModel, max_chars: int = 4000) -> ParentQuestionLayer:
    registry = PromptRegistry(
        specs=PROMPT_SPECS,
        settings=PromptSettings(
            models={
                "MODEL_TEXT": "muse-spark-1.3",
                "OPEN_MODEL": "meta-models/muse-spark-open",
                "MODEL_JUDGE": "muse-spark-1.3",
            },
            reasoning_effort="minimal",
            user_slot_max_chars=max_chars,
        ),
    )
    return ParentQuestionLayer(llm, registry)


@pytest.mark.parametrize("register", list(Language))
async def test_the_reply_is_the_answer_then_one_thing_to_try(register: Language) -> None:
    scripted = ANSWER_IN[register]
    llm = FakeLanguageModel([scripted])
    result = await layer_with(llm).answer(turn_context(text_message(QUESTION)), QUESTION, register)
    assert result.reply.body == f"{scripted['answer']}\n\n{scripted['try_this']}"
    assert result.reply.spoken_text == scripted["spoken_text"]
    assert result.reply.body_language is register
    assert result.outcome is StepOutcome.OK
    assert result.degraded_reason is None
    assert result.prompt_versions == {"parent_answer": "1.5.0"}
    assert len(result.usages) == 1


@pytest.mark.parametrize("register", list(Language))
async def test_the_prompt_carries_the_registers_rules(register: Language) -> None:
    llm = FakeLanguageModel([ANSWER_IN[register]])
    await layer_with(llm).answer(turn_context(text_message(QUESTION)), QUESTION, register)
    prompt = llm.prompts[0]
    assert ParentQuestionLayer.LANGUAGE_RULES[register] in prompt.system
    assert ParentQuestionLayer.SPOKEN_RULES[register] in prompt.system
    assert QUESTION not in prompt.system
    assert prompt.user == f"<parent_message>\n{QUESTION}\n</parent_message>\n"


async def test_a_message_cut_to_fit_is_a_degraded_answer() -> None:
    llm = FakeLanguageModel([HINGLISH_ANSWER])
    long_question = "Mera beta bahut sawal poochta hai " * 10
    result = await layer_with(llm, max_chars=40).answer(
        turn_context(text_message(long_question)), long_question, Language.HINGLISH
    )
    assert result.outcome is StepOutcome.DEGRADED
    assert result.degraded_reason == "truncated=true"


async def test_a_provider_failure_propagates_to_the_orchestrator() -> None:
    llm = FakeLanguageModel([ProviderUnavailable("503", provider="meta_model_api")])
    with pytest.raises(ProviderUnavailable, match="503"):
        await layer_with(llm).answer(
            turn_context(text_message(QUESTION)), QUESTION, Language.HINGLISH
        )


@pytest.mark.parametrize(
    ("answer", "register"),
    [
        (HINGLISH_ANSWER, Language.HINGLISH),
        (HINDI_ANSWER, Language.HINDI),
        (ENGLISH_ANSWER, Language.ENGLISH),
    ],
)
def test_a_reply_in_the_right_scripts_has_no_problems(
    answer: dict[str, object], register: Language
) -> None:
    assert ParentQuestionLayer.script_problems(ParentAnswer.model_validate(answer), register) == []


@pytest.mark.parametrize(
    ("answer", "register", "problems"),
    [
        (HINGLISH_ANSWER, Language.HINDI, ["answer, try_this: expected Devanagari script"]),
        (HINDI_ANSWER, Language.HINGLISH, ["answer, try_this: expected Roman script"]),
        (
            HINDI_ANSWER,
            Language.ENGLISH,
            [
                "answer, try_this: expected Roman script",
                "spoken_text: expected English in Roman script",
            ],
        ),
        (ENGLISH_ANSWER, Language.HINGLISH, ["spoken_text: expected Devanagari script"]),
    ],
)
def test_a_reply_in_the_wrong_script_is_sent_back_for_repair(
    answer: dict[str, object], register: Language, problems: list[str]
) -> None:
    parsed = ParentAnswer.model_validate(answer)
    assert ParentQuestionLayer.script_problems(parsed, register) == problems


def test_problems_never_quote_the_reply() -> None:
    wrong = ParentAnswer.model_validate(HINGLISH_ANSWER)
    for problem in ParentQuestionLayer.script_problems(wrong, Language.HINDI):
        assert str(HINGLISH_ANSWER["answer"]) not in problem


@pytest.mark.parametrize(
    "fields",
    [
        {"answer": "", "try_this": "x", "spoken_text": "x", "off_topic": False},
        {"answer": "x" * 501, "try_this": "x", "spoken_text": "x", "off_topic": False},
        {"answer": "x", "try_this": "x" * 201, "spoken_text": "x", "off_topic": False},
        {"answer": "x", "try_this": "x", "spoken_text": "x" * 901, "off_topic": False},
        {"answer": "x", "try_this": "x", "spoken_text": "x"},
        {"answer": "x", "try_this": "x", "spoken_text": "x", "off_topic": False, "extra": "x"},
        {"answer": "x", "try_this": "", "spoken_text": "x", "off_topic": False},
    ],
    ids=[
        "empty-answer",
        "long-answer",
        "long-try",
        "long-spoken",
        "missing",
        "extra",
        "no-tip-on-topic",
    ],
)
def test_the_output_model_rejects_bad_shapes(fields: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="validation error for ParentAnswer"):
        ParentAnswer.model_validate(fields)


def test_a_parent_answer_naming_a_hazard_gets_a_repair_turn_naming_the_word() -> None:
    # d7 blocks any hazard in a parent's answer at safety_out; the model first gets to rephrase
    answer = ParentAnswer.model_validate(
        {
            "answer": "Bachche ko chhat par mat jaane dijiye.",
            "try_this": "Aaj aangan mein khel kheliye.",
            "spoken_text": "बच्चे को छत पर मत जाने दीजिए। आज आँगन में खेल खेलिए।",
            "off_topic": False,
        }
    )
    problems = ParentQuestionLayer.script_problems(answer, Language.HINGLISH)
    assert any('"chhat"' in problem and '"छत"' in problem for problem in problems)


# --- voice replies off: no spoken text is written (owner, 2026-11-01) ----------------------------

VOICE_OFF = PromptRegistry(
    specs=PROMPT_SPECS, settings=replace(TEST_PROMPT_SETTINGS, voice_replies=False)
)
NO_SPOKEN_TEXT = {**HINGLISH_ANSWER, "spoken_text": ""}


async def test_with_voice_replies_off_the_prompt_asks_for_no_spoken_text() -> None:
    llm = FakeLanguageModel([NO_SPOKEN_TEXT])
    layer = ParentQuestionLayer(llm, VOICE_OFF)
    text = "bachcha khana nahi khata"
    result = await layer.answer(turn_context(text_message(text)), text, Language.HINGLISH)
    [prompt] = llm.prompts
    assert SPOKEN_TEXT_OFF in prompt.system
    assert "Devanagari script" not in prompt.system.split("Language:")[1].split("Fill")[1]
    assert result.reply.body.startswith(str(HINGLISH_ANSWER["answer"]))


async def test_with_voice_replies_on_an_empty_spoken_text_is_sent_back_for_repair() -> None:
    llm = FakeLanguageModel([NO_SPOKEN_TEXT])
    layer = layer_with(llm)
    text = "bachcha khana nahi khata"
    with pytest.raises(AssertionError, match="semantic check"):
        await layer.answer(turn_context(text_message(text)), text, Language.HINGLISH)


async def test_with_voice_replies_off_every_written_problem_still_counts() -> None:
    wrong_script = {**NO_SPOKEN_TEXT, "answer": "बच्चा खाना नहीं खाता तो धीरज रखिए।"}
    llm = FakeLanguageModel([wrong_script])
    layer = ParentQuestionLayer(llm, VOICE_OFF)
    text = "bachcha khana nahi khata"
    with pytest.raises(AssertionError, match="semantic check"):
        await layer.answer(turn_context(text_message(text)), text, Language.HINGLISH)


# --- off-topic messages (the bar-joke review, owner 2026-11-01) -----------------------------------

OFF_TOPIC = {
    "answer": "Ration card mein Marg madad nahi kar sakta. Gram panchayat ya CSC par poochiye.",
    "try_this": "",
    "spoken_text": "राशन कार्ड में मार्ग मदद नहीं कर सकता। ग्राम पंचायत या सी एस सी पर पूछ लीजिए।",
    "off_topic": True,
}


async def test_an_off_topic_message_gets_no_tip_and_is_counted() -> None:
    llm = FakeLanguageModel([OFF_TOPIC])
    layer = ParentQuestionLayer(llm, shipped_registry())
    text = "ration card banwana hai"
    result = await layer.answer(turn_context(text_message(text)), text, Language.HINGLISH)
    assert result.reply.body == OFF_TOPIC["answer"]
    assert result.step_note == "off_topic=true"
    assert result.outcome is StepOutcome.OK


async def test_an_answer_about_the_child_is_not_counted_as_off_topic() -> None:
    llm = FakeLanguageModel([HINGLISH_ANSWER])
    layer = ParentQuestionLayer(llm, shipped_registry())
    text = "bachcha khana nahi khata"
    result = await layer.answer(turn_context(text_message(text)), text, Language.HINGLISH)
    assert result.step_note is None


def test_an_empty_tip_is_allowed_only_off_topic() -> None:
    assert ParentAnswer.model_validate(OFF_TOPIC).try_this == ""
    with pytest.raises(ValueError, match="try_this is empty"):
        ParentAnswer.model_validate({**OFF_TOPIC, "off_topic": False})


def test_the_prompt_points_to_where_to_ask_and_names_the_models() -> None:
    system = " ".join(Path("app/prompts/parent_answer.md.j2").read_text(encoding="utf-8").split())
    for place in ("gram panchayat", "anganwadi", "CSC (Common Service Centre)"):
        assert place in system
    assert "Meta's Muse Spark" in system
    assert "Never say what a scheme gives" in system
    assert "never tell them to wait and see" in system
    assert "never say it is too early" in system
