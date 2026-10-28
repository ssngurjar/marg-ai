"""Retriever: hybrid search over the corpus, with an honest "nothing relevant" (s11 §4.7).

Two candidate lists (nearest vectors, and a keyword search that boosts exact exam and scheme
names), fused by RankFusion, top RETRIEVAL_TOP_K. `nothing_relevant` is set when the best
vector similarity is below RETRIEVAL_MIN_SIMILARITY and no candidate matched a keyword exactly:
then the mentor takes the don't-know path and cites nothing. If the question can't be embedded,
the keyword half still runs (DEGRADED); a database error is raised (the turn fails).
"""

import re
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic import HttpUrl

from app.core.errors import ProviderError
from app.domain.enums import EmbedPurpose
from app.domain.models.retrieval import RetrievalQuery, RetrievalResult, RetrievedChunk
from app.domain.rules.rank_fusion import FusedHit, RankedHit, RankFusion
from app.providers.ports import Embedder
from app.rag.chunk_store import ChunkStore
from app.store.repositories.chunk_repository import Candidate


@dataclass(frozen=True, slots=True)
class RetrieverSettings:
    top_k: int  # RETRIEVAL_TOP_K
    min_similarity: float  # RETRIEVAL_MIN_SIMILARITY


class Retriever:
    CANDIDATES: ClassVar[int] = 20
    WORD: ClassVar[re.Pattern[str]] = re.compile(r"[^\W_]{2,}")  # letters or digits, ≥ 2 long

    def __init__(self, embedder: Embedder, store: ChunkStore, settings: RetrieverSettings) -> None:
        self._embedder = embedder
        self._store = store
        self._settings = settings
        self._known_keywords: frozenset[str] | None = None

    async def retrieve(self, query: RetrievalQuery, grade: int | None) -> RetrievalResult:
        """Raises StoreError when the corpus can't be read."""
        words = self.WORD.findall(query.english_query)
        if not words and not query.keywords:
            return RetrievalResult(
                query=query, chunks=[], nothing_relevant=True, degraded_reason=None
            )
        keywords = list(query.keywords) or await self.keywords_in(query.english_query)
        degraded: str | None = None
        vector_hits: list[Candidate] = []
        try:
            [vector] = await self._embedder.embed([query.english_query], EmbedPurpose.QUERY)
            vector_hits = await self._store.vector_candidates(vector, grade, self.CANDIDATES)
        except ProviderError:
            degraded = "query_embed_failed"
        keyword_query = " OR ".join([*words, *keywords])
        keyword_hits = await self._store.keyword_candidates(
            keyword_query, keywords, grade, self.CANDIDATES
        )
        chunks = await self._chunks(query, vector_hits, keyword_hits)
        best = max((hit.score for hit in vector_hits), default=0.0)
        exact = any(hit.keyword_exact for hit in keyword_hits)
        return RetrievalResult(
            query=query,
            chunks=chunks,
            nothing_relevant=best < self._settings.min_similarity and not exact,
            degraded_reason=degraded,
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
        self,
        query: RetrievalQuery,
        vector_hits: list[Candidate],
        keyword_hits: list[Candidate],
    ) -> list[RetrievedChunk]:
        all_hits = [*vector_hits, *keyword_hits]
        stored = await self._store.load_chunks(list({hit.chunk_id for hit in all_hits}))
        topics = {chunk.document_id: chunk.topic for chunk in stored.values()}
        fused: list[FusedHit] = RankFusion.fuse(
            [_ranked(vector_hits), _ranked(keyword_hits)],
            topics,
            query.topics,
            self._settings.top_k,
        )
        similarity = {hit.chunk_id: hit.score for hit in vector_hits}
        keyword_rank: dict[UUID, int] = {}
        exact: set[UUID] = set()
        for rank, keyword_hit in enumerate(keyword_hits, start=1):
            keyword_rank.setdefault(keyword_hit.chunk_id, rank)
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
                    vector_similarity=similarity.get(hit.chunk_id, 0.0),
                    keyword_rank=keyword_rank.get(hit.chunk_id),
                    keyword_exact=hit.chunk_id in exact,
                    fused_score=hit.score,
                )
            )
        return chunks


def _ranked(hits: list[Candidate]) -> list[RankedHit]:
    return [RankedHit(hit.chunk_id, hit.document_id) for hit in hits]
