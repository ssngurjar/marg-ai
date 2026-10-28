"""In-memory corpus fake: a ChunkStore with scripted keyword candidates."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from app.domain.enums import CorpusTopic
from app.store.repositories.chunk_repository import Candidate, ChunkRow, DocumentRow, StoredChunk


def stored(
    number: int, document: int, topic: CorpusTopic = CorpusTopic.SCHOLARSHIPS
) -> StoredChunk:
    return StoredChunk(
        chunk_id=UUID(int=number),
        document_id=UUID(int=1000 + document),
        title=f"Document {document}",
        heading_path="Who can apply",
        text=f"chunk {number}",
        source_url=f"https://scholarships.gov.in/doc{document}",
        retrieved_on=date(2026, 10, 28),
        topic=topic,
    )


@dataclass
class FakeChunkStore:
    """Satisfies `ChunkStore`."""

    chunks: dict[UUID, StoredChunk] = field(default_factory=dict)
    keyword_hits: list[Candidate] = field(default_factory=list)
    keywords: frozenset[str] = frozenset()
    hashes: dict[str, str] = field(default_factory=dict)
    replaced: list[tuple[DocumentRow, list[ChunkRow]]] = field(default_factory=list)
    keyword_queries: list[tuple[str, list[str], int | None]] = field(default_factory=list)

    async def document_hashes(self) -> dict[str, str]:
        return dict(self.hashes)

    async def replace_document(self, document: DocumentRow, chunks: Sequence[ChunkRow]) -> None:
        self.replaced.append((document, list(chunks)))
        self.hashes[document.path] = document.content_sha256

    async def delete_documents_not_in(self, paths: Collection[str]) -> int:
        gone = [path for path in self.hashes if path not in paths]
        for path in gone:
            del self.hashes[path]
        return len(gone)

    async def corpus_keywords(self) -> frozenset[str]:
        return self.keywords

    async def keyword_candidates(
        self, keyword_query: str, keywords: Sequence[str], grade: int | None, limit: int
    ) -> list[Candidate]:
        self.keyword_queries.append((keyword_query, list(keywords), grade))
        return self.keyword_hits[:limit]

    async def load_chunks(self, chunk_ids: Sequence[UUID]) -> dict[UUID, StoredChunk]:
        return {
            chunk_id: self.chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in self.chunks
        }
