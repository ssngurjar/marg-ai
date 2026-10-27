"""Crisis replies: helplines are sourced, every language exists, numbers read digit by digit."""

from datetime import date
from urllib.parse import urlparse

import pytest

from app.constants.crisis_replies import CRISIS_TEXTS, HELPLINES, Helpline
from app.domain.enums import FixedReplyVariant, Language

pytestmark = pytest.mark.unit

OFFICIAL_SUFFIXES = (".gov.in", ".nic.in")


@pytest.mark.parametrize("helpline", HELPLINES, ids=lambda helpline: helpline.name)
def test_every_helpline_comes_from_an_official_page_that_states_its_number(
    helpline: Helpline,
) -> None:
    host = urlparse(helpline.source_url).hostname or ""
    assert urlparse(helpline.source_url).scheme == "https"
    assert host.endswith(OFFICIAL_SUFFIXES), host
    assert helpline.number in helpline.quoted
    assert date(2026, 1, 1) <= helpline.retrieved_on


@pytest.mark.parametrize("variant", [FixedReplyVariant.SELF_HARM, FixedReplyVariant.ABUSE])
@pytest.mark.parametrize("language", list(Language))
def test_every_crisis_variant_exists_in_every_language(
    variant: FixedReplyVariant, language: Language
) -> None:
    assert (variant, language) in CRISIS_TEXTS


def test_texts_show_the_number_and_speech_reads_it_digit_by_digit() -> None:
    for (variant, _), crisis in CRISIS_TEXTS.items():
        number = "14416" if variant is FixedReplyVariant.SELF_HARM else "1098"
        assert number in crisis.text
        assert " ".join(number) in crisis.spoken_text
        assert number not in crisis.spoken_text


def test_no_template_placeholder_is_left_unfilled() -> None:
    for crisis in CRISIS_TEXTS.values():
        assert "{" not in crisis.text
        assert "{" not in crisis.spoken_text
