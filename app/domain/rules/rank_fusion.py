"""RankFusion: two ranked candidate lists into one (s11 §4.7). Pure.

Reciprocal rank fusion: a chunk scores Σ 1 / (60 + rank) over the lists it's in (rank from 1),
plus a small bonus when its document's topic is one the query hinted at; the hint never removes
anything. At most two chunks per document, so one long document can't crowd out the rest. Ties
break on the chunk id, so the result doesn't depend on which list came first.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from app.domain.enums import CorpusTopic


@dataclass(frozen=True, slots=True)
class RankedHit:
    chunk_id: UUID
    document_id: UUID


@dataclass(frozen=True, slots=True)
class FusedHit:
    chunk_id: UUID
    document_id: UUID
    score: float


class RankFusion:
    K: ClassVar[int] = 60
    TOPIC_BONUS: ClassVar[float] = 0.005
    PER_DOCUMENT: ClassVar[int] = 2

    @staticmethod
    def fuse(
        ranked_lists: Sequence[Sequence[RankedHit]],
        topics: Mapping[UUID, CorpusTopic],
        hinted: Collection[CorpusTopic],
        top_k: int,
    ) -> list[FusedHit]:
        """`topics`: each document's topic. `hinted`: the query's topic hints."""
        scores: dict[UUID, float] = {}
        documents: dict[UUID, UUID] = {}
        for ranked in ranked_lists:
            for rank, hit in enumerate(ranked, start=1):
                scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1 / (RankFusion.K + rank)
                documents[hit.chunk_id] = hit.document_id
        for chunk_id, document_id in documents.items():
            if topics.get(document_id) in hinted:
                scores[chunk_id] += RankFusion.TOPIC_BONUS
        ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], str(chunk_id)))
        fused: list[FusedHit] = []
        taken_per_document: dict[UUID, int] = {}
        for chunk_id in ordered:
            document_id = documents[chunk_id]
            if taken_per_document.get(document_id, 0) >= RankFusion.PER_DOCUMENT:
                continue  # this document already has its two places
            taken_per_document[document_id] = taken_per_document.get(document_id, 0) + 1
            fused.append(FusedHit(chunk_id, document_id, scores[chunk_id]))
            if len(fused) == top_k:
                break
        return fused
