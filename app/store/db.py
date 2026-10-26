"""Async database engine and sessions. The only place a connection is opened."""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as sqlalchemy_create_async_engine

from app.core.config import DatabaseSettings
from app.core.errors import StoreError


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """asyncpg engine sized for Neon's pooled endpoint, which closes idle connections."""
    return sqlalchemy_create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=300,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping(engine: AsyncEngine) -> None:
    """Run SELECT 1.

    Raises StoreError, chained from the driver error, when the database can't answer.
    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise StoreError(f"database ping failed: {type(exc).__name__}") from exc
