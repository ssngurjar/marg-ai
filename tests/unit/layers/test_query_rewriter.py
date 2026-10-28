"""QueryRewriter: the question as an English search, or the student's own words (s11 §4.6)."""

from datetime import UTC, datetime

import pytest

from app.core.errors import ProviderTimeout
from app.domain.enums import CorpusTopic, Route
from app.domain.models.turn import Exchange
from app.layers.query_rewriter import QueryRewriter
from tests.fakes.language_model import FakeLanguageModel
from tests.support.prompts import shipped_registry

pytestmark = pytest.mark.unit

AT = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
REWRITE = {
    "english_query": "Is there a scholarship for class 8 students?",
    "keywords": ["NMMS"],
    "topics": ["scholarships"],
}


async def test_a_rewrite_becomes_the_retrieval_query() -> None:
    llm = FakeLanguageModel([REWRITE])
    query, usage, failed = await QueryRewriter(llm, shipped_registry()).rewrite(
        "क्लास 8 में कोई स्कॉलरशिप मिलती है क्या", [], grade=8
    )
    assert query.english_query == REWRITE["english_query"]
    assert query.keywords == ["NMMS"]
    assert query.topics == [CorpusTopic.SCHOLARSHIPS]
    assert usage is not None
    assert failed is None
    [prompt] = llm.prompts
    assert "Student's class: 8" in prompt.system
    question = "क्लास 8 में कोई स्कॉलरशिप मिलती है क्या"
    assert question in prompt.user
    assert question not in prompt.system


async def test_the_last_two_exchanges_are_given_as_data() -> None:
    llm = FakeLanguageModel([REWRITE])
    earlier = [
        Exchange(user_text=f"question {n}", reply_text=f"answer {n}", route=Route.MENTOR, at=AT)
        for n in range(4)
    ]
    await QueryRewriter(llm, shipped_registry()).rewrite("uske liye kya karna hoga", earlier, None)
    [prompt] = llm.prompts
    assert "question 3" in prompt.user
    assert "question 2" in prompt.user
    assert "question 1" not in prompt.user
    assert "not known" in prompt.system


async def test_a_failed_rewrite_falls_back_to_the_students_own_words() -> None:
    llm = FakeLanguageModel([ProviderTimeout("muse spark timed out", provider="meta_model_api")])
    query, usage, failed = await QueryRewriter(llm, shipped_registry()).rewrite(
        "doctor banna hai", [], 11
    )
    assert (query.english_query, query.keywords, query.topics) == ("doctor banna hai", [], [])
    assert usage is None
    assert failed == "query_rewrite_failed=ProviderTimeout"


def test_the_raw_query_is_capped_at_the_model_limit() -> None:
    assert len(QueryRewriter.raw("x" * 5000).english_query) == 1000
