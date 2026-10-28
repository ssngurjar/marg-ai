"""Retriever: hybrid search and the honest "nothing relevant" (s11 §4.7)."""

from uuid import UUID

import pytest

from app.core.errors import ProviderTimeout
from app.domain.enums import EmbedPurpose
from app.domain.models.retrieval import RetrievalQuery
from app.layers.query_rewriter import QueryRewriter
from app.rag.retriever import Retriever, RetrieverSettings
from app.store.repositories.chunk_repository import Candidate
from tests.fakes.corpus import FakeChunkStore, FakeEmbedder, stored

pytestmark = pytest.mark.unit

SETTINGS = RetrieverSettings(top_k=5, min_similarity=0.80)


def candidate(number: int, document: int, score: float, *, exact: bool = False) -> Candidate:
    return Candidate(UUID(int=number), UUID(int=1000 + document), score, keyword_exact=exact)


def store_with(
    vector: list[Candidate], keyword: list[Candidate], keywords: frozenset[str] = frozenset()
) -> FakeChunkStore:
    chunks = {
        hit.chunk_id: stored(hit.chunk_id.int, hit.document_id.int - 1000)
        for hit in [*vector, *keyword]
    }
    return FakeChunkStore(
        chunks=chunks, vector_hits=vector, keyword_hits=keyword, keywords=keywords
    )


async def test_a_close_match_is_relevant_and_carries_its_source() -> None:
    store = store_with([candidate(1, 1, 0.87)], [])
    embedder = FakeEmbedder()
    result = await Retriever(embedder, store, SETTINGS).retrieve(
        QueryRewriter.raw("क्लास 8 में कोई स्कॉलरशिप मिलती है क्या"), grade=8
    )
    assert result.nothing_relevant is False
    [chunk] = result.chunks
    assert str(chunk.source_url) == "https://scholarships.gov.in/doc1"
    assert chunk.vector_similarity == 0.87
    assert embedder.calls[0][1] is EmbedPurpose.QUERY
    assert store.vector_grades == [8]


async def test_low_similarity_and_no_exact_keyword_is_nothing_relevant() -> None:
    store = store_with([candidate(1, 1, 0.79)], [candidate(1, 1, 0.1)])
    result = await Retriever(FakeEmbedder(), store, SETTINGS).retrieve(
        QueryRewriter.raw("Marine biologist kaise bante hain"), grade=12
    )
    assert result.nothing_relevant is True
    assert result.chunks  # still returned for telemetry; the mentor must not cite them


async def test_an_exact_scheme_name_is_relevant_despite_low_similarity() -> None:
    store = store_with(
        [candidate(1, 1, 0.70)], [candidate(2, 2, 1.2, exact=True)], frozenset({"NMMS"})
    )
    result = await Retriever(FakeEmbedder(), store, SETTINGS).retrieve(
        QueryRewriter.raw("nmms ka form kab bharna hai"), grade=8
    )
    assert result.nothing_relevant is False
    query, keywords, _ = store.keyword_queries[0]
    assert keywords == ["NMMS"]
    assert "nmms" in query
    assert " OR " in query


async def test_when_embedding_fails_the_keyword_half_still_runs_degraded() -> None:
    store = store_with([], [candidate(2, 2, 1.2, exact=True)], frozenset({"NEET"}))
    embedder = FakeEmbedder(error=ProviderTimeout("embed server timed out", provider="ml_sidecar"))
    result = await Retriever(embedder, store, SETTINGS).retrieve(
        QueryRewriter.raw("NEET ki taiyari kaise karein"), grade=11
    )
    assert result.degraded_reason == "query_embed_failed"
    assert result.nothing_relevant is False
    assert [chunk.chunk_id.int for chunk in result.chunks] == [2]


@pytest.mark.parametrize("text", ["", "   ", "🙂🙂", "?!", "a"])
async def test_an_empty_or_wordless_question_is_nothing_relevant_without_any_call(
    text: str,
) -> None:
    store = store_with([candidate(1, 1, 0.99)], [])
    embedder = FakeEmbedder()
    result = await Retriever(embedder, store, SETTINGS).retrieve(QueryRewriter.raw(text), None)
    assert result.nothing_relevant is True
    assert embedder.calls == []
    assert store.keyword_queries == []


async def test_keywords_are_matched_as_whole_words_only() -> None:
    store = FakeChunkStore(keywords=frozenset({"NEET", "NEET-UG", "NDA"}))
    retriever = Retriever(FakeEmbedder(), store, SETTINGS)
    assert await retriever.keywords_in("mujhe neet ug dena hai") == ["NEET", "NEET-UG"]
    assert await retriever.keywords_in("neetu ki behen") == []
    assert await retriever.keywords_in("agenda") == []


async def test_given_keywords_from_a_rewrite_are_used_as_they_are() -> None:
    store = store_with([candidate(1, 1, 0.9)], [], frozenset({"NMMS"}))
    query = RetrievalQuery(
        english_query="Is there a scholarship in class 8?", keywords=["NMMS"], topics=[]
    )
    await Retriever(FakeEmbedder(), store, SETTINGS).retrieve(query, None)
    assert store.keyword_queries[0][1] == ["NMMS"]
