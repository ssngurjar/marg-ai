"""FallbackLanguageModel: Muse Spark Open within 7 s, else Muse Spark 1.3 (s10b §4.8, C9)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.circuit_breaker import BreakerLimits
from app.core.errors import ProviderRejected, ProviderUnavailable
from app.core.provider_breaker import ProviderBreaker
from app.providers.llm.fallback_language_model import FallbackLanguageModel, FallbackRoute
from app.providers.ports import GenerationRequest, RenderedPrompt
from tests.fakes.clock import FixedClock
from tests.fakes.language_model import FakeLanguageModel, ScriptedOutput

pytestmark = pytest.mark.unit

OPEN = "meta-models/muse-spark-open"
SPARK = "muse-spark-1.3"


class Note(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    note: str


def request(model: str) -> GenerationRequest[Note]:
    return GenerationRequest[Note](
        prompt=RenderedPrompt(
            prompt_id="parent_reflection", prompt_version="1", system="s", user="u"
        ),
        output_type=Note,
        model=model,
        reasoning_effort="minimal",
        max_output_tokens=100,
        semantic_check=None,
    )


def models(
    primary: ScriptedOutput, *, primary_delay_s: float = 0.0
) -> tuple[FallbackLanguageModel, FakeLanguageModel, FakeLanguageModel]:
    open_model = FakeLanguageModel([primary], delay_s=primary_delay_s)
    spark = FakeLanguageModel([{"note": "from spark"}])
    route = FallbackRoute(OPEN, SPARK, primary_timeout=timedelta(milliseconds=50))
    return FallbackLanguageModel(open_model, spark, route), open_model, spark


async def test_the_open_model_answers_when_it_can() -> None:
    llm, open_model, spark = models({"note": "from open"})
    result = await llm.generate(request(OPEN))
    assert result.output.note == "from open"
    assert open_model.models == [OPEN]
    assert spark.prompts == []


@pytest.mark.parametrize(
    "failure",
    [ProviderUnavailable("503", provider="baseten"), ProviderRejected("401", provider="baseten")],
    ids=["unavailable", "rejected"],
)
async def test_an_open_model_failure_falls_back_to_spark(failure: ProviderUnavailable) -> None:
    llm, _, spark = models(failure)
    result = await llm.generate(request(OPEN))
    assert result.output.note == "from spark"
    assert len(spark.prompts) == 1


async def test_a_slow_open_model_is_cut_off_and_spark_answers() -> None:
    llm, open_model, spark = models({"note": "from open"}, primary_delay_s=5)
    result = await llm.generate(request(OPEN))
    assert result.output.note == "from spark"
    assert open_model.cancelled
    assert spark.models == [SPARK]


async def test_the_fallback_is_asked_with_its_own_model_id() -> None:
    llm, _, spark = models(ProviderUnavailable("503", provider="baseten"))
    await llm.generate(request(OPEN))
    assert spark.models == [SPARK]


async def test_other_prompts_go_straight_to_spark() -> None:
    llm, open_model, spark = models({"note": "from open"})
    result = await llm.generate(request(SPARK))
    assert result.output.note == "from spark"
    assert open_model.prompts == []
    assert spark.models == [SPARK]


# --- the Open model's breaker (owner, 2026-11-01) ------------------------------------------------

BREAKER_LIMITS = BreakerLimits(
    failures_to_open=2,
    failure_window=timedelta(seconds=60),
    open_for=timedelta(minutes=5),
    probe_every=timedelta(seconds=30),
)


def models_with_breaker(
    primary: ScriptedOutput,
) -> tuple[FallbackLanguageModel, FakeLanguageModel, FakeLanguageModel, FixedClock]:
    clock = FixedClock(datetime(2026, 11, 1, 8, 0, tzinfo=UTC))
    open_model = FakeLanguageModel([primary])
    spark = FakeLanguageModel([{"note": "from spark"}])
    route = FallbackRoute(OPEN, SPARK, primary_timeout=timedelta(milliseconds=50))
    breaker = ProviderBreaker("open_model", BREAKER_LIMITS, clock)
    return FallbackLanguageModel(open_model, spark, route, breaker), open_model, spark, clock


async def test_after_two_open_model_failures_requests_go_straight_to_spark() -> None:
    llm, open_model, spark, _ = models_with_breaker(ProviderUnavailable("503", provider="baseten"))
    for _ in range(3):
        result = await llm.generate(request(OPEN))
        assert result.output.note == "from spark"
    assert len(open_model.prompts) == 2  # the third request didn't wait for it
    assert spark.models == [SPARK, SPARK, SPARK]


async def test_after_five_minutes_the_open_model_is_tried_again() -> None:
    llm, open_model, _, clock = models_with_breaker(ProviderUnavailable("503", provider="baseten"))
    await llm.generate(request(OPEN))
    await llm.generate(request(OPEN))
    clock.advance(timedelta(minutes=5))
    await llm.generate(request(OPEN))
    assert len(open_model.prompts) == 3


async def test_a_success_between_failures_keeps_the_open_model_in_use() -> None:
    open_model = FakeLanguageModel(
        [ProviderUnavailable("503", provider="baseten"), {"note": "from open"}]
    )
    spark = FakeLanguageModel([{"note": "from spark"}])
    clock = FixedClock(datetime(2026, 11, 1, 8, 0, tzinfo=UTC))
    breaker = ProviderBreaker("open_model", BREAKER_LIMITS, clock)
    route = FallbackRoute(OPEN, SPARK, primary_timeout=timedelta(milliseconds=50))
    llm = FallbackLanguageModel(open_model, spark, route, breaker)
    await llm.generate(request(OPEN))  # fails: Spark answers
    await llm.generate(request(OPEN))  # works
    assert not breaker.is_open()


async def test_spark_requests_never_touch_the_open_models_breaker() -> None:
    llm, open_model, spark, _ = models_with_breaker({"note": "from open"})
    await llm.generate(request(SPARK))
    assert open_model.prompts == []
    assert spark.models == [SPARK]
