"""ProfileMemoryRepository: what Marg remembers about a student (s12 §4.7).

Read into the turn context; written by the `UpdateMemory` post-turn task in its own short
transaction after the reply went out. Deleted with the user (cascade).
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.models.base import TurnId, UserHash
from app.domain.models.student import MemoryUpdate, ProfileMemory
from app.store.tables import profile_memory


class ProfileMemoryRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    async def get(session: AsyncSession, user_hash: UserHash) -> ProfileMemory | None:
        row = (
            await session.execute(
                select(profile_memory).where(profile_memory.c.user_hash == user_hash)
            )
        ).first()
        if row is None:
            return None
        return ProfileMemory(
            summary=row.summary,
            ambitions=list(row.ambitions),
            constraints=list(row.constraints),
            updated_at=row.updated_at,
        )

    async def upsert(
        self, user_hash: UserHash, update: MemoryUpdate, source_turn_id: TurnId, prompt_version: str
    ) -> bool:
        """Replace the student's memory. False when the user was deleted meanwhile (the foreign
        key refuses the row): the caller records the task as skipped."""
        values = {
            "user_hash": user_hash,
            "summary": update.summary,
            "ambitions": list(update.ambitions),
            "constraints": list(update.constraints),
            "source_turn_id": source_turn_id,
            "prompt_version": prompt_version,
        }
        statement = insert(profile_memory).values(**values)
        replaced = {key: statement.excluded[key] for key in values if key != "user_hash"}
        statement = statement.on_conflict_do_update(
            index_elements=[profile_memory.c.user_hash], set_={**replaced, "updated_at": func.now()}
        )
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(statement)
        except IntegrityError:
            return False
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not save the memory: {type(exc).__name__}") from exc
        return True
