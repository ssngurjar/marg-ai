"""Retriever: keyword search over the corpus, with an honest "nothing relevant" (s11 §4.7).

One candidate list: Postgres full-text search (English stemming) over each chunk's heading and
text, with exact exam and scheme names boosted. RankFusion then applies the topic hint and at
most two chunks per document, top RETRIEVAL_TOP_K.

A result is relevant when a name the query rewrite gave (an exam, scheme or course) is exactly
a document keyword, or when the best text rank reaches RETRIEVAL_MIN_TEXT_RANK. Names found in
the question by `keywords_in` still boost the order but don't make a result relevant: the
corpus keywords include generic ones ("class 12", "college") that match almost any question
(calibrated on 22 questions, s11 decisions log 2026-10-29). Otherwise `nothing_relevant` is set,
and the mentor takes the don't-know path and cites nothing. A database error is raised (the
turn fails).

Keyword-only since 2026-10-29: every model Marg calls must be a Meta model, and the vector half
used multilingual-e5-small (s11 decisions log).
"""

import re
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic import HttpUrl

from app.domain.models.retrieval import RetrievalQuery, RetrievalResult, RetrievedChunk
from app.domain.rules.rank_fusion import FusedHit, RankedHit, RankFusion
from app.rag.chunk_store import ChunkStore
from app.store.repositories.chunk_repository import Candidate


@dataclass(frozen=True, slots=True)
class RetrieverSettings:
    top_k: int  # RETRIEVAL_TOP_K
    min_text_rank: float  # RETRIEVAL_MIN_TEXT_RANK


class Retriever:
    CANDIDATES: ClassVar[int] = 20
    WORD: ClassVar[re.Pattern[str]] = re.compile(r"[^\W_]{2,}")  # letters or digits, ≥ 2 long

    def __init__(self, store: ChunkStore, settings: RetrieverSettings) -> None:
        self._store = store
        self._settings = settings
        self._known_keywords: frozenset[str] | None = None

    async def retrieve(self, query: RetrievalQuery, grade: int | None) -> RetrievalResult:
        """Raises StoreError when the corpus can't be read."""
        words = self.WORD.findall(query.english_query)
        if not words and not query.keywords:
            return RetrievalResult(query=query, chunks=[], nothing_relevant=True)
        keywords = list(query.keywords) or await self.keywords_in(query.english_query)
        keyword_query = " OR ".join([*words, *keywords])
        keyword_hits = await self._store.keyword_candidates(
            keyword_query, keywords, grade, self.CANDIDATES
        )
        chunks = await self._chunks(query, keyword_hits)
        best_text_rank = max((hit.text_rank for hit in keyword_hits), default=0.0)
        named_exactly = bool(query.keywords) and any(hit.keyword_exact for hit in keyword_hits)
        strong_text_match = best_text_rank >= self._settings.min_text_rank
        return RetrievalResult(
            query=query,
            chunks=chunks,
            nothing_relevant=not (named_exactly or strong_text_match),
        )

    async def keywords_in(self, text: str) -> list[str]:
        """The corpus's exam and scheme names that appear in `text` as whole words."""
        if self._known_keywords is None:
            self._known_keywords = await self._store.corpus_keywords()
        upper = f" {' '.join(self.WORD.findall(text.upper()))} "
        found: list[str] = []
        for keyword in sorted(self._known_keywords):
            spoken = " ".join(self.WORD.findall(keyword))
            if spoken and f" {spoken} " in upper:
                found.append(keyword)
        return found[:8]

    async def _chunks(
        self, query: RetrievalQuery, keyword_hits: list[Candidate]
    ) -> list[RetrievedChunk]:
        stored = await self._store.load_chunks(list({hit.chunk_id for hit in keyword_hits}))
        topics = {chunk.document_id: chunk.topic for chunk in stored.values()}
        fused: list[FusedHit] = RankFusion.fuse(
            [_ranked(keyword_hits)], topics, query.topics, self._settings.top_k
        )
        keyword_rank: dict[UUID, int] = {}
        keyword_score: dict[UUID, float] = {}
        exact: set[UUID] = set()
        for rank, keyword_hit in enumerate(keyword_hits, start=1):
            keyword_rank.setdefault(keyword_hit.chunk_id, rank)
            keyword_score.setdefault(keyword_hit.chunk_id, keyword_hit.score)
            if keyword_hit.keyword_exact:
                exact.add(keyword_hit.chunk_id)
        chunks: list[RetrievedChunk] = []
        for hit in fused:
            chunk = stored[hit.chunk_id]
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    title=chunk.title,
                    heading_path=chunk.heading_path,
                    text=chunk.text,
                    source_url=HttpUrl(chunk.source_url),
                    retrieved_on=chunk.retrieved_on,
                    topic=chunk.topic,
                    keyword_score=keyword_score[hit.chunk_id],
                    keyword_rank=keyword_rank[hit.chunk_id],
                    keyword_exact=hit.chunk_id in exact,
                    fused_score=hit.score,
                )
            )
        return chunks


def _ranked(hits: list[Candidate]) -> list[RankedHit]:
    return [RankedHit(hit.chunk_id, hit.document_id) for hit in hits]
