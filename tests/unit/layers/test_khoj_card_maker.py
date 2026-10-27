"""KhojCardMaker: the caption and the picture (s10b §4.13, C6)."""

import dataclasses

import pytest

from app.constants.child_hazards import CHILD_HAZARD_WORDS
from app.constants.khoj_card_style import ACTIVITY_SCENES, CARD_STYLE, DOMAIN_SCENES
from app.core.errors import ProviderUnavailable
from app.domain.enums import CuriosityDomain, Language
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.layers.khoj_card_maker import CardRequest, KhojCardMaker, KhojCardText, _CaptionChecks
from tests.fakes.image import TINY_PNG, FakeImageGenerator
from tests.fakes.language_model import FakeLanguageModel
from tests.support.journey import CARD_HEADLINE, CARD_TEXT
from tests.support.prompts import shipped_registry

pytestmark = pytest.mark.unit

SUMMARY = "Munni noticed the shadow moved during the day and asked where it goes at night."
REQUEST = CardRequest(
    activity_id="shadow-time",
    activity_title="Parchhai ka khel",
    domains=[CuriosityDomain.EARTH_SKY],
    child_nickname="Munni",
    summary=SUMMARY,
    register=Language.HINGLISH,
)


async def test_a_card_has_the_caption_and_a_png() -> None:
    images = FakeImageGenerator()
    llm = FakeLanguageModel([CARD_TEXT])
    card = await KhojCardMaker(llm, images, shipped_registry()).make(REQUEST)
    assert card.caption.text.startswith(CARD_HEADLINE)
    assert card.image.data == TINY_PNG
    assert len(card.usages) == 2
    assert card.prompt_versions == {"khoj_card_text": "1.0.0"}
    assert "Munni" in llm.prompts[0].user
    assert "Munni" not in llm.prompts[0].system


async def test_the_image_prompt_never_holds_the_childs_name_or_the_parents_words() -> None:
    images = FakeImageGenerator()
    await KhojCardMaker(FakeLanguageModel([CARD_TEXT]), images, shipped_registry()).make(REQUEST)
    [prompt] = images.prompts
    assert prompt == CARD_STYLE + ACTIVITY_SCENES["shadow-time"]
    assert "Munni" not in prompt
    assert "noticed" not in prompt


def test_an_activity_without_a_scene_uses_its_domain_then_a_generic_one() -> None:
    unknown = dataclasses.replace(REQUEST, activity_id="new-one")
    assert KhojCardMaker.image_prompt(unknown).endswith(DOMAIN_SCENES[CuriosityDomain.EARTH_SKY])
    bare = dataclasses.replace(REQUEST, activity_id="new-one", domains=[])
    assert KhojCardMaker.image_prompt(bare).endswith(KhojCardMaker.GENERIC_SCENE)


async def test_an_image_failure_is_raised() -> None:
    images = FakeImageGenerator(error=ProviderUnavailable("503", provider="meta_model_api"))
    maker = KhojCardMaker(FakeLanguageModel([CARD_TEXT]), images, shipped_registry())
    with pytest.raises(ProviderUnavailable, match="503"):
        await maker.make(REQUEST)


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"headline": "Munni toh genius hai!"}, "text: labels the child"),
        ({"line": "Badi hokar doctor banegi."}, "text: mentions careers"),
        ({"line": "Talab ke paas parchhai dekhi."}, "text: mentions a danger"),
        ({"headline": "मुन्नी ने परछाई देखी!"}, "text: expected Roman script"),
    ],
)
def test_the_caption_checks_catch_each_problem(changes: dict[str, str], problem: str) -> None:
    text = KhojCardText.model_validate({**CARD_TEXT, **changes})
    problems = _CaptionChecks.problems(text, Language.HINGLISH)
    assert any(found.startswith(problem) for found in problems), problems


def test_every_scene_is_free_of_hazards_for_a_child() -> None:
    """Regression: "snake-like rope" and "river-washed stones" were in the first draft."""
    for scene in [*ACTIVITY_SCENES.values(), *DOMAIN_SCENES.values()]:
        assert not ChildHazardMatcher.find(scene, CHILD_HAZARD_WORDS), scene
