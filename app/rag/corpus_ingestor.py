"""CorpusIngestor: the validated corpus files into the corpus tables (s11 §4.5). Idempotent.

A file whose content hash is already stored is skipped. A new or changed file is chunked, then
replaced in one transaction (Postgres builds its keyword index). Documents whose files are gone
are deleted. A dry run reports what would change and writes nothing.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.rag.chunk_store import ChunkStore
from app.rag.chunker import ChunkDraft, Chunker
from app.rag.corpus_loader import CorpusFile
from app.store.repositories.chunk_repository import ChunkRow, DocumentRow


@dataclass(frozen=True, slots=True)
class IngestReport:
    added: int
    updated: int
    unchanged: int
    deleted: int
    chunks_written: int


class CorpusIngestor:
    def __init__(self, store: ChunkStore) -> None:
        self._store = store

    async def ingest(self, files: Sequence[CorpusFile], *, dry_run: bool) -> IngestReport:
        """Raises StoreError naming the document being processed; documents already done stay
        done (each is its own transaction)."""
        stored = await self._store.document_hashes()
        added = updated = unchanged = chunks_written = 0
        for corpus_file in files:
            previous = stored.get(corpus_file.path)
            if previous == corpus_file.content_sha256:
                unchanged += 1
                continue  # already ingested as it is
            drafts = Chunker.chunk(corpus_file.frontmatter.title, corpus_file.body)
            if not dry_run:
                await self._write(corpus_file, drafts)
            chunks_written += len(drafts)
            if previous is None:
                added += 1
            else:
                updated += 1
        on_disk = {corpus_file.path for corpus_file in files}
        if dry_run:
            deleted = len(set(stored) - on_disk)
        else:
            deleted = await self._store.delete_documents_not_in(on_disk)
        return IngestReport(added, updated, unchanged, deleted, chunks_written)

    async def _write(self, corpus_file: CorpusFile, drafts: Sequence[ChunkDraft]) -> None:
        frontmatter = corpus_file.frontmatter
        document = DocumentRow(
            path=corpus_file.path,
            title=frontmatter.title,
            source_url=str(frontmatter.source_url),
            retrieved_on=frontmatter.retrieved_on,
            topic=frontmatter.topic,
            language=frontmatter.language,
            grades=frontmatter.grades,
            keywords=frontmatter.keywords,
            content_sha256=corpus_file.content_sha256,
        )
        chunks: list[ChunkRow] = []
        for draft in drafts:
            chunks.append(
                ChunkRow(position=draft.position, heading_path=draft.heading_path, text=draft.text)
            )
        await self._store.replace_document(document, chunks)
