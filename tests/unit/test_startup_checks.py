"""check_startup: a bad configuration fails the deploy, not a user's turn (s05 §4.1, §4.3)."""

import pytest

from app.core.errors import ConfigError
from app.wiring import check_startup
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.unit


def test_the_default_configuration_passes() -> None:
    check_startup(make_settings())


def test_a_contributor_model_on_user_content_refuses_to_start() -> None:
    settings = make_settings().model_copy(update={"model_text": "muse-spark-1.3-contributor"})
    with pytest.raises(
        ConfigError, match=r"MODEL_TEXT=muse-spark-1\.3-contributor may not be used"
    ):
        check_startup(settings)


def test_an_unpriced_text_model_refuses_to_start() -> None:
    settings = make_settings().model_copy(update={"model_text": "some-new-model"})
    with pytest.raises(ConfigError, match="no price recorded for model 'some-new-model'"):
        check_startup(settings)


def test_an_unpriced_safety_model_refuses_to_start() -> None:
    settings = make_settings().model_copy(update={"safety_model": "llama-guard-3-8b"})
    with pytest.raises(ConfigError, match="no price recorded for model 'llama-guard-3-8b'"):
        check_startup(settings)
