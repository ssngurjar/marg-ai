"""ParentQuestionLayer: one warm answer in the parent's register (s10b §4.9 flow D, S5 exit)."""

import pytest

from app.core.errors import ProviderUnavailable
from app.domain.enums import Language, StepOutcome
from app.layers.parent_question_layer import PARENT_ANSWER, ParentAnswer, ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSettings
from tests.fakes.language_model import FakeLanguageModel
from tests.support.parent_answers import ANSWER_IN, ENGLISH_ANSWER, HINDI_ANSWER, HINGLISH_ANSWER
from tests.support.turn_context import text_message, turn_context

pytestmark = pytest.mark.unit

QUESTION = "Beta ko rang kaise sikhayein?"


def layer_with(llm: FakeLanguageModel, max_chars: int = 4000) -> ParentQuestionLayer:
    registry = PromptRegistry(
        specs=[PARENT_ANSWER],
        settings=PromptSettings(
            models={"MODEL_TEXT": "muse-spark-1.3"},
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
    assert result.prompt_versions == {"parent_answer": "1.0.0"}
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
        {"answer": "", "try_this": "x", "spoken_text": "x"},
        {"answer": "x" * 501, "try_this": "x", "spoken_text": "x"},
        {"answer": "x", "try_this": "x" * 201, "spoken_text": "x"},
        {"answer": "x", "try_this": "x", "spoken_text": "x" * 901},
        {"answer": "x", "try_this": "x"},
        {"answer": "x", "try_this": "x", "spoken_text": "x", "extra": "x"},
    ],
    ids=["empty-answer", "long-answer", "long-try", "long-spoken", "missing", "extra"],
)
def test_the_output_model_rejects_bad_shapes(fields: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="validation error for ParentAnswer"):
        ParentAnswer.model_validate(fields)
