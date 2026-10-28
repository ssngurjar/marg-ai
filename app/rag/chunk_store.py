"""ChunkStore: what ingestion and retrieval need from the corpus tables (ChunkRepository in
production, an in-memory fake in unit tests)."""

from collections.abc import Collection, Sequence
from typing import Protocol
from uuid import UUID

from app.store.repositories.chunk_repository import Candidate, ChunkRow, DocumentRow, StoredChunk


class ChunkStore(Protocol):
    async def document_hashes(self) -> dict[str, str]: ...

    async def replace_document(self, document: DocumentRow, chunks: Sequence[ChunkRow]) -> None: ...

    async def delete_documents_not_in(self, paths: Collection[str]) -> int: ...

    async def corpus_keywords(self) -> frozenset[str]: ...

    async def keyword_candidates(
        self, keyword_query: str, keywords: Sequence[str], grade: int | None, limit: int
    ) -> list[Candidate]: ...

    async def load_chunks(self, chunk_ids: Sequence[UUID]) -> dict[UUID, StoredChunk]: ...
