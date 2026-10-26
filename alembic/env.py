"""Alembic environment: runs migrations with the async engine.

The URL comes from load_settings(), never from alembic.ini. Never point this at a shared or
deployed database unless the owner asks (CLAUDE.md §8).
"""

import asyncio

from sqlalchemy.engine import Connection

from alembic import context
from app.core.config import load_settings
from app.store.db import create_engine
from app.store.tables import metadata

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=load_settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_engine(load_settings())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
