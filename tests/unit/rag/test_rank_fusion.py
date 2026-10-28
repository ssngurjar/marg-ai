"""RankFusion: reciprocal rank fusion with a soft topic hint and two chunks per document."""

from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import CorpusTopic
from app.domain.rules.rank_fusion import RankedHit, RankFusion

pytestmark = pytest.mark.unit


def hit(chunk: int, document: int) -> RankedHit:
    return RankedHit(UUID(int=chunk), UUID(int=1000 + document))


# A chunk belongs to exactly one document (chunk 7 is always in document 1, and so on).
hits = st.integers(1, 30).map(lambda chunk: hit(chunk, chunk % 6))
lists = st.lists(hits, max_size=20, unique_by=lambda ranked: ranked.chunk_id)


def test_a_chunk_in_both_lists_beats_one_in_a_single_list() -> None:
    fused = RankFusion.fuse([[hit(1, 1), hit(2, 2)], [hit(2, 2)]], {}, [], 5)
    assert [entry.chunk_id for entry in fused] == [UUID(int=2), UUID(int=1)]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)


def test_at_most_two_chunks_come_from_one_document() -> None:
    fused = RankFusion.fuse([[hit(1, 1), hit(2, 1), hit(3, 1), hit(4, 2)]], {}, [], 5)
    assert [entry.chunk_id.int for entry in fused] == [1, 2, 4]


def test_the_topic_hint_reorders_but_never_removes() -> None:
    topics = {UUID(int=1001): CorpusTopic.EXAMS, UUID(int=1002): CorpusTopic.SPORTS}
    fused = RankFusion.fuse([[hit(1, 1), hit(2, 2)]], topics, [CorpusTopic.SPORTS], 5)
    assert [entry.chunk_id.int for entry in fused] == [2, 1]


@given(lists, lists, st.integers(1, 8))
def test_swapping_the_lists_never_changes_the_result(
    first: list[RankedHit], second: list[RankedHit], top_k: int
) -> None:
    assert RankFusion.fuse([first, second], {}, [], top_k) == RankFusion.fuse(
        [second, first], {}, [], top_k
    )


@given(lists, lists, st.integers(1, 8))
def test_the_result_is_bounded_ranked_and_capped_per_document(
    first: list[RankedHit], second: list[RankedHit], top_k: int
) -> None:
    fused = RankFusion.fuse([first, second], {}, [], top_k)
    assert len(fused) <= top_k
    assert [entry.score for entry in fused] == sorted(
        (entry.score for entry in fused), reverse=True
    )
    for document in {entry.document_id for entry in fused}:
        assert sum(1 for entry in fused if entry.document_id == document) <= RankFusion.PER_DOCUMENT
    found = {entry.chunk_id for entry in [*first, *second]}
    assert {entry.chunk_id for entry in fused} <= found
