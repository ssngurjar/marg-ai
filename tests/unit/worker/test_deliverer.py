"""ReplyDeliverer (s04 §4.10): order, the 24-hour window, retries and permanent failures."""

import dataclasses
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.errors import ProviderError, ProviderRejected, ProviderUnavailable
from app.domain.enums import Channel, PartKind
from app.domain.models.base import TurnId, UserHash
from app.domain.models.message import ImageClip
from app.domain.models.reply import OutboundPart, TemplateRef
from app.providers.http import RetryPolicy, RetryTiming
from app.providers.ports import ChannelSender
from app.store.repositories.outbox_repository import OutboxRepository, OutboxRow
from app.worker.reply_deliverer import DeliveryDeps, DeliverySettings, ReplyDeliverer
from tests.fakes.clock import FixedClock
from tests.fakes.image import TINY_PNG
from tests.fakes.sender import FakeSender
from tests.fakes.sleeper import FakeSleeper
from tests.fakes.user_repository import MemoryUserRepository
from tests.fakes.voice import VOICE_NOTE, MemoryReplyAudioStore
from tests.support.app_factory import make_identity

pytestmark = pytest.mark.unit

CARD = ImageClip(data=TINY_PNG, mime_type="image/png")

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
USER = UserHash("c" * 64)
WA_ID = "919000000001"
TURN = TurnId(uuid4())


@dataclass(frozen=True, slots=True)
class Mark:
    outbox_id: int
    result: str  # "sent", "retry", "failed"
    detail: str | None


class MemoryOutbox(OutboxRepository):
    """Hands out scripted rows in order and records how each ended."""

    def __init__(self, rows: list[OutboxRow]) -> None:
        self.rows = rows
        self.marks: list[Mark] = []

    async def claim_next_part(self, turn_id: TurnId) -> OutboxRow | None:
        return self.rows.pop(0) if self.rows else None

    async def mark_sent(
        self, outbox_id: int, provider_message_id: str | None, sent_at: datetime
    ) -> None:
        self.marks.append(Mark(outbox_id, "sent", provider_message_id))

    async def mark_retry(self, outbox_id: int, error_code: str, delay: timedelta) -> None:
        self.marks.append(Mark(outbox_id, "retry", error_code))

    async def mark_failed(self, outbox_id: int, error_code: str) -> None:
        self.marks.append(Mark(outbox_id, "failed", error_code))


def part(number: int, kind: PartKind = PartKind.TEXT) -> OutboundPart:
    template = (
        TemplateRef(name="aaj_ki_khoj", language_code="hi", button_payloads=["jrn:today"])
        if kind is PartKind.TEMPLATE
        else None
    )
    return OutboundPart(
        part_no=number,
        kind=kind,
        text=None if kind is PartKind.TEMPLATE else f"part {number}",
        audio_blob_id=uuid4() if kind is PartKind.AUDIO else None,
        image_blob_id=None,
        buttons=[],
        template=template,
    )


def row(
    number: int,
    *,
    kind: PartKind = PartKind.TEXT,
    attempts: int = 1,
    last_inbound_at: datetime | None = NOW,
    ciphertext: bytes | None = None,
) -> OutboxRow:
    return OutboxRow(
        outbox_id=100 + number,
        turn_id=TURN,
        user_hash=USER,
        channel=Channel.WHATSAPP,
        part=part(number, kind),
        attempts=attempts,
        address_ciphertext=ciphertext
        if ciphertext is not None
        else make_identity().encrypt_address(USER, WA_ID),
        last_inbound_at=last_inbound_at,
    )


def deliverer(
    outbox: MemoryOutbox,
    sender: FakeSender,
    clock: FixedClock,
    audio: MemoryReplyAudioStore | None = None,
) -> ReplyDeliverer:
    senders: dict[Channel, ChannelSender] = {Channel.WHATSAPP: sender}
    retry = RetryPolicy(
        timing=RetryTiming(attempts=1),  # the outbox's own retries are what's under test
        clock=clock,
        sleeper=FakeSleeper(clock),
        rng=random.Random(3),  # noqa: S311  # deterministic jitter for tests, not cryptography
    )
    return ReplyDeliverer(
        DeliveryDeps(
            outbox=outbox,
            users=MemoryUserRepository(),
            senders=senders,
            identity=make_identity(),
            retry=retry,
            clock=clock,
            audio=audio or MemoryReplyAudioStore(),
            images=audio or MemoryReplyAudioStore(),
        ),
        DeliverySettings(max_attempts=5, part_budget=timedelta(seconds=25)),
    )


def failing(error: ProviderError) -> FakeSender:
    clock = FixedClock(NOW)
    return FakeSender(clock, fail_with=lambda _part, _call: error)


async def test_parts_are_sent_in_order_to_the_decrypted_number() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    outbox = MemoryOutbox([row(0), row(1)])
    assert await deliverer(outbox, sender, clock).deliver_turn(TURN) == 2
    assert [(sent.part.part_no, sent.address) for sent in sender.sent] == [(0, WA_ID), (1, WA_ID)]
    assert [mark.result for mark in outbox.marks] == ["sent", "sent"]


async def test_a_closed_window_fails_the_part_without_calling_meta() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    outbox = MemoryOutbox([row(0, last_inbound_at=NOW - timedelta(hours=25))])
    await deliverer(outbox, sender, clock).deliver_turn(TURN)
    assert sender.calls == 0
    assert outbox.marks == [Mark(100, "failed", "window_closed")]


async def test_the_window_is_open_at_exactly_24_hours() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    outbox = MemoryOutbox([row(0, last_inbound_at=NOW - timedelta(hours=24))])
    await deliverer(outbox, sender, clock).deliver_turn(TURN)
    assert sender.calls == 1


async def test_a_template_is_sent_outside_the_window() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    outbox = MemoryOutbox([row(0, kind=PartKind.TEMPLATE, last_inbound_at=NOW - timedelta(days=3))])
    await deliverer(outbox, sender, clock).deliver_turn(TURN)
    assert sender.calls == 1
    assert outbox.marks[0].result == "sent"


async def test_a_retryable_failure_is_scheduled_again() -> None:
    clock = FixedClock(NOW)
    outbox = MemoryOutbox([row(0, attempts=1)])
    error = ProviderUnavailable("graph api http 503", provider="whatsapp")
    await deliverer(outbox, failing(error), clock).deliver_turn(TURN)
    assert outbox.marks == [Mark(100, "retry", "ProviderUnavailable: graph api http 503")]


async def test_a_retryable_failure_at_the_attempt_limit_fails_for_good() -> None:
    clock = FixedClock(NOW)
    outbox = MemoryOutbox([row(0, attempts=5)])
    error = ProviderUnavailable("graph api http 503", provider="whatsapp")
    await deliverer(outbox, failing(error), clock).deliver_turn(TURN)
    assert outbox.marks == [Mark(100, "failed", "ProviderUnavailable: graph api http 503")]


async def test_a_rejected_send_fails_at_once() -> None:
    clock = FixedClock(NOW)
    outbox = MemoryOutbox([row(0, attempts=1)])
    error = ProviderRejected("graph api error 131026", provider="whatsapp")
    await deliverer(outbox, failing(error), clock).deliver_turn(TURN)
    assert outbox.marks == [Mark(100, "failed", "ProviderRejected: graph api error 131026")]


async def test_an_address_that_will_not_decrypt_fails_the_part() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    outbox = MemoryOutbox([row(0, ciphertext=b"\x00" * 40)])
    await deliverer(outbox, sender, clock).deliver_turn(TURN)
    assert sender.calls == 0
    assert outbox.marks == [Mark(100, "failed", "InvalidAddressCiphertext")]


async def test_a_khoj_card_is_sent_with_its_stored_image() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    store = MemoryReplyAudioStore()
    card_row = row(0, kind=PartKind.IMAGE)
    card_row = dataclasses.replace(
        card_row, part=card_row.part.model_copy(update={"image_blob_id": uuid4()})
    )
    assert card_row.part.image_blob_id is not None
    store.images[card_row.part.image_blob_id] = CARD
    assert await deliverer(MemoryOutbox([card_row]), sender, clock, store).deliver_turn(TURN) == 1
    assert sender.sent[0].image == CARD


async def test_an_expired_card_is_failed_not_sent() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    outbox = MemoryOutbox([row(0, kind=PartKind.IMAGE)])
    await deliverer(outbox, sender, clock).deliver_turn(TURN)
    assert sender.calls == 0
    assert outbox.marks == [Mark(100, "failed", "media_expired")]


async def test_a_voice_reply_is_sent_with_its_stored_clip() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    store = MemoryReplyAudioStore()
    audio_row = row(0, kind=PartKind.AUDIO)
    assert audio_row.part.audio_blob_id is not None
    store.saved[audio_row.part.audio_blob_id] = VOICE_NOTE
    outbox = MemoryOutbox([audio_row, row(1)])
    assert await deliverer(outbox, sender, clock, store).deliver_turn(TURN) == 2
    assert [sent.audio for sent in sender.sent] == [VOICE_NOTE, None]


async def test_an_expired_voice_reply_is_failed_and_the_text_after_it_still_goes() -> None:
    clock = FixedClock(NOW)
    sender = FakeSender(clock)
    deleted = row(0, kind=PartKind.AUDIO)
    unlinked = row(1, kind=PartKind.AUDIO)
    unlinked = dataclasses.replace(
        unlinked, part=unlinked.part.model_copy(update={"audio_blob_id": None})
    )  # the blob was deleted and the foreign key set it NULL
    outbox = MemoryOutbox([deleted, unlinked, row(2)])
    assert await deliverer(outbox, sender, clock).deliver_turn(TURN) == 1
    assert outbox.marks[:2] == [
        Mark(100, "failed", "media_expired"),
        Mark(101, "failed", "media_expired"),
    ]
    assert [sent.part.part_no for sent in sender.sent] == [2]


async def test_logs_never_contain_the_number(capsys: pytest.CaptureFixture[str]) -> None:
    clock = FixedClock(NOW)
    outbox = MemoryOutbox([row(0, last_inbound_at=NOW - timedelta(hours=30))])
    await deliverer(outbox, FakeSender(clock), clock).deliver_turn(TURN)
    assert WA_ID not in capsys.readouterr().out
