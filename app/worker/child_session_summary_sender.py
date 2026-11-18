"""ChildSessionSummarySender: the parent's summary for a session the child left without a
goodbye (s10b §4.16, s04 §4.13), sent from the maintenance pass.

At a goodbye the summary goes out with the child's last reply. A session the child just walked
away from is closed as EXPIRED by maintenance instead, and this sends its summary: the same
reviewed wording and topic labels, never the child's words, and the child's time that day
against their daily limit (owner, 2026-11-13), as text only. It's sealed through
the safety gate's fixed path (no model wrote any of it) and queued in the parent's own channel,
once per session even with several workers, and only inside WhatsApp's 24-hour window.
"""

from dataclasses import dataclass
from typing import Final

from app.constants.fixed_replies import FALLBACK_LANGUAGE
from app.constants.whatsapp import CUSTOMER_SERVICE_WINDOW
from app.domain.enums import FixedReplyKind
from app.domain.models.child_session import DailyTalkTime
from app.domain.models.reply import LocalisedReply
from app.domain.rules.child_daily_limit_rules import ChildDailyLimitRules
from app.domain.rules.child_session_rules import ChildSessionLimits
from app.layers.child_talk_layer import ChildTalkLayer
from app.pipeline.reply_parts_builder import ReplyPartsBuilder
from app.safety.safety_gate import SafetyGate
from app.store.repositories.child_session_repository import (
    ChildSessionRepository,
    ExpiredSession,
    QueuedSummary,
)
from app.worker.reply_deliverer import ReplyDeliverer

BATCH_SIZE: Final = 50


@dataclass(frozen=True, slots=True)
class SummaryDeps:
    sessions: ChildSessionRepository
    gate: SafetyGate
    deliverer: ReplyDeliverer
    limits: ChildSessionLimits  # the session cap, for the day's time


class ChildSessionSummarySender:
    def __init__(self, deps: SummaryDeps, worker_id: str) -> None:
        self._sessions = deps.sessions
        self._gate = deps.gate
        self._deliverer = deps.deliverer
        self._limits = deps.limits
        self._worker_id = worker_id

    async def send_due(self) -> int:
        """Queue and send every due summary. Returns how many were queued."""
        queued = 0
        for expired in await self._sessions.due_summaries(BATCH_SIZE, CUSTOMER_SERVICE_WINDOW):
            summary = self._summary(expired, await self._talk_time(expired))
            turn_id = await self._sessions.queue_summary(summary)
            if turn_id is None:
                continue  # another worker sent it, or the parent was deleted
            await self._deliverer.deliver_turn(turn_id)
            queued += 1
        return queued

    async def _talk_time(self, expired: ExpiredSession) -> DailyTalkTime:
        """The child's time on the day the session started, up to its end."""
        day_started = ChildDailyLimitRules.day_started(expired.started_at)
        sessions = await self._sessions.learner_sessions_since(expired.learner_id, day_started)
        used = ChildDailyLimitRules.used_that_day(
            expired.learner_id, sessions, expired.started_at, expired.ended_at, self._limits
        )
        limit = ChildDailyLimitRules.picked_or_default(expired.daily_limit)
        return DailyTalkTime(used=used, limit=limit)

    def _summary(self, expired: ExpiredSession, talk_time: DailyTalkTime) -> QueuedSummary:
        register = expired.language or FALLBACK_LANGUAGE
        text = ChildTalkLayer.parent_summary(expired.nickname, expired.topics, register, talk_time)
        localised = LocalisedReply(
            text=text, spoken_text=text, reply_register=register, citations=[], buttons=[]
        )
        safe = self._gate.clear_fixed(localised, FixedReplyKind.CHILD_SESSION_END)
        return QueuedSummary(
            expired=expired,
            delivery=ReplyPartsBuilder.build(safe, audio_blob_id=None),
            reply_text=safe.text,
            register=register,
            worker_id=self._worker_id,
        )
