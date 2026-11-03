"""Wiring with only a Meta Model API key: no Llama Guard, no Baseten (2026-11-03).

A judge who runs Marg locally has a Meta key and nothing else; the Muse Spark checks decide
every message in and out, and Spark 1.3 runs the reflection prompts, as when those hosts are down.
"""

import pytest

from app.core.clock import SystemClock
from app.core.config import Settings
from app.providers.llm.fallback_language_model import FallbackLanguageModel
from app.store.db import create_engine, create_session_factory
from app.wiring import Providers, build_container, build_providers, build_retry, close_providers
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.unit

NO_GUARD = {"safety_base_url": None, "safety_api_key": None}
NO_OPEN_MODEL = {"open_model_base_url": None, "open_model_api_key": None}


def settings_without(*missing: dict[str, None]) -> Settings:
    update: dict[str, None] = {}
    for fields in missing:
        update.update(fields)
    return make_settings().model_copy(update=update)


def providers_for(settings: Settings) -> Providers:
    clock = SystemClock()
    session_factory = create_session_factory(create_engine(settings))
    return build_providers(settings, session_factory, build_retry(clock), clock)


async def test_with_only_a_meta_key_spark_does_everything_and_nothing_else_is_built() -> None:
    providers = providers_for(settings_without(NO_GUARD, NO_OPEN_MODEL))
    assert providers.safety_classifier is None
    assert providers.open_model is None
    assert providers.language_model is providers.spark
    assert providers.language_models == (providers.spark,)
    await close_providers(providers)


async def test_with_every_host_set_llama_guard_and_the_open_model_fallback_are_built() -> None:
    providers = providers_for(make_settings())
    assert providers.safety_classifier is not None
    assert providers.open_model is not None
    assert isinstance(providers.language_model, FallbackLanguageModel)
    assert providers.language_models == (providers.spark, providers.open_model)
    await close_providers(providers)


@pytest.mark.parametrize(
    ("missing", "guard", "open_model"),
    [(NO_GUARD, False, True), (NO_OPEN_MODEL, True, False)],
    ids=["no-llama-guard", "no-baseten"],
)
async def test_each_host_is_optional_on_its_own(
    missing: dict[str, None], *, guard: bool, open_model: bool
) -> None:
    providers = providers_for(settings_without(missing))
    assert (providers.safety_classifier is not None) is guard
    assert (providers.open_model is not None) is open_model
    await close_providers(providers)


def probe_names(settings: Settings) -> list[str]:
    return [probe.name for probe in build_container(settings).readiness_probes]


def test_without_llama_guard_readiness_does_not_probe_a_safety_host() -> None:
    assert "safety" not in probe_names(settings_without(NO_GUARD, NO_OPEN_MODEL))
    assert "model_api" in probe_names(settings_without(NO_GUARD, NO_OPEN_MODEL))


def test_with_llama_guard_readiness_probes_it() -> None:
    assert "safety" in probe_names(make_settings())


def test_the_container_builds_with_only_a_meta_key() -> None:
    container = build_container(settings_without(NO_GUARD, NO_OPEN_MODEL))
    assert container.safety_classifier is None
    assert len(container.language_models) == 1
