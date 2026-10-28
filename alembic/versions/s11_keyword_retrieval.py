"""s11 (2026-10-29): retrieval is keyword-only; corpus chunks lose their embeddings.

Every model Marg calls must be a Meta model (organisers, 2026-10-29), and multilingual-e5-small
isn't one, so the vector half of hybrid retrieval goes: the `embedding` column and its HNSW
index are dropped. The keyword index now uses Postgres's `english` configuration (stemming,
stop-words) over the heading and the text, since the corpus is English and the query rewriter
writes English queries.

Downgrade restores the old columns empty, so it first clears the corpus (derived data:
`marg ingest-corpus` rebuilds it).

Revision ID: s11_keyword_retrieval
Revises: s04_user_leases
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.store.vector_column import VectorColumn

revision: str = "s11_keyword_retrieval"
down_revision: str | Sequence[str] | None = "s04_user_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENGLISH_TSV = "to_tsvector('english', heading_path || ' ' || text)"
SIMPLE_TSV = "to_tsvector('simple', text)"


def upgrade() -> None:
    op.drop_index("ix_corpus_chunks_embedding_hnsw", table_name="corpus_chunks")
    op.drop_column("corpus_chunks", "embedding")
    _replace_tsv(ENGLISH_TSV)


def downgrade() -> None:
    op.execute("DELETE FROM corpus_documents")  # chunks go with them (ON DELETE CASCADE)
    _replace_tsv(SIMPLE_TSV)
    op.add_column("corpus_chunks", sa.Column("embedding", VectorColumn(384), nullable=False))
    op.create_index(
        "ix_corpus_chunks_embedding_hnsw",
        "corpus_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def _replace_tsv(expression: str) -> None:
    op.drop_index("ix_corpus_chunks_tsv", table_name="corpus_chunks")
    op.drop_column("corpus_chunks", "tsv")
    op.add_column(
        "corpus_chunks",
        sa.Column(
            "tsv", postgresql.TSVECTOR(), sa.Computed(expression, persisted=True), nullable=True
        ),
    )
    op.create_index("ix_corpus_chunks_tsv", "corpus_chunks", ["tsv"], postgresql_using="gin")
