"""ChunkRepository against Postgres with pgvector (s11 §4.5, §4.7)."""

import math
import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.enums import CorpusTopic
from app.store.db import create_engine, create_session_factory
from app.store.repositories.chunk_repository import ChunkRepository, ChunkRow, DocumentRow
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration


def axis(index: int, lean: float = 0.0) -> list[float]:
    """A unit vector mostly along `index`, leaning `lean` toward axis 0."""
    vector = [0.0] * 384
    vector[index] = math.sqrt(1 - lean**2)
    vector[0] += lean
    return vector


def document(path: str, *, grades: list[int], keywords: list[str], sha: str = "1") -> DocumentRow:
    return DocumentRow(
        path=path,
        title=path.rsplit("/", 1)[-1],
        source_url=f"https://example.gov.in/{path}",
        retrieved_on=date(2026, 10, 28),
        topic=CorpusTopic.SCHOLARSHIPS,
        language="english",
        grades=grades,
        keywords=keywords,
        content_sha256=sha,
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE corpus_documents CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def corpus(engine: AsyncEngine) -> ChunkRepository:
    repository = ChunkRepository(create_session_factory(engine))
    await repository.replace_document(
        document("corpus/scholarships/nmms.md", grades=[8], keywords=["NMMS", "scholarship"]),
        [ChunkRow(0, "Who can apply", "NMMS — students of class 8 can apply", axis(1))],
    )
    await repository.replace_document(
        document("corpus/scholarships/nsp.md", grades=[], keywords=["NSP"]),
        [ChunkRow(0, "What it is", "National Scholarship Portal for all classes", axis(2))],
    )
    return repository


async def test_nearest_vectors_come_first_with_their_similarity(corpus: ChunkRepository) -> None:
    hits = await corpus.vector_candidates(axis(1, lean=0.2), None, 20)
    assert len(hits) == 2
    assert hits[0].score > hits[1].score
    assert hits[0].score == pytest.approx(math.sqrt(1 - 0.04), abs=1e-3)
    chunks = await corpus.load_chunks([hits[0].chunk_id])
    assert chunks[hits[0].chunk_id].title == "nmms.md"


async def test_a_grade_8_document_is_left_out_for_grade_11_but_all_grade_ones_stay(
    corpus: ChunkRepository,
) -> None:
    titles = []
    for hit in await corpus.vector_candidates(axis(1), 11, 20):
        titles.append((await corpus.load_chunks([hit.chunk_id]))[hit.chunk_id].title)
    assert titles == ["nsp.md"]
    assert len(await corpus.vector_candidates(axis(1), 8, 20)) == 2


async def test_an_exact_scheme_name_is_found_and_flagged_whatever_the_case(
    corpus: ChunkRepository,
) -> None:
    hits = await corpus.keyword_candidates("form kab bharna OR nmms", ["nmms"], None, 20)
    assert hits[0].keyword_exact is True
    assert (await corpus.load_chunks([hits[0].chunk_id]))[hits[0].chunk_id].title == "nmms.md"


async def test_a_word_in_the_text_matches_without_being_an_exact_keyword(
    corpus: ChunkRepository,
) -> None:
    [hit] = await corpus.keyword_candidates("portal", [], None, 20)
    assert hit.keyword_exact is False


async def test_replacing_a_document_swaps_all_its_chunks_and_keeps_its_id(
    corpus: ChunkRepository, engine: AsyncEngine
) -> None:
    before = await corpus.vector_candidates(axis(1), 8, 1)
    await corpus.replace_document(
        document("corpus/scholarships/nmms.md", grades=[8], keywords=["NMMS"], sha="2"),
        [
            ChunkRow(0, "Who can apply", "first", axis(3)),
            ChunkRow(1, "How to apply", "second", axis(4)),
        ],
    )
    assert (await corpus.document_hashes())["corpus/scholarships/nmms.md"] == "2"
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT c.position, c.document_id FROM corpus_chunks c"
                    " JOIN corpus_documents d ON d.id = c.document_id"
                    " WHERE d.path = 'corpus/scholarships/nmms.md' ORDER BY c.position"
                )
            )
        ).all()
    assert [row.position for row in rows] == [0, 1]
    assert rows[0].document_id == before[0].document_id


async def test_documents_whose_files_are_gone_are_deleted_with_their_chunks(
    corpus: ChunkRepository,
) -> None:
    assert await corpus.delete_documents_not_in(["corpus/scholarships/nsp.md"]) == 1
    assert set(await corpus.document_hashes()) == {"corpus/scholarships/nsp.md"}
    assert await corpus.chunk_count() == 1


async def test_keywords_are_stored_upper_cased_and_listed(corpus: ChunkRepository) -> None:
    assert await corpus.corpus_keywords() == frozenset({"NMMS", "SCHOLARSHIP", "NSP"})
