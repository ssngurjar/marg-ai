"""What retrieval is asked and what it finds (s11 §4.6, §4.7; contracts §2.7)."""

from datetime import date
from uuid import UUID

from pydantic import Field, HttpUrl

from app.domain.enums import CorpusTopic
from app.domain.models.base import DomainModel


class RetrievalQuery(DomainModel):
    """The search: a question in English (the corpus language) and the exam or scheme names in
    it. Without query rewriting (QUERY_REWRITE_ENABLED off) it is the user's own words."""

    english_query: str = Field(max_length=1000)
    keywords: list[str] = Field(max_length=8)
    topics: list[CorpusTopic] = Field(max_length=3)  # a soft hint, never a filter


class RetrievedChunk(DomainModel):
    chunk_id: UUID
    document_id: UUID
    title: str
    heading_path: str
    text: str
    source_url: HttpUrl
    retrieved_on: date
    topic: CorpusTopic
    keyword_score: float  # full-text rank, +1 when a document keyword matched exactly
    keyword_rank: int  # 1-based rank in the keyword search
    keyword_exact: bool  # a document keyword matched one of the query's keywords exactly
    fused_score: float


class RetrievalResult(DomainModel):
    query: RetrievalQuery
    chunks: list[RetrievedChunk]  # at most RETRIEVAL_TOP_K, best first
    nothing_relevant: bool  # True: S12 takes the don't-know path and cites nothing
