"""EvalRepository: seeding a golden case's user and reading back what a turn did (s15 §4.2).

Used only by `marg eval`, inside its own disposable database. Seeding writes what onboarding
would have left behind (an ACTIVE profile with consent, the children, an activity already
offered), so a case starts exactly where it says. The reads give the eval what the database
holds about a turn: route, fixed reply, the reply text, every step with its cost and detail,
and the parts that went out.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import StoreError
from app.domain.enums import (
    ActivityStatus,
    Channel,
    ConsentEventKind,
    ConversationState,
    Language,
    LearnerRelation,
    Role,
    Route,
    TurnStatus,
)
from app.domain.models.base import TurnId, UserHash
from app.store.tables import (
    consent_events,
    corpus_chunks,
    corpus_documents,
    inbox_messages,
    learner_activities,
    learners,
    media_blobs,
    outbox_messages,
    turn_steps,
    turns,
    users,
)


@dataclass(frozen=True, slots=True)
class SeedLearner:
    relation: LearnerRelation
    nickname: str | None
    birth_year: int
    child_talk_consented: bool


@dataclass(frozen=True, slots=True)
class SeedActivity:
    activity_id: str
    activity_version: int


@dataclass(frozen=True, slots=True)
class EvalSeed:
    """A web user as onboarding would have left them. `role` None: a brand-new user (NEW)."""

    user_hash: UserHash
    role: Role | None
    grade: int | None
    subject: str | None
    district: str | None
    language: Language | None
    learners: Sequence[SeedLearner]
    open_activity: SeedActivity | None  # offered to the first learner
    consent_copy_version: str  # COPY_VERSION, as a real consent records it


@dataclass(frozen=True, slots=True)
class EvalStep:
    step: str
    outcome: str
    failure_kind: str | None
    duration_ms: int
    cost_usd: Decimal
    detail: str | None
    model: str | None
    started_at: datetime


@dataclass(frozen=True, slots=True)
class EvalPart:
    part_no: int
    kind: str
    text: str | None
    has_audio: bool
    has_image: bool
    status: str


@dataclass(frozen=True, slots=True)
class EvalTurnSnapshot:
    turn_id: TurnId
    status: str
    route: Route | None
    fixed_reply_kind: str | None
    reply_text: str | None
    reply_register: Language | None
    steps: list[EvalStep]
    parts: list[EvalPart]
    latency_ms: int  # from the first message arriving to the turn completing


@dataclass(frozen=True, slots=True)
class SourceText:
    chunk_id: UUID
    title: str
    source_url: str
    text: str


class EvalRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def seed(self, seed: EvalSeed) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                await _seed_user(session, seed)
                learner_ids = await _seed_learners(session, seed)
                if seed.open_activity is not None and learner_ids:
                    await _seed_offer(session, seed, learner_ids[0], seed.open_activity)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not seed an eval user: {type(exc).__name__}") from exc

    async def snapshot(self, turn_id: TurnId) -> EvalTurnSnapshot:
        """Raises StoreError when the turn doesn't exist."""
        try:
            async with self._session_factory() as session:
                return await _snapshot(session, turn_id)
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read an eval turn: {type(exc).__name__}") from exc

    async def turns_after(self, user_hash: UserHash, turn_id: TurnId) -> list[EvalTurnSnapshot]:
        """Turns the system started on its own after this one (a khoj card, a summary)."""
        try:
            async with self._session_factory() as session:
                after = select(turns.c.started_at).where(turns.c.id == turn_id).scalar_subquery()
                later = (
                    (
                        await session.execute(
                            select(turns.c.id)
                            .where(and_(turns.c.user_hash == user_hash, turns.c.started_at > after))
                            .order_by(turns.c.started_at)
                        )
                    )
                    .scalars()
                    .all()
                )
                return [await _snapshot(session, TurnId(later_id)) for later_id in later]
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read later eval turns: {type(exc).__name__}") from exc

    async def stored_media(self, user_hash: UserHash) -> int:
        """Media rows this user has now (the person check must leave none behind)."""
        try:
            async with self._session_factory() as session:
                count: int = (
                    await session.execute(
                        select(func.count())
                        .select_from(media_blobs)
                        .where(media_blobs.c.user_hash == user_hash)
                    )
                ).scalar_one()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not count eval media: {type(exc).__name__}") from exc
        return count

    async def sources(self, chunk_ids: Sequence[UUID]) -> list[SourceText]:
        """The cited chunks' full text, for the judge to check grounding against."""
        if not chunk_ids:
            return []
        query = (
            select(
                corpus_chunks.c.id,
                corpus_chunks.c.text,
                corpus_documents.c.title,
                corpus_documents.c.source_url,
            )
            .join(corpus_documents, corpus_documents.c.id == corpus_chunks.c.document_id)
            .where(corpus_chunks.c.id.in_(list(chunk_ids)))
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(query)).all()
        except (SQLAlchemyError, OSError) as exc:
            raise StoreError(f"could not read eval sources: {type(exc).__name__}") from exc
        by_id = {row.id: SourceText(row.id, row.title, row.source_url, row.text) for row in rows}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]


async def _seed_user(session: AsyncSession, seed: EvalSeed) -> None:
    onboarded = seed.role is not None
    await session.execute(
        users.insert().values(
            user_hash=seed.user_hash,
            channel=Channel.WEB.value,
            address_ciphertext=None,
            state=(ConversationState.ACTIVE if onboarded else ConversationState.NEW).value,
            role=seed.role.value if seed.role is not None else None,
            grade=seed.grade,
            subject=seed.subject,
            district=seed.district,
            language=seed.language.value if seed.language is not None else None,
            guardian_confirmed=seed.role is Role.STUDENT,
            consented_at=func.now() if onboarded else None,
            last_inbound_at=func.now(),
        )
    )
    if not onboarded:
        return
    kinds = [ConsentEventKind.GRANTED]
    if seed.role is Role.STUDENT:
        kinds.append(ConsentEventKind.GUARDIAN_CONFIRMED)
    for kind in kinds:
        await session.execute(
            consent_events.insert().values(
                user_hash=seed.user_hash,
                kind=kind.value,
                prompt_version=seed.consent_copy_version,
                recorded_at=func.now(),
            )
        )


async def _seed_learners(session: AsyncSession, seed: EvalSeed) -> list[UUID]:
    learner_ids: list[UUID] = []
    for learner in seed.learners:
        learner_id = uuid4()
        await session.execute(
            learners.insert().values(
                id=learner_id,
                owner_user_hash=seed.user_hash,
                relation=learner.relation.value,
                nickname=learner.nickname,
                birth_year=learner.birth_year,
                child_talk_consented_at=func.now() if learner.child_talk_consented else None,
            )
        )
        learner_ids.append(learner_id)
    return learner_ids


async def _seed_offer(
    session: AsyncSession, seed: EvalSeed, learner_id: UUID, activity: SeedActivity
) -> None:
    """The earlier turn that offered the activity, and the offer itself."""
    offer_turn = uuid4()
    await session.execute(
        turns.insert().values(
            id=offer_turn,
            user_hash=seed.user_hash,
            status=TurnStatus.COMPLETED.value,
            route=Route.JOURNEY.value,
            worker_id="eval-seed",
            started_at=func.now() - func.make_interval(0, 0, 0, 0, 1),
            completed_at=func.now() - func.make_interval(0, 0, 0, 0, 1),
        )
    )
    await session.execute(
        learner_activities.insert().values(
            id=uuid4(),
            learner_id=learner_id,
            activity_id=activity.activity_id,
            activity_version=activity.activity_version,
            offered_turn_id=offer_turn,
            status=ActivityStatus.OFFERED.value,
        )
    )


async def _snapshot(session: AsyncSession, turn_id: TurnId) -> EvalTurnSnapshot:
    turn = (await session.execute(select(turns).where(turns.c.id == turn_id))).one()
    first_received = (
        await session.execute(
            select(func.min(inbox_messages.c.received_at)).where(
                inbox_messages.c.turn_id == turn_id
            )
        )
    ).scalar_one_or_none()
    steps = (
        await session.execute(
            select(turn_steps).where(turn_steps.c.turn_id == turn_id).order_by(turn_steps.c.id)
        )
    ).all()
    parts = (
        await session.execute(
            select(outbox_messages)
            .where(outbox_messages.c.turn_id == turn_id)
            .order_by(outbox_messages.c.part_no)
        )
    ).all()
    began: datetime = first_received or turn.started_at
    ended: datetime = turn.completed_at or turn.started_at
    return EvalTurnSnapshot(
        turn_id=turn_id,
        status=turn.status,
        route=Route(turn.route) if turn.route else None,
        fixed_reply_kind=turn.fixed_reply_kind,
        reply_text=turn.reply_text,
        reply_register=Language(turn.reply_register) if turn.reply_register else None,
        steps=[
            EvalStep(
                step=row.step,
                outcome=row.outcome,
                failure_kind=row.failure_kind,
                duration_ms=row.duration_ms,
                cost_usd=row.cost_usd,
                detail=row.detail,
                model=row.model,
                started_at=row.started_at,
            )
            for row in steps
        ],
        parts=[
            EvalPart(
                part_no=row.part_no,
                kind=row.kind,
                text=row.text,
                has_audio=row.audio_blob_id is not None,
                has_image=row.image_blob_id is not None,
                status=row.status,
            )
            for row in parts
        ],
        latency_ms=max(int((ended - began).total_seconds() * 1000), 0),
    )
