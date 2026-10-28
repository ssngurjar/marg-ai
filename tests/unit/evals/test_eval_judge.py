"""EvalJudge: every item answered once, a judge error never counted, votes combined (s15 §4.4)."""

import pytest

from app.core.errors import ProviderResponseInvalid, ProviderTimeout
from app.domain.models.eval_judgement import JudgeItem, JudgeScore
from app.evals.eval_judge import EvalJudge
from app.evals.golden_case import TurnExpectation
from app.wiring import EVAL_JUDGE
from tests.fakes.language_model import FakeLanguageModel
from tests.support.eval_records import case, record, source
from tests.support.prompts import shipped_registry

pytestmark = pytest.mark.unit

EXPECT = TurnExpectation(must=["gives an activity", "uses the nickname"], must_not=["sells"])
KINDS = ["must", "must", "must_not"]


def score(
    passes: tuple[bool, bool, bool] = (True, True, True), grounding: int = 4
) -> dict[str, object]:
    return {
        "items": [
            {"index": index, "kind": kind, "passed": passed, "reason": "the reply says so"}
            for index, (kind, passed) in enumerate(zip(KINDS, passes, strict=True))
        ],
        "grounding": grounding, "cultural_resonance": 5, "reading_level": 4,
        "actionability": 4, "safety": 5,
    }  # fmt: skip


def judge(llm: FakeLanguageModel, repeat: int = 1) -> EvalJudge:
    return EvalJudge(llm, shipped_registry(), EVAL_JUDGE, repeat)


async def test_the_judge_reads_the_items_sources_and_reply_but_not_the_expectations() -> None:
    llm = FakeLanguageModel([score()])
    judged = await judge(llm).judge(
        case(), ["Aaj ki khoj batao"], record(sources=[source()]), EXPECT
    )
    assert judged.score is not None
    [prompt] = llm.prompts
    assert "0. [must] gives an activity" in prompt.system
    assert "2. [must_not] sells" in prompt.system
    assert "NMMS is for class 8." in prompt.system  # the cited source, in full
    assert "child Munni, aged 5" in prompt.system
    assert "Aaj ki khoj batao" in prompt.user
    assert "journey" in prompt.system  # the route it took
    assert "hinglish" not in prompt.system.split("writes in")[0]  # no expected register given


@pytest.mark.parametrize(
    ("items", "problem"),
    [
        ([0, 1], "answer each index 0 to 2 exactly once"),
        ([0, 1, 1], "answer each index 0 to 2 exactly once"),
        ([0, 1, 2, 3], "answer each index 0 to 2 exactly once"),
    ],
)
def test_every_item_must_be_answered_exactly_once(items: list[int], problem: str) -> None:
    answers = [
        JudgeItem(index=index, kind="must" if index < 2 else "must_not", passed=True, reason="r")
        for index in items
    ]
    scored = JudgeScore.model_validate({**score(), "items": [a.model_dump() for a in answers]})
    assert problem in " | ".join(EvalJudge.problems(scored, KINDS))


def test_an_item_with_the_wrong_kind_is_a_problem() -> None:
    swapped = JudgeScore.model_validate(score())
    wrong = swapped.model_copy(
        update={"items": [*swapped.items[:2], swapped.items[2].model_copy(update={"kind": "must"})]}
    )
    assert EvalJudge.problems(wrong, KINDS) == ["item 2: kind is must_not"]


@pytest.mark.parametrize(
    "error",
    [
        ProviderResponseInvalid("still invalid after the repair", provider="meta_model_api"),
        ProviderTimeout("judge timed out", provider="meta_model_api"),
    ],
)
async def test_a_judge_that_fails_is_a_judge_error_not_a_verdict(error: Exception) -> None:
    llm = FakeLanguageModel([error])  # type: ignore[list-item]  # a scripted provider error
    judged = await judge(llm).judge(case(), ["x"], record(), EXPECT)
    assert judged.score is None
    assert judged.error == type(error).__name__


async def test_repeats_take_the_majority_per_item_and_the_median_score() -> None:
    llm = FakeLanguageModel(
        [
            score((True, False, True), grounding=2),
            score((True, False, False), grounding=5),
            score((True, True, False), grounding=4),
        ]
    )
    judged = await judge(llm, repeat=3).judge(case(), ["x"], record(), EXPECT)
    assert judged.score is not None
    assert [item.passed for item in judged.score.items] == [True, False, False]
    assert judged.score.grounding == 4
    assert len(llm.prompts) == 3


def test_a_tie_fails_the_item() -> None:
    combined = EvalJudge.combine(
        [
            JudgeScore.model_validate(score((True,) * 3)),
            JudgeScore.model_validate(score((False,) * 3)),
        ]
    )
    assert [item.passed for item in combined.items] == [False, False, False]


def test_a_new_user_is_described_without_a_profile() -> None:
    assert EvalJudge.describe(case(profile=None, learner=None)) == (
        "someone writing to Marg for the first time"
    )
