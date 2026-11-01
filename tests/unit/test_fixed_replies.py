"""The reviewed fixed replies say what is true for whoever reads them (owner's field test)."""

import pytest

from app.constants.fixed_replies import FIXED_TEXTS, FixedTextKey
from app.domain.enums import FixedReplyKind, FixedReplyVariant, Language

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("language", list(Language))
def test_the_general_refusal_never_assumes_a_parent(language: Language) -> None:
    # 2026-11-01: a student was told "let's talk about the child's khoj"
    key = FixedTextKey(FixedReplyKind.REFUSE, FixedReplyVariant.GENERAL, language)
    text = FIXED_TEXTS[key].text.casefold()
    for parent_word in ("bachche", "khoj", "child", "बच्चे", "खोज"):
        assert parent_word not in text
