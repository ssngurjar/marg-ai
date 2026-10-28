"""VectorColumn: pgvector's `vector(n)` column type, for table definitions only (s11 §6).

Vectors are written and compared in SQL with `CAST(:v AS vector)` from a "[0.1,0.2,…]" literal
(VectorColumn.literal), so no pgvector Python package is needed and the column is never read
back into Python.
"""

from collections.abc import Sequence

from sqlalchemy.types import UserDefinedType


class VectorColumn(UserDefinedType[str]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dimensions})"

    @staticmethod
    def literal(vector: Sequence[float]) -> str:
        """The text form pgvector parses: "[0.1,0.2,…]"."""
        return "[" + ",".join(repr(float(value)) for value in vector) + "]"
