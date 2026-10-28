"""VectorColumn: pgvector's `vector(n)` column type, kept for the s11 migrations only.

Since 2026-10-29 retrieval is keyword-only and no table has a vector column; the migrations
that created and dropped one still need the type.
"""

from sqlalchemy.types import UserDefinedType


class VectorColumn(UserDefinedType[str]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dimensions})"
