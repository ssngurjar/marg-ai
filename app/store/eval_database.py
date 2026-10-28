"""EvalDatabase: the disposable database each `marg eval` run creates and drops (s15 §4.2).

Only on the TEST Postgres (EVAL_DATABASE_ADMIN_URL, docker-compose.test.yml): the run never
touches the dev or deployed database. Names are checked against a fixed pattern before they
reach SQL, because CREATE and DROP DATABASE can't take bound parameters.
"""

import re
from typing import ClassVar

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine as sqlalchemy_create_async_engine

from app.core.errors import ConfigError, StoreError


class EvalDatabase:
    NAME: ClassVar[re.Pattern[str]] = re.compile(r"^marg_eval_[0-9a-z_]{1,40}$")

    @staticmethod
    def url_for(admin_url: SecretStr, name: str) -> SecretStr:
        """The admin URL pointed at database `name` (same server and credentials)."""
        EvalDatabase._check(name)
        try:
            pointed = make_url(admin_url.get_secret_value()).set(database=name)
        except ArgumentError as exc:
            raise ConfigError("EVAL_DATABASE_ADMIN_URL is not a database URL") from exc
        return SecretStr(pointed.render_as_string(hide_password=False))

    @staticmethod
    async def create(admin_url: SecretStr, name: str) -> SecretStr:
        """Create database `name`; returns its URL. Raises StoreError when the server refuses."""
        await EvalDatabase._run(admin_url, f'CREATE DATABASE "{EvalDatabase._check(name)}"')
        return EvalDatabase.url_for(admin_url, name)

    @staticmethod
    async def drop(admin_url: SecretStr, name: str) -> None:
        """Drop it, closing anything still connected to it first."""
        await EvalDatabase._run(
            admin_url, f'DROP DATABASE IF EXISTS "{EvalDatabase._check(name)}" WITH (FORCE)'
        )

    @staticmethod
    def _check(name: str) -> str:
        if not EvalDatabase.NAME.fullmatch(name):
            raise ConfigError(f"eval database name {name!r} doesn't match marg_eval_*")
        return name

    @staticmethod
    async def _run(admin_url: SecretStr, statement: str) -> None:
        engine = sqlalchemy_create_async_engine(
            admin_url.get_secret_value(), isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as connection:
                await connection.execute(text(statement))
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"eval database: {type(exc).__name__}") from exc
        finally:
            await engine.dispose()
