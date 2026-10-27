"""WhatsAppWebhookIngestor: an authentic webhook body stored and applied (s03 §4.1, §4.8).

The router verifies the signature and parses the envelope; this stores the messages, applies
the delivery statuses and answers Meta. Nothing here logs message content or numbers.
"""

from dataclasses import dataclass
from typing import ClassVar

from fastapi import Response, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from app.api.turn_waker import TurnWaker
from app.channels.whatsapp.parsed_webhook import StatusUpdate
from app.channels.whatsapp.payloads import WebhookBody
from app.channels.whatsapp.webhook_parser import WhatsAppWebhookParser
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import StoreError
from app.core.logging import get_logger
from app.core.user_identity import UserIdentity
from app.store.repositories.inbox_repository import InboundRecord, InboxRepository, SaveResult
from app.store.repositories.outbox_repository import OutboxRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WhatsAppWebhookIngestor:
    identity: UserIdentity
    inbox: InboxRepository
    outbox: OutboxRepository
    clock: Clock
    waker: TurnWaker

    ACK: ClassVar[str] = "ok"

    @staticmethod
    def parse_body(raw_body: bytes) -> tuple[WebhookBody | None, str | None]:
        """The parsed envelope, or None and a description of where it broke (no values)."""
        try:
            return WebhookBody.model_validate_json(raw_body), None
        except ValidationError as exc:
            first = exc.errors(include_input=False, include_url=False)[0]
            location = ".".join(str(part) for part in first["loc"]) or "body"
            return None, f"{location}: {first['type']}"

    async def ingest(self, body: WebhookBody, settings: Settings) -> Response:
        """Store the authentic webhook's messages and apply its delivery statuses."""
        parsed = WhatsAppWebhookParser.parse(
            body, settings.whatsapp_phone_number_id, self.identity, self.clock.now()
        )
        records = [
            InboundRecord(
                message=item.inbound,
                address_ciphertext=self.identity.encrypt_address(
                    item.inbound.user_hash, item.wa_id.get_secret_value()
                ),
                raw_payload=item.raw_payload,
            )
            for item in parsed.messages
        ]
        saved, store_problem = await self._save(records)
        if store_problem is not None:
            # Unlike a parse failure, this one should be retried by Meta, so answer 503. The
            # driver's error isn't attached: it can quote the failing row (user content).
            logger.error("webhook_store_failed", problem=store_problem)
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        for user_hash in saved.users_with_new_messages:
            self.waker.wake(user_hash)
        unknown_statuses, status_problem = await self._apply_statuses(parsed.statuses)
        if status_problem is not None:
            # The messages are already stored; Meta's retry re-sends them, and they're skipped.
            logger.error("webhook_status_update_failed", problem=status_problem)
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

        for account_error in parsed.account_errors:
            logger.error(
                "whatsapp_account_error", code=account_error.code, title=account_error.title
            )
        if parsed.foreign_phone_number_id:
            logger.warning("webhook_for_other_number", changes=parsed.foreign_phone_number_id)
        logger.info(
            "webhook_received",
            messages=len(parsed.messages),
            stored=saved.stored,
            statuses=len(parsed.statuses),
            statuses_not_ours=unknown_statuses,
            ignored=parsed.ignored,
            malformed=parsed.malformed,
        )
        return PlainTextResponse(self.ACK)

    async def _save(self, records: list[InboundRecord]) -> tuple[SaveResult, str | None]:
        """What was stored, or a description of why storing failed."""
        try:
            return await self.inbox.save(records), None
        except StoreError as exc:
            return SaveResult(stored=0, users_with_new_messages=frozenset()), str(exc)

    async def _apply_statuses(self, statuses: list[StatusUpdate]) -> tuple[int, str | None]:
        """How many statuses matched no message of ours, or why applying them failed."""
        not_ours = 0
        try:
            for update in statuses:
                matched = await self.outbox.apply_status_update(
                    update.provider_message_id, update.status, update.at, update.error_code
                )
                if not matched:
                    not_ours += 1
        except StoreError as exc:
            return not_ours, str(exc)
        return not_ours, None
