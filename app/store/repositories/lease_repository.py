"""Per-user turn leases (s04 §4.3, §4.8): the only SQL for `users.lease_owner`.

A worker runs a user's turn only while it holds that user's lease, so several workers can share
one database without two of them answering the same person. Every claim uses `FOR UPDATE SKIP
LOCKED`, so workers never block each other. A dead worker's lease expires, and only the
maintenance takeover clears it, after failing the dead turn and putting its messages back.
Finalize and abandon (TurnRepository) release the lease in their own transactions.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import TextClause

from app.core.errors import StoreError
from app.domain.models.base import UserHash
from app.domain.rules.turn_batcher import TurnBatcher

CLAIM_USER = text(
    """
    WITH candidate AS (
        SELECT u.user_hash
        FROM inbox_messages i
        JOIN users u ON u.user_hash = i.user_hash
        WHERE i.status = 'pending'
          AND i.available_at <= now()
          AND u.lease_owner IS NULL
          AND NOT EXISTS (
                SELECT 1 FROM inbox_messages newer
                WHERE newer.user_hash = i.user_hash
                  AND newer.status = 'pending'
                  AND newer.received_at > now() - make_interval(secs => :debounce_s))
        ORDER BY i.available_at, i.id
        LIMIT 1
        FOR UPDATE OF u SKIP LOCKED
    )
    UPDATE users
    SET lease_owner = :worker_id,
        lease_expires_at = now() + make_interval(secs => :lease_s),
        updated_at = now()
    FROM candidate
    WHERE users.user_hash = candidate.user_hash
    RETURNING users.user_hash
    """
)
"""s04 §4.3. An expired lease isn't claimable here: the takeover clears it first (§4.8)."""

ACQUIRE = text(
    """
    UPDATE users
    SET lease_owner = :worker_id,
        lease_expires_at = now() + make_interval(secs => :lease_s),
        updated_at = now()
    WHERE user_hash = :user_hash AND lease_owner IS NULL
    RETURNING 1
    """
)

RENEW = text(
    """
    UPDATE users SET lease_expires_at = now() + make_interval(secs => :lease_s)
    WHERE user_hash = :user_hash AND lease_owner = :worker_id
    RETURNING 1
    """
)

RELEASE = text(
    """
    UPDATE users SET lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
    WHERE user_hash = :user_hash AND lease_owner = :worker_id
    """
)

TAKE_OVER = text(
    """
    WITH expired AS (
        SELECT user_hash FROM users
        WHERE lease_owner IS NOT NULL AND lease_expires_at < now()
        FOR UPDATE SKIP LOCKED
    ),
    released AS (
        UPDATE users u SET lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
        FROM expired WHERE u.user_hash = expired.user_hash
        RETURNING u.user_hash
    ),
    dead_turns AS (
        UPDATE turns t SET status = 'failed', failure_kind = 'internal', completed_at = now()
        FROM users u
        WHERE t.user_hash = u.user_hash
          AND t.status = 'processing'
          AND (u.user_hash IN (SELECT user_hash FROM expired) OR u.lease_owner IS NULL)
        RETURNING t.id
    ),
    reset_inbox AS (
        UPDATE inbox_messages i
        SET status = 'pending', turn_id = NULL, attempts = i.attempts + 1,
            available_at = now() + make_interval(
                secs => least(:max_backoff_s, :base_backoff_s * power(2, i.attempts)))
        FROM dead_turns WHERE i.turn_id = dead_turns.id AND i.status = 'processing'
        RETURNING i.id
    )
    SELECT (SELECT count(*) FROM released) AS leases,
           (SELECT count(*) FROM dead_turns) AS turns,
           (SELECT count(*) FROM reset_inbox) AS messages
    """
)
"""s04 §4.8, plus a `processing` turn whose user holds no lease at all: nobody is running it
(a lease is taken before a turn starts and released in the transaction that ends it)."""

SECONDS_UNTIL_CLAIMABLE = text(
    """
    SELECT extract(epoch FROM min(greatest(
               i.available_at, i.received_at + make_interval(secs => :debounce_s))) - now())
    FROM inbox_messages i
    WHERE i.status = 'pending'
    """
)


@dataclass(frozen=True, slots=True)
class Takeover:
    leases: int  # expired leases cleared
    turns: int  # dead turns marked failed
    messages: int  # their messages back to pending, one attempt more


@dataclass(frozen=True, slots=True)
class LeaseTimes:
    lease: timedelta  # LEASE_DURATION_S
    debounce: timedelta  # TURN_DEBOUNCE_MS: a user who just wrote waits for the rest of the burst


class LeaseRepository:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], times: LeaseTimes
    ) -> None:
        self._session_factory = session_factory
        self._times = times

    async def claim_user(self, worker_id: str) -> UserHash | None:
        """Lease the user whose oldest due message has waited longest, if any is claimable."""
        claimed = await self._returning(
            CLAIM_USER,
            {
                "worker_id": worker_id,
                "lease_s": self._times.lease.total_seconds(),
                "debounce_s": self._times.debounce.total_seconds(),
            },
            "claim a user",
        )
        return UserHash(str(claimed)) if claimed is not None else None

    async def acquire(self, user_hash: UserHash, worker_id: str) -> bool:
        """Lease this user if nobody holds them: for running one known user's turn directly
        (evals, tests). False when another worker holds the lease."""
        acquired = await self._returning(
            ACQUIRE,
            {
                "user_hash": user_hash,
                "worker_id": worker_id,
                "lease_s": self._times.lease.total_seconds(),
            },
            "acquire a lease",
        )
        return acquired is not None

    async def renew(self, user_hash: UserHash, worker_id: str) -> bool:
        """The heartbeat. False when the lease is no longer this worker's (lost)."""
        renewed = await self._returning(
            RENEW,
            {
                "user_hash": user_hash,
                "worker_id": worker_id,
                "lease_s": self._times.lease.total_seconds(),
            },
            "renew a lease",
        )
        return renewed is not None

    async def release(self, user_hash: UserHash, worker_id: str) -> None:
        """Give the lease back when a claimed user had nothing to run."""
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(RELEASE, {"user_hash": user_hash, "worker_id": worker_id})
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not release a lease: {type(exc).__name__}") from exc

    async def take_over_expired(self) -> Takeover:
        """Clear expired leases, fail the turns nobody is running and put their messages back
        with TurnBatcher's backoff (maintenance, s04 §4.8). Idempotent."""
        try:
            async with self._session_factory() as session, session.begin():
                row = (
                    await session.execute(
                        TAKE_OVER,
                        {
                            "base_backoff_s": TurnBatcher.RETRY_BASE.total_seconds(),
                            "max_backoff_s": TurnBatcher.RETRY_CAP.total_seconds(),
                        },
                    )
                ).one()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not take over expired leases: {type(exc).__name__}") from exc
        return Takeover(leases=int(row.leases), turns=int(row.turns), messages=int(row.messages))

    async def until_claimable(self) -> timedelta | None:
        """How long until some pending message is past its backoff and its burst; None when
        nothing is pending. Zero or less: claimable now."""
        try:
            async with self._session_factory() as session:
                seconds = (
                    await session.execute(
                        SECONDS_UNTIL_CLAIMABLE,
                        {"debounce_s": self._times.debounce.total_seconds()},
                    )
                ).scalar_one_or_none()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read pending messages: {type(exc).__name__}") from exc
        if seconds is None:
            return None
        return timedelta(seconds=float(seconds))

    async def _returning(
        self, statement: TextClause, params: dict[str, str | float], action: str
    ) -> object | None:
        try:
            async with self._session_factory() as session, session.begin():
                result = await session.execute(statement, params)
                return result.scalar_one_or_none()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not {action}: {type(exc).__name__}") from exc
