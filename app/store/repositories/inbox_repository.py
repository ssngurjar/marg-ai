"""Storing inbound WhatsApp messages (s03 §4.5, §4.6). The only SQL for users and the inbox."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.core.types import JsonValue
from app.domain.enums import Channel, MessageKind
from app.domain.models.base import UserHash
from app.domain.models.message import InboundMessage
from app.store.tables import inbox_messages, users


@dataclass(frozen=True, slots=True)
class InboundRecord:
    """One parsed message, ready to store, with its sender's encrypted address."""

    message: InboundMessage
    address_ciphertext: bytes | None
    raw_payload: dict[str, JsonValue] | None


@dataclass(frozen=True, slots=True)
class SaveResult:
    stored: int  # new messages; re-sent ones are skipped
    users_with_new_messages: frozenset[UserHash]  # whose turns should be woken


@dataclass(frozen=True, slots=True)
class LatestInbound:
    user_hash: UserHash
    kind: MessageKind


class InboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, records: Sequence[InboundRecord]) -> SaveResult:
        """Upsert each sender and insert each message, in one transaction.

        A message already stored (Meta re-sends webhooks) is skipped. If any were new, notifies
        `inbox_new`, delivered on commit.
        """
        if not records:
            return SaveResult(stored=0, users_with_new_messages=frozenset())
        stored = 0
        users: set[UserHash] = set()
        try:
            async with self._session_factory() as session, session.begin():
                for record in records:
                    await _upsert_sender(session, record)
                    if await _insert_message(session, record):
                        stored += 1
                        users.add(record.message.user_hash)
                if stored:
                    await session.execute(text("SELECT pg_notify('inbox_new', '')"))
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not store inbound messages: {type(exc).__name__}") from exc
        return SaveResult(stored=stored, users_with_new_messages=frozenset(users))

    async def latest_whatsapp_message(self) -> LatestInbound | None:
        """The newest stored WhatsApp message's sender and kind (ops CLI)."""
        query = (
            select(inbox_messages.c.user_hash, inbox_messages.c.kind)
            .where(inbox_messages.c.channel == Channel.WHATSAPP.value)
            .order_by(inbox_messages.c.received_at.desc(), inbox_messages.c.id.desc())
            .limit(1)
        )
        try:
            async with self._session_factory() as session:
                row = (await session.execute(query)).first()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read the inbox: {type(exc).__name__}") from exc
        if row is None:
            return None
        return LatestInbound(user_hash=UserHash(row.user_hash), kind=MessageKind(row.kind))

    async def load_address(self, user_hash: UserHash) -> bytes | None:
        """The sender's encrypted address, for decrypting just before a send."""
        query = select(users.c.address_ciphertext).where(users.c.user_hash == user_hash)
        try:
            async with self._session_factory() as session:
                ciphertext = (await session.execute(query)).scalar_one_or_none()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read the user: {type(exc).__name__}") from exc
        return bytes(ciphertext) if ciphertext is not None else None


async def _upsert_sender(session: AsyncSession, record: InboundRecord) -> None:
    message = record.message
    statement = insert(users).values(
        user_hash=message.user_hash,
        channel=message.channel.value,
        address_ciphertext=record.address_ciphertext,
        last_inbound_at=message.provider_sent_at,
    )
    # An existing ciphertext is never overwritten. GREATEST keeps last_inbound_at right when
    # Meta delivers an older retry after a newer message.
    statement = statement.on_conflict_do_update(
        index_elements=[users.c.user_hash],
        set_={
            "last_inbound_at": func.greatest(
                users.c.last_inbound_at, statement.excluded.last_inbound_at
            ),
            "updated_at": func.now(),
        },
    )
    await session.execute(statement)


async def _insert_message(session: AsyncSession, record: InboundRecord) -> bool:
    message = record.message
    statement = (
        insert(inbox_messages)
        .values(
            channel=message.channel.value,
            external_id=message.external_id,
            user_hash=message.user_hash,
            kind=message.kind.value,
            text=message.text,
            media_provider_id=message.media.provider_media_id if message.media else None,
            media_mime_type=message.media.mime_type if message.media else None,
            interactive_reply_id=message.interactive_reply_id,
            raw_payload=record.raw_payload,
            provider_sent_at=message.provider_sent_at,
            received_at=message.received_at,
        )
        .on_conflict_do_nothing(index_elements=["channel", "external_id"])
        .returning(inbox_messages.c.id)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None
