"""CorpusIngestor: idempotent ingestion keyed by content hash (s11 §4.5)."""

from datetime import date

import pytest

from app.core.errors import ProviderUnavailable
from app.domain.enums import EmbedPurpose
from app.rag.corpus_ingestor import CorpusIngestor
from app.rag.corpus_loader import CorpusFile, CorpusLoader
from tests.fakes.corpus import FakeChunkStore, FakeEmbedder

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 28)


def corpus_file(slug: str, body: str = "## Who can apply\nStudents of class 8.") -> CorpusFile:
    content = (
        "---\ntitle: NMMS scholarship — who can apply\n"
        "source_url: https://www.myscheme.gov.in/schemes/nmmss\nretrieved_on: 2026-10-28\n"
        f"topic: scholarships\nkeywords: [NMMS]\n---\n{body}\n"
    ).encode()
    return CorpusLoader.parse(f"corpus/scholarships/{slug}.md", content, TODAY)


async def test_new_files_are_chunked_embedded_as_passages_and_stored() -> None:
    store, embedder = FakeChunkStore(), FakeEmbedder()
    report = await CorpusIngestor(embedder, store).ingest([corpus_file("a")], dry_run=False)
    assert (report.added, report.updated, report.unchanged, report.chunks_written) == (1, 0, 0, 1)
    [(texts, purpose)] = embedder.calls
    assert purpose is EmbedPurpose.PASSAGE
    assert texts[0].startswith("NMMS scholarship — who can apply — Who can apply")
    [(document, chunks)] = store.replaced
    assert document.keywords == ["NMMS"]
    assert chunks[0].heading_path == "Who can apply"


async def test_a_second_run_changes_nothing_and_embeds_nothing() -> None:
    store, embedder = FakeChunkStore(), FakeEmbedder()
    files = [corpus_file("a"), corpus_file("b")]
    await CorpusIngestor(embedder, store).ingest(files, dry_run=False)
    embedder.calls.clear()
    report = await CorpusIngestor(embedder, store).ingest(files, dry_run=False)
    assert (report.added, report.updated, report.unchanged) == (0, 0, 2)
    assert embedder.calls == []


async def test_a_changed_file_is_replaced_and_a_removed_one_deleted() -> None:
    store, embedder = FakeChunkStore(), FakeEmbedder()
    await CorpusIngestor(embedder, store).ingest(
        [corpus_file("a"), corpus_file("b")], dry_run=False
    )
    changed = corpus_file("a", "## Who can apply\nStudents of class 8 in government schools.")
    report = await CorpusIngestor(embedder, store).ingest([changed], dry_run=False)
    assert (report.updated, report.deleted) == (1, 1)
    assert set(store.hashes) == {"corpus/scholarships/a.md"}


async def test_a_dry_run_reports_and_writes_nothing() -> None:
    store, embedder = FakeChunkStore(hashes={"corpus/scholarships/gone.md": "x"}), FakeEmbedder()
    report = await CorpusIngestor(embedder, store).ingest([corpus_file("a")], dry_run=True)
    assert (report.added, report.deleted, report.chunks_written) == (1, 1, 1)
    assert embedder.calls == []
    assert store.replaced == []
    assert "corpus/scholarships/gone.md" in store.hashes


async def test_an_embedding_failure_stops_before_that_document_is_written() -> None:
    store = FakeChunkStore()
    embedder = FakeEmbedder(
        error=ProviderUnavailable("embed server http 503", provider="ml_sidecar")
    )
    with pytest.raises(ProviderUnavailable, match="embed server"):
        await CorpusIngestor(embedder, store).ingest([corpus_file("a")], dry_run=False)
    assert store.replaced == []
