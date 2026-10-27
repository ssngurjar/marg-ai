"""Users: onboarding changes, consent records and delete-my-data (s08 §4.9 to §4.11).

The finalize transaction calls the session-level methods, so a profile change commits with the
reply's outbox rows or not at all. Purging is one DELETE of the users row: every table that
holds the user's hash, or a learner of theirs, cascades from it.
"""

from datetime import timedelta

from sqlalchemy import and_, delete, exists, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.dml import ReturningDelete

from app.core.errors import LeaseLost, StoreError
from app.domain.enums import OutboxStatus
from app.domain.models.base import TurnId, UserHash
from app.domain.models.writes import ProfileChange
from app.store.tables import consent_events, outbox_messages, turns, users

_UNDELIVERED = (OutboxStatus.PENDING.value, OutboxStatus.SENDING.value)


class UserRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    async def apply_profile_change(
        session: AsyncSession, user_hash: UserHash, change: ProfileChange
    ) -> None:
        """Inside finalize. Raises LeaseLost when the user isn't in `expected_state` any more."""
        values: dict[str, object] = {"state": change.new_state.value, "updated_at": func.now()}
        optional_fields = {
            "role": change.role.value if change.role else None,
            "grade": change.grade,
            "subject": change.subject,
            "district": change.district,
            "language": change.language.value if change.language else None,
            "guardian_confirmed": change.guardian_confirmed,
            "consented_at": change.consented_at,
            "pending_question": change.pending_question,
        }
        values.update({name: value for name, value in optional_fields.items() if value is not None})
        if change.clear_pending_question:
            values["pending_question"] = None
        result = await session.execute(
            update(users)
            .where(
                and_(
                    users.c.user_hash == user_hash,
                    users.c.state == change.expected_state.value,
                )
            )
            .values(**values)
            .returning(users.c.user_hash)
        )
        if result.first() is None:
            raise LeaseLost(f"user is no longer in state {change.expected_state.value}")
        if change.consent_events:
            if change.consent_prompt_version is None:
                raise StoreError("consent events need the version of the copy that was shown")
            for kind in change.consent_events:  # one or two per turn
                await session.execute(
                    insert(consent_events).values(
                        user_hash=user_hash,
                        kind=kind.value,
                        prompt_version=change.consent_prompt_version,
                        recorded_at=func.now(),
                    )
                )

    @staticmethod
    async def mark_purge_after(session: AsyncSession, user_hash: UserHash, turn_id: TurnId) -> None:
        await session.execute(
            update(users).where(users.c.user_hash == user_hash).values(purge_after_turn_id=turn_id)
        )

    async def purge_if_delivered(self, turn_id: TurnId) -> bool:
        """Delete the user who asked for it in this turn, once no part of it waits to be sent.

        False when no user is marked for this turn, or a part is still pending (the sweep, or a
        later delivery pass, finishes it)."""
        still_sending = exists().where(
            and_(
                outbox_messages.c.turn_id == turn_id,
                outbox_messages.c.status.in_(_UNDELIVERED),
            )
        )
        statement = (
            delete(users)
            .where(and_(users.c.purge_after_turn_id == turn_id, ~still_sending))
            .returning(users.c.user_hash)
        )
        return await self._delete(statement)

    async def sweep_purges(self, older_than: timedelta) -> int:
        """Purge every marked user whose turn completed `older_than` ago, delivered or not."""
        overdue = select(turns.c.id).where(turns.c.completed_at < func.now() - older_than)
        statement = (
            delete(users)
            .where(users.c.purge_after_turn_id.in_(overdue))
            .returning(users.c.user_hash)
        )
        try:
            async with self._session_factory() as session, session.begin():
                return len((await session.execute(statement)).all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not sweep purges: {type(exc).__name__}") from exc

    async def purge_user(self, user_hash: UserHash) -> bool:
        """Delete the user and, by cascade, everything about them. False if already gone."""
        statement = delete(users).where(users.c.user_hash == user_hash).returning(users.c.user_hash)
        return await self._delete(statement)

    async def _delete(self, statement: ReturningDelete[tuple[str]]) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                return (await session.execute(statement)).first() is not None
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not purge a user: {type(exc).__name__}") from exc
