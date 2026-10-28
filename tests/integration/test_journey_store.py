"""The journey against Postgres: offers and reports commit with the reply, only for the user's
own children; the context finds the active child and their open activity (s10b §5, §9)."""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import SystemClock
from app.core.errors import StoreError
from app.domain.enums import ActivityStatus, Channel, InboxStatus, MessageKind
from app.domain.models.base import TurnId, UserHash
from app.domain.models.learner import LearnerId
from app.domain.models.message import InboundMessage
from app.domain.models.photo import ObjectCount
from app.domain.models.turn import QueuedMessage
from app.domain.models.writes import ActivityOffered, ActivityReported
from app.store.db import create_engine, create_session_factory
from app.store.repositories.turn_repository import FinishedTurn, StartedTurn, TurnRepository
from tests.support.app_factory import make_settings

pytestmark = pytest.mark.integration

PARENT = UserHash("a" * 64)
OTHER = UserHash("b" * 64)
MUNNI = LearnerId(UUID(int=1))
GOLU = LearnerId(UUID(int=2))
STRANGER_CHILD = LearnerId(UUID(int=3))
FINISHED = FinishedTurn(
    route=None, fixed_reply_kind=None, user_text=None, reply_text=None, reply_register=None,
    prompt_versions={}, failure_step=None, failure_kind=None, inbox_status=InboxStatus.DONE,
)  # fmt: skip


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL must point at the docker-compose.test.yml database")
    engine = create_engine(make_settings(database_url=url))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, inbox_messages RESTART IDENTITY CASCADE"))
        for user in (PARENT, OTHER):
            await connection.execute(
                text(
                    "INSERT INTO users (user_hash, channel, state, role, consented_at) "
                    "VALUES (:h, 'whatsapp', 'active', 'parent', now())"
                ),
                {"h": user},
            )
        for learner, owner, nickname in (
            (MUNNI, PARENT, "Munni"),
            (GOLU, PARENT, "Golu"),
            (STRANGER_CHILD, OTHER, None),
        ):
            await connection.execute(
                text(
                    "INSERT INTO learners (id, owner_user_hash, relation, nickname, birth_year) "
                    "VALUES (:id, :owner, 'parent', :nickname, 2021)"
                ),
                {"id": learner, "owner": owner, "nickname": nickname},
            )
    yield engine
    await engine.dispose()


@pytest.fixture
def turns(engine: AsyncEngine) -> TurnRepository:
    return TurnRepository(create_session_factory(engine))


def message(text_body: str | None, *, button: str | None = None) -> InboundMessage:
    now = SystemClock().now()  # the database's now(): offers are stamped by Postgres
    return InboundMessage(
        channel=Channel.WHATSAPP,
        external_id=f"wamid.{uuid4().hex}",
        user_hash=PARENT,
        kind=MessageKind.INTERACTIVE if button else MessageKind.TEXT,
        text=text_body,
        media=None,
        interactive_reply_id=button,
        provider_sent_at=now,
        received_at=now,
    )


LEASE_FOR_TEST = text(
    "UPDATE users SET lease_owner = :w, lease_expires_at = now() + interval '1 minute' "
    "WHERE user_hash = :h"
)
"""What the turn loop's claim does: finalize commits only while the turn's worker holds it."""


async def started(engine: AsyncEngine, *messages: InboundMessage) -> StartedTurn:
    turn_id = TurnId(uuid4())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO turns (id, user_hash, status, worker_id) "
                "VALUES (:id, :h, 'processing', 't')"
            ),
            {"id": turn_id, "h": PARENT},
        )
        await connection.execute(LEASE_FOR_TEST, {"h": PARENT, "w": "t"})
    queued = [
        QueuedMessage(number, item, 0) for number, item in enumerate(messages or (message("hi"),))
    ]
    return StartedTurn(
        turn_id=turn_id, user_hash=PARENT, channel=Channel.WHATSAPP, queued=queued, worker_id="t"
    )


def offered(learner: LearnerId = MUNNI, activity: str = "shadow-time") -> ActivityOffered:
    return ActivityOffered(
        learner_activity_id=uuid4(), learner_id=learner, activity_id=activity, activity_version=1
    )


async def scalar(engine: AsyncEngine, sql: str, **params: object) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(sql), params)).scalar_one()


async def test_an_offer_commits_with_the_turn_and_a_report_closes_it(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    offer = offered()
    await turns.finalize(await started(engine), FINISHED, None, [offer])
    assert await scalar(engine, "SELECT status FROM learner_activities") == "offered"
    report = ActivityReported(
        learner_activity_id=offer.learner_activity_id,
        status=ActivityStatus.DONE,
        summary="Munni noticed the shadow move.",
    )
    await turns.finalize(await started(engine), FINISHED, None, [report])
    assert await scalar(engine, "SELECT status FROM learner_activities") == "done"
    assert await scalar(engine, "SELECT reported_at IS NOT NULL FROM learner_activities") is True


async def test_a_reports_photo_counts_are_stored_and_never_the_photo(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    offer = offered()
    await turns.finalize(await started(engine), FINISHED, None, [offer])
    report = ActivityReported(
        learner_activity_id=offer.learner_activity_id,
        status=ActivityStatus.DONE,
        summary="Munni built a tower of stones.",
        photo_counts=[ObjectCount(phrase="stone", count=5)],
    )
    await turns.finalize(await started(engine), FINISHED, None, [report])
    stored = await scalar(engine, "SELECT photo_findings FROM learner_activities")
    assert stored == [{"phrase": "stone", "count": 5}]


async def test_a_report_without_a_photo_stores_no_findings(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    offer = offered()
    await turns.finalize(await started(engine), FINISHED, None, [offer])
    report = ActivityReported(
        learner_activity_id=offer.learner_activity_id, status=ActivityStatus.DONE, summary=None
    )
    await turns.finalize(await started(engine), FINISHED, None, [report])
    assert await scalar(engine, "SELECT photo_findings FROM learner_activities") is None


async def test_an_offer_for_someone_elses_child_is_refused_and_nothing_commits(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    turn = await started(engine)
    with pytest.raises(StoreError, match="user's own learner"):
        await turns.finalize(turn, FINISHED, None, [offered(STRANGER_CHILD)])
    assert await scalar(engine, "SELECT count(*) FROM learner_activities") == 0
    assert (
        await scalar(engine, "SELECT status FROM turns WHERE id = :id", id=turn.turn_id)
        == "processing"
    )


async def test_a_report_on_someone_elses_activity_changes_nothing(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    stranger_offer = offered()
    await turns.finalize(await started(engine), FINISHED, None, [stranger_offer])
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE learner_activities SET learner_id = :other"), {"other": STRANGER_CHILD}
        )
    report = ActivityReported(
        learner_activity_id=stranger_offer.learner_activity_id,
        status=ActivityStatus.DONE,
        summary="x",
    )
    await turns.finalize(await started(engine), FINISHED, None, [report])
    assert await scalar(engine, "SELECT status FROM learner_activities") == "offered"


async def test_the_context_knows_the_child_from_the_latest_offer_and_its_open_activity(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    await turns.finalize(await started(engine), FINISHED, None, [offered(GOLU, "leaf-families")])
    ctx = await turns.load_context(await started(engine, message("ho gaya")), recent_exchanges=0)
    assert ctx.active_learner is not None
    assert ctx.active_learner.id == GOLU
    assert ctx.open_activity is not None
    assert ctx.open_activity.activity_id == "leaf-families"
    assert [record.activity_id for record in ctx.activity_history] == ["leaf-families"]


async def test_a_nickname_in_the_message_picks_that_child(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    await turns.finalize(await started(engine), FINISHED, None, [offered(GOLU)])
    ctx = await turns.load_context(
        await started(engine, message("Munni ne kaha…")), recent_exchanges=0
    )
    assert ctx.active_learner is not None
    assert ctx.active_learner.id == MUNNI
    assert ctx.open_activity is None


async def test_an_offer_older_than_48_hours_is_not_open(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    await turns.finalize(await started(engine), FINISHED, None, [offered(MUNNI)])
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE learner_activities SET offered_at = now() - interval '49 hours'")
        )
    ctx = await turns.load_context(
        await started(engine, message("Munni ne kaha")), recent_exchanges=0
    )
    assert ctx.open_activity is None
    assert len(ctx.activity_history) == 1


async def test_a_child_button_picks_that_child(engine: AsyncEngine, turns: TurnRepository) -> None:
    ctx = await turns.load_context(
        await started(engine, message("Golu", button=f"jrn:today:{GOLU}")), recent_exchanges=0
    )
    assert ctx.active_learner is not None
    assert ctx.active_learner.id == GOLU


async def test_retention_clears_old_report_summaries(
    engine: AsyncEngine, turns: TurnRepository
) -> None:
    offer = offered()
    await turns.finalize(await started(engine), FINISHED, None, [offer])
    report = ActivityReported(
        learner_activity_id=offer.learner_activity_id,
        status=ActivityStatus.DONE,
        summary="Munni counted 7 leaves.",
    )
    await turns.finalize(await started(engine), FINISHED, None, [report])
    future = SystemClock().now() + timedelta(days=1)
    await turns.clear_expired_text(turn_text_before=future, raw_payload_before=future)
    assert await scalar(engine, "SELECT child_response_summary FROM learner_activities") is None
