"""ModelPricing: cost accounting in Decimal, and no Contributor model on user content."""

import re
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import ConfigError
from app.providers.llm.model_pricing import ModelPricing

pytestmark = pytest.mark.unit

SPARK = "muse-spark-1.3"
TOKENS = st.integers(min_value=0, max_value=2_000_000)


def test_cost_uses_the_input_cached_and_output_rates() -> None:
    # 1000 uncached in at 1.25, 1000 cached at 0.15, 1000 out at 4.25, per million
    assert ModelPricing.cost_of(SPARK, 2000, 1000, 1000) == Decimal("0.005650")


def test_zero_tokens_cost_nothing() -> None:
    assert ModelPricing.cost_of(SPARK, 0, 0, 0) == Decimal("0.000000")


def test_cached_tokens_beyond_the_prompt_never_make_a_negative_cost() -> None:
    assert ModelPricing.cost_of(SPARK, 10, 50, 0) >= 0


@given(prompt=TOKENS, cached=TOKENS, completion=TOKENS, extra=st.integers(1, 1000))
def test_more_output_never_costs_less(
    prompt: int, cached: int, completion: int, extra: int
) -> None:
    assert ModelPricing.cost_of(SPARK, prompt, cached, completion + extra) >= ModelPricing.cost_of(
        SPARK, prompt, cached, completion
    )


def test_an_unpriced_model_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="no price recorded for model 'gpt-unknown'"):
        ModelPricing.price_of("gpt-unknown")


@pytest.mark.parametrize("model", ["muse-spark-1.3-contributor", "muse-spark-1.2-contributor"])
def test_a_contributor_model_is_refused_for_user_content(model: str) -> None:
    with pytest.raises(
        ConfigError, match=re.escape(f"MODEL_TEXT={model} may not be used on user content")
    ):
        ModelPricing.require_allowed_for_user_content(model, "MODEL_TEXT")


def test_the_default_models_are_allowed_for_user_content() -> None:
    ModelPricing.require_allowed_for_user_content(SPARK, "MODEL_TEXT")
    ModelPricing.require_allowed_for_user_content("meta-llama/Llama-Guard-4-12B", "SAFETY_MODEL")
