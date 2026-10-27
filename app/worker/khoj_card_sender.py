"""KhojCardSender: after a good report, an illustrated card of the child's discovery
(s10b §4.13, C6). Runs after the reflection is delivered; nothing here can affect it.

Only for engagement of 2 or more (from the same turn's signals), at most one card per child per
India day. The caption and the image both pass safety before anything is stored; a card that
fails anywhere is simply not sent.
"""

from dataclasses import dataclass
from typing import ClassVar, Literal

from app.core.clock import Clock
from app.domain.models.curiosity import MakeKhojCard
from app.domain.models.usage import StepUsage
from app.domain.rules.nudge_schedule import NudgeSchedule
from app.layers.khoj_card_maker import CardRequest, KhojCardMaker
from app.pipeline.reply_parts_builder import ReplyPartsBuilder
from app.safety.safety_gate import SafetyGate
from app.store.repositories.curiosity_signal_repository import CuriositySignalRepository
from app.store.repositories.khoj_card_repository import KhojCardRepository, QueuedCard
from app.worker.reply_deliverer import ReplyDeliverer

type CardSkip = Literal["low_engagement", "card_today", "blocked", "user_gone"]


@dataclass(frozen=True, slots=True)
class CardOutcome:
    """What happened: sent, or why not. `usage` covers the calls that were made."""

    sent: bool
    skipped: CardSkip | None
    usage: StepUsage | None
    detail: str


@dataclass(frozen=True, slots=True)
class CardDeps:
    maker: KhojCardMaker
    gate: SafetyGate
    cards: KhojCardRepository
    signals: CuriositySignalRepository
    deliverer: ReplyDeliverer
    clock: Clock


class KhojCardSender:
    MIN_ENGAGEMENT: ClassVar[int] = 2  # s10b §4.13: cards stay special

    def __init__(self, deps: CardDeps, worker_id: str) -> None:
        self._maker = deps.maker
        self._gate = deps.gate
        self._cards = deps.cards
        self._signals = deps.signals
        self._deliverer = deps.deliverer
        self._clock = deps.clock
        self._worker_id = worker_id

    async def send(self, task: MakeKhojCard) -> CardOutcome:
        """Raises ProviderError, SafetyUnavailable or StoreError; the runner records it."""
        engagement = await self._signals.engagement_for(task.turn_id)
        if engagement is None or engagement < self.MIN_ENGAGEMENT:
            return CardOutcome(
                sent=False, skipped="low_engagement", usage=None, detail=f"engagement={engagement}"
            )
        today = NudgeSchedule.start_of_india_day(self._clock.now())
        if await self._cards.card_since(task.learner_id, today):
            return CardOutcome(
                sent=False, skipped="card_today", usage=None, detail="one card a day"
            )
        card = await self._maker.make(
            CardRequest(
                activity_id=task.activity_id,
                activity_title=task.activity_title,
                domains=task.domains,
                child_nickname=task.child_nickname,
                summary=task.summary,
                register=task.reply_register,
            )
        )
        usage = StepUsage.total(card.usages)
        check = await self._gate.check_card(card.caption, card.image)
        if check.safe_reply is None:
            flagged = ",".join(category.value for category in check.verdict.categories)
            return CardOutcome(
                sent=False, skipped="blocked", usage=usage, detail=f"categories={flagged}"
            )
        blob_id = KhojCardRepository.new_blob_id()
        turn_id = await self._cards.queue(
            QueuedCard(
                learner_activity_id=task.learner_activity_id,
                image_blob_id=blob_id,
                image=card.image,
                delivery=ReplyPartsBuilder.card(check.safe_reply, blob_id),
                caption=check.safe_reply.text,
                register=task.reply_register,
                worker_id=self._worker_id,
            )
        )
        if turn_id is None:
            return CardOutcome(sent=False, skipped="user_gone", usage=usage, detail="report gone")
        await self._deliverer.deliver_turn(turn_id)
        return CardOutcome(sent=True, skipped=None, usage=usage, detail="sent")
