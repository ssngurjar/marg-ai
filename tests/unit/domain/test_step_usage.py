"""StepUsage.total: one turn_steps row for a step that made several provider calls."""

from decimal import Decimal

import pytest

from app.domain.models.usage import StepUsage

pytestmark = pytest.mark.unit


def usage(provider: str | None, model: str | None, tokens: int, cost: str) -> StepUsage:
    return StepUsage(
        provider=provider,
        model=model,
        input_tokens=tokens,
        output_tokens=tokens // 10,
        audio_seconds=None,
        cost_usd=Decimal(cost),
    )


def test_no_calls_have_no_usage() -> None:
    assert StepUsage.total([]) is None


def test_calls_are_added_up_and_named_in_order() -> None:
    total = StepUsage.total(
        [
            usage("llama_guard", "meta-llama/Llama-Guard-4-12B", 200, "0.000040"),
            usage("meta_model_api", "muse-spark-1.3", 700, "0.001200"),
        ]
    )
    assert total == StepUsage(
        provider="llama_guard+meta_model_api",
        model="meta-llama/Llama-Guard-4-12B+muse-spark-1.3",
        input_tokens=900,
        output_tokens=90,
        audio_seconds=None,
        cost_usd=Decimal("0.001240"),
    )


def test_a_repeated_provider_is_named_once_and_missing_names_are_skipped() -> None:
    total = StepUsage.total(
        [usage("meta_model_api", "m", 10, "0.1"), usage("meta_model_api", None, 10, "0.2")]
    )
    assert total is not None
    assert total.provider == "meta_model_api"
    assert total.model == "m"
    assert total.cost_usd == Decimal("0.3")


def test_unnamed_calls_give_no_name() -> None:
    total = StepUsage.total([usage(None, None, 1, "0")])
    assert total is not None
    assert (total.provider, total.model) == (None, None)
