"""NudgeSender: the daily khoj message, sent from the maintenance pass (s10b §4.11).

Each due parent gets a NUDGE turn with one TEMPLATE part, built and sealed like any fixed reply
(FixedReplyService → SafetyGate.clear_fixed → ReplyPartsBuilder) and queued in the outbox by
NudgeRepository. A tap on the template's button ("jrn:today") opens the 24-hour window, and the
khoj itself is sent then, as a normal reply. Off while NUDGES_ENABLED is false.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.constants.journey_copy import KHOJ_TODAY
from app.core.clock import Clock
from app.domain.enums import FixedReplyKind, FixedReplyVariant, Language
from app.domain.models.reply import TemplateRef
from app.pipeline.fixed_reply_service import FixedReplyService
from app.pipeline.reply_parts_builder import ReplyDelivery, ReplyPartsBuilder
from app.safety.safety_gate import SafetyGate
from app.store.repositories.nudge_repository import NudgeBatch, NudgeRepository
from app.worker.reply_deliverer import ReplyDeliverer


@dataclass(frozen=True, slots=True)
class NudgeSettings:
    templates: Mapping[Language, TemplateRef]  # the approved template for each language
    daily_limit: int  # NUDGE_DAILY_LIMIT
    worker_id: str
    batch_size: int = 50


class NudgeSender:
    def __init__(
        self,
        repository: NudgeRepository,
        deliverer: ReplyDeliverer,
        gate: SafetyGate,
        clock: Clock,
        settings: NudgeSettings,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._deliverer = deliverer
        self._settings = settings
        self._batch = NudgeBatch(
            deliveries=self._deliveries(gate, settings.templates),
            reply_texts={
                language: FixedReplyService.localise(
                    FixedReplyKind.NUDGE, FixedReplyVariant.DEFAULT, language
                ).text
                for language in Language
            },
            worker_id=settings.worker_id,
            batch_size=settings.batch_size,
            daily_limit=settings.daily_limit,
        )

    async def send_due(self) -> int:
        """Queue and send every due nudge. Returns how many were queued."""
        result = await self._repository.send_due(self._batch, self._clock.now())
        for turn_id in result.sent:
            await self._deliverer.deliver_turn(turn_id)
        return len(result.sent)

    @staticmethod
    def _deliveries(
        gate: SafetyGate, templates: Mapping[Language, TemplateRef]
    ) -> dict[Language, ReplyDelivery]:
        deliveries: dict[Language, ReplyDelivery] = {}
        for language in Language:
            localised = FixedReplyService.localise(
                FixedReplyKind.NUDGE, FixedReplyVariant.DEFAULT, language
            )
            safe = gate.clear_fixed(localised, FixedReplyKind.NUDGE)
            deliveries[language] = ReplyPartsBuilder.build(
                safe, audio_blob_id=None, template=templates[language]
            )
        return deliveries


def nudge_templates(name: str, hinglish_name: str) -> dict[Language, TemplateRef]:
    """Hindi and English share one template name in two languages; Hinglish has its own
    (Meta has no Hinglish language code, so it's submitted as English)."""
    return {
        Language.HINDI: TemplateRef(name=name, language_code="hi", button_payloads=[KHOJ_TODAY]),
        Language.ENGLISH: TemplateRef(name=name, language_code="en", button_payloads=[KHOJ_TODAY]),
        Language.HINGLISH: TemplateRef(
            name=hinglish_name, language_code="en", button_payloads=[KHOJ_TODAY]
        ),
    }
