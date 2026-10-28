"""s11: the RAG corpus: corpus_documents and corpus_chunks, with pgvector (s11 §6).

Chunks carry a 384-dimension embedding (multilingual-e5-small) with an HNSW cosine index, and a
generated `simple` tsvector with a GIN index for the keyword half of hybrid retrieval. No user
data lives here.

Revision ID: s11_corpus_tables
Revises: s13_turn_metrics
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.store.vector_column import VectorColumn

revision: str = "s11_corpus_tables"
down_revision: str | Sequence[str] | None = "s13_turn_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOPICS = (
    "'exams', 'scholarships', 'sports', 'entrepreneurship', 'public_service', 'skilling', "
    "'exposure_fields'"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "corpus_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieved_on", sa.Date(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), server_default=sa.text("'english'"), nullable=False),
        sa.Column(
            "grades",
            postgresql.ARRAY(sa.SmallInteger()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("keywords", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"topic IN ({TOPICS})", name="topic_valid"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_table(
        "corpus_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", VectorColumn(384), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["corpus_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "position"),
    )
    op.create_index(
        "ix_corpus_chunks_embedding_hnsw",
        "corpus_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_corpus_chunks_tsv", "corpus_chunks", ["tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_corpus_chunks_tsv", table_name="corpus_chunks")
    op.drop_index("ix_corpus_chunks_embedding_hnsw", table_name="corpus_chunks")
    op.drop_table("corpus_chunks")
    op.drop_table("corpus_documents")
