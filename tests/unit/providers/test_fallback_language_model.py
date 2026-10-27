"""FallbackLanguageModel: Muse Spark Open within 7 s, else Muse Spark 1.3 (s10b §4.8, C9)."""

from datetime import timedelta

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.errors import ProviderRejected, ProviderUnavailable
from app.providers.llm.fallback_language_model import FallbackLanguageModel, FallbackRoute
from app.providers.ports import GenerationRequest, RenderedPrompt
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
