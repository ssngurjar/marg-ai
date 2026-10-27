"""ModelPricing: what a call cost, and which models may see user content (s05 §4.1)."""

from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar

from app.constants.model_prices import MODEL_PRICES, ModelPrice
from app.core.errors import ConfigError


class ModelPricing:
    _MILLION: ClassVar[Decimal] = Decimal(1_000_000)
    _PLACES: ClassVar[Decimal] = Decimal("0.000001")

    @staticmethod
    def price_of(model: str) -> ModelPrice:
        price = MODEL_PRICES.get(model)
        if price is None:
            raise ConfigError(f"no price recorded for model {model!r}")
        return price

    @staticmethod
    def cost_of(
        model: str, prompt_tokens: int, cached_tokens: int, completion_tokens: int
    ) -> Decimal:
        """USD for one call. Completion tokens include reasoning, billed at the output rate."""
        price = ModelPricing.price_of(model)
        uncached = max(prompt_tokens - cached_tokens, 0)
        total = (
            Decimal(uncached) * price.input_per_million
            + Decimal(cached_tokens) * price.cached_input_per_million
            + Decimal(completion_tokens) * price.output_per_million
        ) / ModelPricing._MILLION
        return total.quantize(ModelPricing._PLACES, rounding=ROUND_HALF_UP)

    @staticmethod
    def require_allowed_for_user_content(model: str, setting_name: str) -> None:
        """Startup check: a model that sees user content must be priced and not Contributor-mode
        (Meta may train on Contributor content, and our users are mostly minors)."""
        price = ModelPricing.price_of(model)
        if not price.allowed_for_user_content:
            raise ConfigError(f"{setting_name}={model} may not be used on user content")
