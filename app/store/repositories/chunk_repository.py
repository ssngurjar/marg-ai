"""ChunkRepository: the corpus in Postgres (s11 §4.5, §4.7). No user data.

A changed document is replaced in one transaction (the row, then all its chunks), so a failed
ingest never leaves half a document. Retrieval reads two candidate lists: nearest vectors
(cosine, HNSW) and a keyword search over the chunk text and the document's keywords, both
optionally limited to a grade.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Row, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import CorpusTopic
from app.store.vector_column import VectorColumn


@dataclass(frozen=True, slots=True)
class DocumentRow:
    path: str
    title: str
    source_url: str
    retrieved_on: date
    topic: CorpusTopic
    language: str
    grades: Sequence[int]
    keywords: Sequence[str]
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ChunkRow:
    position: int
    heading_path: str
    text: str
    embedding: Sequence[float]


@dataclass(frozen=True, slots=True)
class Candidate:
    chunk_id: UUID
    document_id: UUID
    score: float  # vector: 1 - cosine distance; keyword: text rank (+1 for an exact keyword)
    keyword_exact: bool


@dataclass(frozen=True, slots=True)
class StoredChunk:
    chunk_id: UUID
    document_id: UUID
    title: str
    heading_path: str
    text: str
    source_url: str
    retrieved_on: date
    topic: CorpusTopic


class ChunkRepository:
    EF_SEARCH = 60  # HNSW search breadth: better recall at this corpus size (s11 §4.7)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def document_hashes(self) -> dict[str, str]:
        """Every ingested document's path and content hash."""
        rows = await self._rows("SELECT path, content_sha256 FROM corpus_documents")
        return {row.path: row.content_sha256 for row in rows}

    async def replace_document(self, document: DocumentRow, chunks: Sequence[ChunkRow]) -> None:
        """Insert or replace one document and all its chunks, in one transaction."""
        try:
            async with self._session_factory() as session, session.begin():
                document_id = await _upsert_document(session, document)
                await session.execute(
                    text("DELETE FROM corpus_chunks WHERE document_id = :id"), {"id": document_id}
                )
                for chunk in chunks:
                    await session.execute(
                        text(
                            "INSERT INTO corpus_chunks (id, document_id, position, heading_path,"
                            " text, embedding)"
                            " VALUES (:id, :document_id, :position, :heading_path, :text,"
                            " CAST(:embedding AS vector))"
                        ),
                        {
                            "id": uuid4(),
                            "document_id": document_id,
                            "position": chunk.position,
                            "heading_path": chunk.heading_path,
                            "text": chunk.text,
                            "embedding": VectorColumn.literal(chunk.embedding),
                        },
                    )
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(
                f"could not store corpus document {document.path}: {type(exc).__name__}"
            ) from exc

    async def delete_documents_not_in(self, paths: Collection[str]) -> int:
        """Remove documents whose files are gone (their chunks cascade)."""
        try:
            async with self._session_factory() as session, session.begin():
                result = await session.execute(
                    text(
                        "DELETE FROM corpus_documents WHERE NOT (path = ANY(:paths)) RETURNING id"
                    ),
                    {"paths": list(paths)},
                )
                return len(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not delete corpus documents: {type(exc).__name__}") from exc

    async def corpus_keywords(self) -> frozenset[str]:
        """Every document keyword (upper-cased): the exam and scheme names to look for in a
        question when it isn't rewritten."""
        rows = await self._rows("SELECT DISTINCT unnest(keywords) AS keyword FROM corpus_documents")
        return frozenset(str(row.keyword) for row in rows)

    async def chunk_count(self) -> int:
        [row] = await self._rows("SELECT count(*) AS chunks FROM corpus_chunks")
        return int(row.chunks)

    async def vector_candidates(
        self, vector: Sequence[float], grade: int | None, limit: int
    ) -> list[Candidate]:
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(text(f"SET LOCAL hnsw.ef_search = {self.EF_SEARCH}"))
                result = await session.execute(
                    text(
                        """
                        SELECT c.id, c.document_id,
                               1 - (c.embedding <=> CAST(:vector AS vector)) AS similarity
                        FROM corpus_chunks c
                        JOIN corpus_documents d ON d.id = c.document_id
                        WHERE (CAST(:grade AS smallint) IS NULL OR cardinality(d.grades) = 0
                               OR CAST(:grade AS smallint) = ANY(d.grades))
                        ORDER BY c.embedding <=> CAST(:vector AS vector)
                        LIMIT :limit
                        """
                    ),
                    {"vector": VectorColumn.literal(vector), "grade": grade, "limit": limit},
                )
                rows = result.all()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not search the corpus: {type(exc).__name__}") from exc
        return [
            Candidate(row.id, row.document_id, float(row.similarity), keyword_exact=False)
            for row in rows
        ]

    async def keyword_candidates(
        self, keyword_query: str, keywords: Sequence[str], grade: int | None, limit: int
    ) -> list[Candidate]:
        """Chunks whose text matches any word of the query, or whose document has one of
        `keywords` exactly (case-insensitive), best first."""
        rows = await self._rows(
            """
            WITH q AS (SELECT websearch_to_tsquery('simple', :keyword_query) AS tsq)
            SELECT c.id, c.document_id,
                   ts_rank_cd(c.tsv, q.tsq)
                     + CASE WHEN d.keywords && CAST(:keywords AS text[]) THEN 1.0 ELSE 0 END
                     AS score,
                   d.keywords && CAST(:keywords AS text[]) AS exact
            FROM corpus_chunks c
            JOIN corpus_documents d ON d.id = c.document_id, q
            WHERE (c.tsv @@ q.tsq OR d.keywords && CAST(:keywords AS text[]))
              AND (CAST(:grade AS smallint) IS NULL OR cardinality(d.grades) = 0
                   OR CAST(:grade AS smallint) = ANY(d.grades))
            ORDER BY score DESC, c.id
            LIMIT :limit
            """,
            keyword_query=keyword_query,
            keywords=[keyword.upper() for keyword in keywords],
            grade=grade,
            limit=limit,
        )
        return [
            Candidate(row.id, row.document_id, float(row.score), keyword_exact=bool(row.exact))
            for row in rows
        ]

    async def load_chunks(self, chunk_ids: Sequence[UUID]) -> dict[UUID, StoredChunk]:
        if not chunk_ids:
            return {}
        rows = await self._rows(
            """
            SELECT c.id, c.document_id, d.title, c.heading_path, c.text, d.source_url,
                   d.retrieved_on, d.topic
            FROM corpus_chunks c JOIN corpus_documents d ON d.id = c.document_id
            WHERE c.id = ANY(:ids)
            """,
            ids=list(chunk_ids),
        )
        return {
            row.id: StoredChunk(
                chunk_id=row.id,
                document_id=row.document_id,
                title=row.title,
                heading_path=row.heading_path,
                text=row.text,
                source_url=row.source_url,
                retrieved_on=row.retrieved_on,
                topic=CorpusTopic(row.topic),
            )
            for row in rows
        }

    async def _rows(self, sql: str, **params: object) -> list[Row[tuple[object, ...]]]:
        try:
            async with self._session_factory() as session:
                result = await session.execute(text(sql), params)
                return list(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read the corpus: {type(exc).__name__}") from exc


async def _upsert_document(session: AsyncSession, document: DocumentRow) -> UUID:
    result = await session.execute(
        text(
            """
            INSERT INTO corpus_documents (id, path, title, source_url, retrieved_on, topic,
                                          language, grades, keywords, content_sha256)
            VALUES (:id, :path, :title, :source_url, :retrieved_on, :topic, :language,
                    CAST(:grades AS smallint[]), CAST(:keywords AS text[]), :content_sha256)
            ON CONFLICT (path) DO UPDATE SET
                title = EXCLUDED.title, source_url = EXCLUDED.source_url,
                retrieved_on = EXCLUDED.retrieved_on, topic = EXCLUDED.topic,
                language = EXCLUDED.language, grades = EXCLUDED.grades,
                keywords = EXCLUDED.keywords, content_sha256 = EXCLUDED.content_sha256,
                ingested_at = now()
            RETURNING id
            """
        ),
        {
            "id": uuid4(),
            "path": document.path,
            "title": document.title,
            "source_url": document.source_url,
            "retrieved_on": document.retrieved_on,
            "topic": document.topic.value,
            "language": document.language,
            "grades": list(document.grades),
            "keywords": [keyword.upper() for keyword in document.keywords],
            "content_sha256": document.content_sha256,
        },
    )
    return UUID(str(result.scalar_one()))
