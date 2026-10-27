"""Turns: claiming a user's pending messages, loading the context, finalizing (s04 §4.4 to §4.7).

Exception E1 (mvp-scope §4.1): one process with one lock per user, so there are no leases. Each
public method is one transaction. The only SQL for turns and the inbox's processing columns.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import assert_never
from uuid import uuid4

from sqlalchemy import Row, and_, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import (
    Channel,
    ConversationState,
    FailureKind,
    FixedReplyKind,
    InboxStatus,
    Language,
    MessageKind,
    Role,
    Route,
    StepName,
    TurnStatus,
)
from app.domain.models.base import TurnId, UserHash
from app.domain.models.message import InboundMessage, MediaRef
from app.domain.models.turn import Exchange, QueuedMessage, TurnContext, UserProfile
from app.domain.models.writes import (
    ChildTalkConsent,
    LearnerUpsert,
    MarkPurgeAfterDelivery,
    ProfileChange,
    TurnWrite,
)
from app.domain.rules.session_rules import SessionRules
from app.domain.rules.turn_batcher import TurnBatcher
from app.pipeline.reply_parts_builder import ReplyDelivery
from app.store.repositories.learner_repository import LearnerRepository
from app.store.repositories.outbox_repository import OutboxRepository
from app.store.repositories.user_repository import UserRepository
from app.store.tables import inbox_messages, turns, users

RETENTION_BATCH = 1000


@dataclass(frozen=True, slots=True)
class StartedTurn:
    """A turn that has taken some of a user's pending messages (rows now `processing`)."""

    turn_id: TurnId
    user_hash: UserHash
    channel: Channel
    queued: list[QueuedMessage]  # oldest first


@dataclass(frozen=True, slots=True)
class FinishedTurn:
    """What finalize writes to the turn row, mapped by the worker from the TurnOutcome."""

    route: Route | None
    fixed_reply_kind: FixedReplyKind | None
    user_text: str | None  # stored as NULL when fixed_reply_kind is CRISIS
    reply_text: str | None
    reply_register: Language | None
    prompt_versions: Mapping[str, str]
    failure_step: StepName | None
    failure_kind: FailureKind | None
    inbox_status: InboxStatus  # DONE, or FAILED for a poisoned turn


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    parts_enqueued: int
    more_pending: bool  # the user has newer pending messages: run another turn


class TurnRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def start_turn(
        self, user_hash: UserHash, max_messages: int, worker_id: str
    ) -> StartedTurn | None:
        """Take this user's due pending messages (oldest first, at most `max_messages`) into a
        new `processing` turn. None if nothing is due."""
        try:
            async with self._session_factory() as session, session.begin():
                pending = await _lock_due_pending(session, user_hash)
                batch = TurnBatcher.choose_batch(pending, max_messages)
                if not batch:
                    return None
                channel = batch[0].message.channel
                turn_id = TurnId(uuid4())
                await session.execute(
                    turns.insert().values(
                        id=turn_id,
                        user_hash=user_hash,
                        status=TurnStatus.PROCESSING.value,
                        worker_id=worker_id,
                    )
                )
                await session.execute(
                    update(inbox_messages)
                    .where(inbox_messages.c.id.in_([queued.inbox_id for queued in batch]))
                    .values(status=InboxStatus.PROCESSING.value, turn_id=turn_id)
                )
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not start a turn: {type(exc).__name__}") from exc
        return StartedTurn(turn_id=turn_id, user_hash=user_hash, channel=channel, queued=batch)

    async def load_context(self, started: StartedTurn, recent_exchanges: int) -> TurnContext:
        """Everything the pipeline reads for this turn (s04 §4.5), in one read."""
        try:
            async with self._session_factory() as session:
                profile = await _load_profile(session, started.user_hash)
                user_learners = await LearnerRepository.list_for(session, started.user_hash)
                exchanges = await _recent_exchanges(session, started.user_hash, recent_exchanges)
                previous_started_at = await _previous_turn_start(session, started)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not load the turn context: {type(exc).__name__}") from exc
        messages = [queued.message for queued in started.queued]
        return TurnContext(
            turn_id=started.turn_id,
            profile=profile,
            learners=user_learners,
            messages=messages,
            recent_exchanges=exchanges,
            is_session_start=SessionRules.is_session_start(
                previous_started_at, messages[0].provider_sent_at
            ),
        )

    async def finalize(
        self,
        started: StartedTurn,
        finished: FinishedTurn,
        delivery: ReplyDelivery | None,
        writes: Sequence[TurnWrite] = (),
    ) -> FinalizeResult:
        """Apply the turn's writes, queue the reply, complete the turn and close its messages,
        all or nothing (s04 §4.7, contracts §2.4).

        `delivery` is None only for a stale turn, which answers nothing. Raises LeaseLost (and
        commits nothing) when a profile change finds the user in another state.
        """
        user_text = (
            None if finished.fixed_reply_kind is FixedReplyKind.CRISIS else finished.user_text
        )
        try:
            async with self._session_factory() as session, session.begin():
                for write in writes:
                    await _apply(session, started, write)
                parts = 0
                if delivery is not None:
                    parts = await OutboxRepository.enqueue(
                        session, started.turn_id, started.user_hash, started.channel, delivery
                    )
                await session.execute(
                    update(turns)
                    .where(turns.c.id == started.turn_id)
                    .values(
                        status=TurnStatus.COMPLETED.value,
                        route=_value(finished.route),
                        user_text=user_text,
                        reply_text=finished.reply_text,
                        reply_register=_value(finished.reply_register),
                        fixed_reply_kind=_value(finished.fixed_reply_kind),
                        prompt_versions=dict(finished.prompt_versions),
                        failure_step=_value(finished.failure_step),
                        failure_kind=_value(finished.failure_kind),
                        completed_at=func.now(),
                    )
                )
                await session.execute(
                    update(inbox_messages)
                    .where(inbox_messages.c.turn_id == started.turn_id)
                    .values(status=finished.inbox_status.value)
                )
                more_pending = await _has_pending(session, started.user_hash)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not finalize the turn: {type(exc).__name__}") from exc
        return FinalizeResult(parts_enqueued=parts, more_pending=more_pending)

    async def abandon(
        self, started: StartedTurn, *, count_attempt: bool, retry_after: timedelta
    ) -> None:
        """The turn crashed or was cut short: mark it failed and put its messages back.

        `count_attempt` is False for a shutdown, which isn't the message's fault.
        """
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    update(turns)
                    .where(turns.c.id == started.turn_id)
                    .values(
                        status=TurnStatus.FAILED.value,
                        failure_kind=FailureKind.INTERNAL.value,
                        completed_at=func.now(),
                    )
                )
                await session.execute(
                    update(inbox_messages)
                    .where(
                        and_(
                            inbox_messages.c.turn_id == started.turn_id,
                            inbox_messages.c.status == InboxStatus.PROCESSING.value,
                        )
                    )
                    .values(
                        status=InboxStatus.PENDING.value,
                        attempts=inbox_messages.c.attempts + (1 if count_attempt else 0),
                        available_at=func.now() + retry_after,
                    )
                )
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not abandon the turn: {type(exc).__name__}") from exc

    async def recover_unfinished(self, retry_after: timedelta) -> int:
        """Startup recovery (E1): turns left `processing` by a dead process are failed, and their
        messages go back to pending with one more attempt. Returns how many messages."""
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    update(turns)
                    .where(turns.c.status == TurnStatus.PROCESSING.value)
                    .values(
                        status=TurnStatus.FAILED.value,
                        failure_kind=FailureKind.INTERNAL.value,
                        completed_at=func.now(),
                    )
                )
                result = await session.execute(
                    update(inbox_messages)
                    .where(inbox_messages.c.status == InboxStatus.PROCESSING.value)
                    .values(
                        status=InboxStatus.PENDING.value,
                        attempts=inbox_messages.c.attempts + 1,
                        available_at=func.now() + retry_after,
                    )
                    .returning(inbox_messages.c.id)
                )
                return len(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not recover unfinished turns: {type(exc).__name__}") from exc

    async def users_with_pending(self) -> list[UserHash]:
        """Every user with a pending message, due or not (each gets a dispatcher task)."""
        query = (
            select(inbox_messages.c.user_hash)
            .where(inbox_messages.c.status == InboxStatus.PENDING.value)
            .distinct()
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(query)).scalars().all()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not list pending users: {type(exc).__name__}") from exc
        return [UserHash(user_hash) for user_hash in rows]

    async def next_pending_at(self, user_hash: UserHash) -> datetime | None:
        """When this user's earliest pending message becomes due, or None if none is pending."""
        query = select(func.min(inbox_messages.c.available_at)).where(
            and_(
                inbox_messages.c.user_hash == user_hash,
                inbox_messages.c.status == InboxStatus.PENDING.value,
            )
        )
        try:
            async with self._session_factory() as session:
                earliest = (await session.execute(query)).scalar_one_or_none()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read pending messages: {type(exc).__name__}") from exc
        return _optional_datetime(earliest)

    async def clear_expired_text(
        self, turn_text_before: datetime, raw_payload_before: datetime
    ) -> int:
        """Retention (data-model §4): turn text and raw payloads past their window, in batches."""
        cleared = 0
        try:
            async with self._session_factory() as session, session.begin():
                expired_turns = (
                    select(turns.c.id)
                    .where(
                        and_(
                            turns.c.completed_at < turn_text_before,
                            (turns.c.user_text.is_not(None)) | (turns.c.reply_text.is_not(None)),
                        )
                    )
                    .limit(RETENTION_BATCH)
                )
                result = await session.execute(
                    update(turns)
                    .where(turns.c.id.in_(expired_turns))
                    .values(user_text=None, reply_text=None)
                    .returning(turns.c.id)
                )
                cleared += len(result.all())
                expired_payloads = (
                    select(inbox_messages.c.id)
                    .where(
                        and_(
                            inbox_messages.c.raw_payload.is_not(None),
                            inbox_messages.c.received_at < raw_payload_before,
                        )
                    )
                    .limit(RETENTION_BATCH)
                )
                result = await session.execute(
                    update(inbox_messages)
                    .where(inbox_messages.c.id.in_(expired_payloads))
                    .values(raw_payload=None)
                    .returning(inbox_messages.c.id)
                )
                cleared += len(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not clear expired text: {type(exc).__name__}") from exc
        return cleared


async def _lock_due_pending(session: AsyncSession, user_hash: UserHash) -> list[QueuedMessage]:
    query = (
        select(inbox_messages)
        .where(
            and_(
                inbox_messages.c.user_hash == user_hash,
                inbox_messages.c.status == InboxStatus.PENDING.value,
                inbox_messages.c.available_at <= func.now(),
            )
        )
        .with_for_update(skip_locked=True)
    )
    rows = (await session.execute(query)).all()
    return [_queued_message(row) for row in rows]


def _queued_message(row: Row[tuple[object, ...]]) -> QueuedMessage:
    mapping = row._mapping
    media = None
    media_provider_id = mapping["media_provider_id"]
    channel = Channel(str(mapping["channel"]))
    if media_provider_id is not None:
        media = MediaRef(
            channel=channel,
            provider_media_id=str(media_provider_id),
            blob_id=None,
            mime_type=str(mapping["media_mime_type"]),
        )
    message = InboundMessage(
        channel=channel,
        external_id=str(mapping["external_id"]),
        user_hash=UserHash(str(mapping["user_hash"])),
        kind=MessageKind(str(mapping["kind"])),
        text=_optional_str(mapping["text"]),
        media=media,
        interactive_reply_id=_optional_str(mapping["interactive_reply_id"]),
        provider_sent_at=_datetime(mapping["provider_sent_at"]),
        received_at=_datetime(mapping["received_at"]),
    )
    return QueuedMessage(
        inbox_id=_int(mapping["id"]), message=message, attempts=_int(mapping["attempts"])
    )


async def _apply(session: AsyncSession, started: StartedTurn, write: TurnWrite) -> None:
    """One write, in list order, inside the finalize transaction."""
    match write:
        case ProfileChange():
            await UserRepository.apply_profile_change(session, started.user_hash, write)
        case LearnerUpsert():
            await LearnerRepository.upsert(session, started.user_hash, write)
        case ChildTalkConsent():
            await LearnerRepository.set_child_talk(session, started.user_hash, write)
        case MarkPurgeAfterDelivery():
            await UserRepository.mark_purge_after(session, started.user_hash, started.turn_id)
        case _:
            assert_never(write)


async def _load_profile(session: AsyncSession, user_hash: UserHash) -> UserProfile:
    query = select(users).where(users.c.user_hash == user_hash)
    row = (await session.execute(query)).one()
    return UserProfile(
        user_hash=user_hash,
        channel=Channel(row.channel),
        state=ConversationState(row.state),
        role=Role(row.role) if row.role else None,
        grade=row.grade,
        subject=row.subject,
        district=row.district,
        language=Language(row.language) if row.language else None,
        guardian_confirmed=row.guardian_confirmed,
        consented_at=row.consented_at,
        last_inbound_at=row.last_inbound_at,
        pending_question=row.pending_question,
    )


async def _recent_exchanges(
    session: AsyncSession, user_hash: UserHash, limit: int
) -> list[Exchange]:
    if limit == 0:
        return []
    query = (
        select(turns.c.user_text, turns.c.reply_text, turns.c.route, turns.c.started_at)
        .where(
            and_(
                turns.c.user_hash == user_hash,
                turns.c.status == TurnStatus.COMPLETED.value,
                turns.c.user_text.is_not(None),
                turns.c.reply_text.is_not(None),
                turns.c.route.is_not(None),
            )
        )
        .order_by(turns.c.started_at.desc())
        .limit(limit)
    )
    newest_first = (await session.execute(query)).all()
    exchanges = [
        Exchange(
            user_text=row.user_text,
            reply_text=row.reply_text,
            route=Route(row.route),
            at=row.started_at,
        )
        for row in newest_first
    ]
    exchanges.reverse()
    return exchanges


async def _previous_turn_start(session: AsyncSession, started: StartedTurn) -> datetime | None:
    query = select(func.max(turns.c.started_at)).where(
        and_(turns.c.user_hash == started.user_hash, turns.c.id != started.turn_id)
    )
    return _optional_datetime((await session.execute(query)).scalar_one_or_none())


async def _has_pending(session: AsyncSession, user_hash: UserHash) -> bool:
    query = (
        select(inbox_messages.c.id)
        .where(
            and_(
                inbox_messages.c.user_hash == user_hash,
                inbox_messages.c.status == InboxStatus.PENDING.value,
            )
        )
        .limit(1)
    )
    return (await session.execute(query)).first() is not None


def _value(member: Route | FixedReplyKind | Language | StepName | FailureKind | None) -> str | None:
    return member.value if member is not None else None


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _int(value: object) -> int:
    if not isinstance(value, int):
        raise StoreError(f"expected an integer column, got {type(value).__name__}")
    return value


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise StoreError(f"expected a timestamp column, got {type(value).__name__}")
    return value


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _datetime(value)
