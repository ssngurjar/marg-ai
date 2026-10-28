"""CorpusIngestor: idempotent ingestion keyed by content hash (s11 §4.5)."""

from collections.abc import Sequence
from datetime import date

import pytest

from app.core.errors import StoreError
from app.rag.corpus_ingestor import CorpusIngestor
from app.rag.corpus_loader import CorpusFile, CorpusLoader
from app.store.repositories.chunk_repository import ChunkRow, DocumentRow
from tests.fakes.corpus import FakeChunkStore

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 28)


def corpus_file(slug: str, body: str = "## Who can apply\nStudents of class 8.") -> CorpusFile:
    content = (
        "---\ntitle: NMMS scholarship — who can apply\n"
        "source_url: https://www.myscheme.gov.in/schemes/nmmss\nretrieved_on: 2026-10-28\n"
        f"topic: scholarships\nkeywords: [NMMS]\n---\n{body}\n"
    ).encode()
    return CorpusLoader.parse(f"corpus/scholarships/{slug}.md", content, TODAY)


async def test_new_files_are_chunked_and_stored() -> None:
    store = FakeChunkStore()
    report = await CorpusIngestor(store).ingest([corpus_file("a")], dry_run=False)
    assert (report.added, report.updated, report.unchanged, report.chunks_written) == (1, 0, 0, 1)
    [(document, chunks)] = store.replaced
    assert chunks[0].text.startswith("NMMS scholarship — who can apply — Who can apply")
    assert document.keywords == ["NMMS"]
    assert chunks[0].heading_path == "Who can apply"


async def test_a_second_run_changes_nothing_and_writes_nothing() -> None:
    store = FakeChunkStore()
    files = [corpus_file("a"), corpus_file("b")]
    await CorpusIngestor(store).ingest(files, dry_run=False)
    store.replaced.clear()
    report = await CorpusIngestor(store).ingest(files, dry_run=False)
    assert (report.added, report.updated, report.unchanged) == (0, 0, 2)
    assert store.replaced == []


async def test_a_changed_file_is_replaced_and_a_removed_one_deleted() -> None:
    store = FakeChunkStore()
    await CorpusIngestor(store).ingest([corpus_file("a"), corpus_file("b")], dry_run=False)
    changed = corpus_file("a", "## Who can apply\nStudents of class 8 in government schools.")
    report = await CorpusIngestor(store).ingest([changed], dry_run=False)
    assert (report.updated, report.deleted) == (1, 1)
    assert set(store.hashes) == {"corpus/scholarships/a.md"}


async def test_a_dry_run_reports_and_writes_nothing() -> None:
    store = FakeChunkStore(hashes={"corpus/scholarships/gone.md": "x"})
    report = await CorpusIngestor(store).ingest([corpus_file("a")], dry_run=True)
    assert (report.added, report.deleted, report.chunks_written) == (1, 1, 1)
    assert store.replaced == []
    assert "corpus/scholarships/gone.md" in store.hashes


async def test_a_store_failure_names_the_document_and_keeps_earlier_ones() -> None:
    class FailingOnB(FakeChunkStore):
        async def replace_document(self, document: DocumentRow, chunks: Sequence[ChunkRow]) -> None:
            if document.path.endswith("/b.md"):
                raise StoreError(f"could not store corpus document {document.path}: OSError")
            await super().replace_document(document, chunks)

    store = FailingOnB()
    with pytest.raises(StoreError, match=r"corpus/scholarships/b\.md"):
        await CorpusIngestor(store).ingest([corpus_file("a"), corpus_file("b")], dry_run=False)
    assert set(store.hashes) == {"corpus/scholarships/a.md"}
