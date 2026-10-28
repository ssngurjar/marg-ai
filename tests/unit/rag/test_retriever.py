"""Retriever: keyword search and the honest "nothing relevant" (s11 §4.7)."""

from uuid import UUID

import pytest

from app.core.errors import StoreError
from app.domain.enums import CorpusTopic
from app.domain.models.retrieval import RetrievalQuery
from app.layers.query_rewriter import QueryRewriter
from app.rag.retriever import Retriever, RetrieverSettings
from app.store.repositories.chunk_repository import Candidate, StoredChunk
from tests.fakes.corpus import FakeChunkStore, stored

pytestmark = pytest.mark.unit

SETTINGS = RetrieverSettings(top_k=5, min_text_rank=1.3)


def candidate(number: int, document: int, rank: float, *, exact: bool = False) -> Candidate:
    """A keyword hit as the repository returns it: the order score adds 1 for an exact name."""
    score = rank + 1.0 if exact else rank
    return Candidate(
        UUID(int=number), UUID(int=1000 + document), score, keyword_exact=exact, text_rank=rank
    )


def store_with(
    keyword: list[Candidate],
    keywords: frozenset[str] = frozenset(),
    topics: dict[int, CorpusTopic] | None = None,
) -> FakeChunkStore:
    chunks: dict[UUID, StoredChunk] = {}
    for hit in keyword:
        document = hit.document_id.int - 1000
        topic = (topics or {}).get(document, CorpusTopic.SCHOLARSHIPS)
        chunks[hit.chunk_id] = stored(hit.chunk_id.int, document, topic)
    return FakeChunkStore(chunks=chunks, keyword_hits=keyword, keywords=keywords)


async def test_a_strong_text_match_is_relevant_and_carries_its_source() -> None:
    store = store_with([candidate(1, 1, 1.5)])
    result = await Retriever(store, SETTINGS).retrieve(
        QueryRewriter.raw("scholarship for class 8 students"), grade=8
    )
    assert result.nothing_relevant is False
    [chunk] = result.chunks
    assert str(chunk.source_url) == "https://scholarships.gov.in/doc1"
    assert (chunk.keyword_score, chunk.keyword_rank, chunk.keyword_exact) == (1.5, 1, False)
    assert store.keyword_queries[0][2] == 8


async def test_a_weak_match_and_no_exact_name_is_nothing_relevant() -> None:
    store = store_with([candidate(1, 1, 1.1), candidate(2, 2, 0.9)])
    result = await Retriever(store, SETTINGS).retrieve(
        QueryRewriter.raw("Marine biologist kaise bante hain"), grade=12
    )
    assert result.nothing_relevant is True
    assert result.chunks  # still returned for telemetry; the mentor must not cite them


@pytest.mark.parametrize(
    ("best", "nothing_relevant"), [(1.2999, True), (1.3, False), (1.3001, False)]
)
async def test_the_threshold_is_inclusive(best: float, *, nothing_relevant: bool) -> None:
    store = store_with([candidate(1, 1, best)])
    result = await Retriever(store, SETTINGS).retrieve(QueryRewriter.raw("nursing course"), None)
    assert result.nothing_relevant is nothing_relevant


async def test_a_rewritten_name_matching_a_document_exactly_is_relevant() -> None:
    store = store_with([candidate(2, 2, 0.2, exact=True)], frozenset({"NMMS"}))
    query = RetrievalQuery(english_query="When is the NMMS form due?", keywords=["NMMS"], topics=[])
    result = await Retriever(store, SETTINGS).retrieve(query, grade=8)
    assert result.nothing_relevant is False


async def test_a_generic_name_found_in_the_question_boosts_but_is_not_relevance() -> None:
    # regression (calibration, 2026-10-29): "How can a Class 12 student join the police?"
    # matched the corpus keyword "CLASS 12" exactly and was answered from scholarship pages
    store = store_with([candidate(2, 2, 0.9, exact=True)], frozenset({"CLASS 12"}))
    result = await Retriever(store, SETTINGS).retrieve(
        QueryRewriter.raw("How can a Class 12 student join the police?"), grade=12
    )
    query, keywords, _ = store.keyword_queries[0]
    assert keywords == ["CLASS 12"]  # still sent, so it can lift the order
    assert " OR " in query
    assert result.nothing_relevant is True


async def test_no_candidates_is_nothing_relevant_with_no_chunks() -> None:
    result = await Retriever(store_with([]), SETTINGS).retrieve(
        QueryRewriter.raw("how do I become an astronaut"), None
    )
    assert result.nothing_relevant is True
    assert result.chunks == []


@pytest.mark.parametrize("text", ["", "   ", "🙂🙂", "?!", "a"])
async def test_an_empty_or_wordless_question_is_nothing_relevant_without_a_search(
    text: str,
) -> None:
    store = store_with([candidate(1, 1, 0.99)])
    result = await Retriever(store, SETTINGS).retrieve(QueryRewriter.raw(text), None)
    assert result.nothing_relevant is True
    assert store.keyword_queries == []


async def test_a_hinted_topic_moves_its_chunk_up_and_one_document_gets_two_places() -> None:
    hits = [
        candidate(1, 1, 0.5),
        candidate(2, 1, 0.45),
        candidate(3, 1, 0.4),
        candidate(4, 2, 0.3),
    ]
    store = store_with(hits, topics={2: CorpusTopic.EXAMS})
    query = RetrievalQuery(english_query="NEET exam", keywords=[], topics=[CorpusTopic.EXAMS])
    result = await Retriever(store, SETTINGS).retrieve(query, None)
    assert [chunk.chunk_id.int for chunk in result.chunks] == [4, 1, 2]


async def test_a_database_error_is_raised_not_hidden() -> None:
    class BrokenStore(FakeChunkStore):
        async def keyword_candidates(
            self, keyword_query: str, keywords: object, grade: int | None, limit: int
        ) -> list[Candidate]:
            raise StoreError("could not search the corpus: OperationalError")

    with pytest.raises(StoreError, match="could not search the corpus"):
        await Retriever(BrokenStore(), SETTINGS).retrieve(QueryRewriter.raw("NEET exam"), None)


async def test_keywords_are_matched_as_whole_words_only() -> None:
    store = FakeChunkStore(keywords=frozenset({"NEET", "NEET-UG", "NDA"}))
    retriever = Retriever(store, SETTINGS)
    assert await retriever.keywords_in("mujhe neet ug dena hai") == ["NEET", "NEET-UG"]
    assert await retriever.keywords_in("neetu ki behen") == []
    assert await retriever.keywords_in("agenda") == []


async def test_given_keywords_from_a_rewrite_are_used_as_they_are() -> None:
    store = store_with([candidate(1, 1, 0.9)], frozenset({"NMMS"}))
    query = RetrievalQuery(
        english_query="Is there a scholarship in class 8?", keywords=["NMMS"], topics=[]
    )
    await Retriever(store, SETTINGS).retrieve(query, None)
    assert store.keyword_queries[0][1] == ["NMMS"]
