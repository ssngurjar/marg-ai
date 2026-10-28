"""OutboxRepository: queued reply parts and their delivery (s04 §4.7, §4.10; s03 §4.8).

`OutboxRepository.enqueue` is the only code that inserts outbox rows, and it accepts only a sealed
`ReplyDelivery`, so nothing reaches a user without passing the safety gate (s07 §4.2).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import RowMapping, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import Channel, OutboxStatus, PartKind
from app.domain.models.base import TurnId, UserHash
from app.domain.models.delivery import PartState
from app.domain.models.reply import OutboundPart, ReplyButton, TemplateRef
from app.domain.rules.delivery_planner import DeliveryPlanner
from app.pipeline.reply_parts_builder import ReplyDelivery
from app.store.tables import outbox_messages, users

_BUTTONS = TypeAdapter(list[ReplyButton])


@dataclass(frozen=True, slots=True)
class OutboxRow:
    """A part claimed for sending (now `sending`), with what's needed to reach its recipient."""

    outbox_id: int
    turn_id: TurnId
    user_hash: UserHash
    channel: Channel
    part: OutboundPart
    attempts: int  # including this one
    address_ciphertext: bytes | None
    last_inbound_at: datetime | None


class OutboxRepository:
    @staticmethod
    async def enqueue(
        session: AsyncSession,
        turn_id: TurnId,
        user_hash: UserHash,
        channel: Channel,
        delivery: ReplyDelivery,
    ) -> int:
        """Insert one pending row per part, inside the caller's finalize transaction.

        Re-running for the same turn inserts nothing new: (turn_id, part_no) is unique.
        """
        inserted = 0
        for part in delivery.parts:
            statement = (
                insert(outbox_messages)
                .values(
                    turn_id=turn_id,
                    part_no=part.part_no,
                    user_hash=user_hash,
                    channel=channel.value,
                    kind=part.kind.value,
                    text=part.text,
                    audio_blob_id=part.audio_blob_id,
                    image_blob_id=part.image_blob_id,
                    buttons=[button.model_dump(mode="json") for button in part.buttons],
                    template=part.template.model_dump(mode="json") if part.template else None,
                    status=OutboxStatus.PENDING.value,
                )
                .on_conflict_do_nothing(index_elements=["turn_id", "part_no"])
                .returning(outbox_messages.c.id)
            )
            result = await session.execute(statement)
            inserted += len(result.all())
        return inserted

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next_part(self, turn_id: TurnId) -> OutboxRow | None:
        """Mark this turn's next sendable part `sending` and return it, or None.

        Parts go strictly in order: a later part waits while an earlier one is pending or sending.
        """
        try:
            async with self._session_factory() as session, session.begin():
                rows = (
                    await session.execute(
                        select(
                            outbox_messages.c.part_no,
                            outbox_messages.c.status,
                            outbox_messages.c.available_at <= func.now(),
                        )
                        .where(outbox_messages.c.turn_id == turn_id)
                        .with_for_update()
                    )
                ).all()
                states = [
                    PartState(part_no=row[0], status=OutboxStatus(row[1]), due=bool(row[2]))
                    for row in rows
                ]
                part_no = DeliveryPlanner.next_part_to_send(states)
                if part_no is None:
                    return None
                claimed = (
                    await session.execute(
                        update(outbox_messages)
                        .where(
                            and_(
                                outbox_messages.c.turn_id == turn_id,
                                outbox_messages.c.part_no == part_no,
                            )
                        )
                        .values(
                            status=OutboxStatus.SENDING.value,
                            attempts=outbox_messages.c.attempts + 1,
                            sending_since=func.now(),
                        )
                        .returning(outbox_messages)
                    )
                ).one()
                recipient = (
                    await session.execute(
                        select(users.c.address_ciphertext, users.c.last_inbound_at).where(
                            users.c.user_hash == claimed.user_hash
                        )
                    )
                ).one()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not claim an outbox part: {type(exc).__name__}") from exc
        return OutboxRow(
            outbox_id=claimed.id,
            turn_id=TurnId(claimed.turn_id),
            user_hash=UserHash(claimed.user_hash),
            channel=Channel(claimed.channel),
            part=_part(claimed._mapping),
            attempts=claimed.attempts,
            address_ciphertext=(
                bytes(recipient.address_ciphertext) if recipient.address_ciphertext else None
            ),
            last_inbound_at=recipient.last_inbound_at,
        )

    async def mark_sent(
        self, outbox_id: int, provider_message_id: str | None, sent_at: datetime
    ) -> None:
        await self._update(
            outbox_id,
            status=OutboxStatus.SENT.value,
            provider_message_id=provider_message_id,
            sent_at=sent_at,
            sending_since=None,
            last_error=None,
        )

    async def mark_retry(self, outbox_id: int, error_code: str, delay: timedelta) -> None:
        """Back to pending, due `delay` from now by the database's clock (the one claims use)."""
        await self._update(
            outbox_id,
            status=OutboxStatus.PENDING.value,
            available_at=func.now() + delay,
            sending_since=None,
            last_error=error_code,
        )

    async def mark_failed(self, outbox_id: int, error_code: str) -> None:
        await self._update(
            outbox_id, status=OutboxStatus.FAILED.value, sending_since=None, last_error=error_code
        )

    async def reset_stuck_sending(self, stuck_after: timedelta) -> int:
        """Maintenance (s04 §4.10): a part `sending` for longer than `stuck_after` was left by a
        dead worker, and goes back to pending. A live worker's send is younger, so it's untouched.

        If Meta had already accepted it, the user gets it twice: the one duplicate window,
        logged by the caller.
        """
        try:
            async with self._session_factory() as session, session.begin():
                result = await session.execute(
                    update(outbox_messages)
                    .where(
                        and_(
                            outbox_messages.c.status == OutboxStatus.SENDING.value,
                            outbox_messages.c.sending_since < func.now() - stuck_after,
                        )
                    )
                    .values(status=OutboxStatus.PENDING.value, sending_since=None)
                    .returning(outbox_messages.c.id)
                )
                return len(result.all())
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not reset stuck parts: {type(exc).__name__}") from exc

    async def turns_with_due_parts(self) -> list[TurnId]:
        """Turns with a pending part whose retry time has come (the outbox loop)."""
        query = (
            select(outbox_messages.c.turn_id)
            .where(
                and_(
                    outbox_messages.c.status == OutboxStatus.PENDING.value,
                    outbox_messages.c.available_at <= func.now(),
                )
            )
            .distinct()
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(query)).scalars().all()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not list due outbox parts: {type(exc).__name__}") from exc
        return [TurnId(turn_id) for turn_id in rows]

    async def apply_status_update(
        self, provider_message_id: str, reported: OutboxStatus, at: datetime, error_code: int | None
    ) -> bool:
        """Apply a status webhook (s03 §4.8). Statuses only move forward; returns False when the
        message isn't ours (or was deleted with its user)."""
        try:
            async with self._session_factory() as session, session.begin():
                current = (
                    await session.execute(
                        select(outbox_messages.c.id, outbox_messages.c.status)
                        .where(outbox_messages.c.provider_message_id == provider_message_id)
                        .with_for_update()
                    )
                ).first()
                if current is None:
                    return False
                new_status = DeliveryPlanner.next_status(OutboxStatus(current.status), reported)
                values: dict[str, object] = {"status": new_status.value}
                if new_status in {OutboxStatus.DELIVERED, OutboxStatus.READ}:
                    values["delivered_at"] = func.coalesce(outbox_messages.c.delivered_at, at)
                if new_status is OutboxStatus.READ:
                    values["read_at"] = func.coalesce(outbox_messages.c.read_at, at)
                if new_status is OutboxStatus.FAILED and error_code is not None:
                    values["last_error"] = f"whatsapp:{error_code}"
                await session.execute(
                    update(outbox_messages).where(outbox_messages.c.id == current.id).values(values)
                )
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not apply a status update: {type(exc).__name__}") from exc
        return True

    async def _update(self, outbox_id: int, **values: object) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    update(outbox_messages).where(outbox_messages.c.id == outbox_id).values(values)
                )
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not update an outbox part: {type(exc).__name__}") from exc


def _part(row: RowMapping) -> OutboundPart:
    """The OutboundPart an outbox row holds, validated on the way out of the database."""
    template = row["template"]
    try:
        return OutboundPart(
            part_no=row["part_no"],
            kind=PartKind(row["kind"]),
            text=row["text"],
            audio_blob_id=row["audio_blob_id"],
            image_blob_id=row["image_blob_id"],
            buttons=_BUTTONS.validate_python(row["buttons"]),
            template=TemplateRef.model_validate(template) if template is not None else None,
        )
    except ValidationError as exc:
        raise StoreError(f"outbox row {row['id']} doesn't hold a valid part") from exc
