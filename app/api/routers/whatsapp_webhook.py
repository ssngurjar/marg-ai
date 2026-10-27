"""The WhatsApp webhook routes (s03 §4.1). Thin: verify, then hand off to the ingestor.

No model calls and no outbound HTTP here; the reply is produced later by the worker.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.api.deps import (
    get_clock,
    get_identity,
    get_inbox_repository,
    get_outbox_repository,
    get_settings,
)
from app.api.whatsapp_webhook_ingestor import WhatsAppWebhookIngestor
from app.channels.whatsapp.webhook_signature import WebhookSignatureVerifier
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import SignatureInvalid
from app.core.logging import get_logger
from app.core.user_identity import UserIdentity
from app.store.repositories.inbox_repository import InboxRepository
from app.store.repositories.outbox_repository import OutboxRepository

router = APIRouter(prefix="/webhooks/whatsapp")
logger = get_logger(__name__)

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("")
async def verify(
    settings: SettingsDep,
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    """Meta's one-time subscription handshake: echo the challenge if the token matches."""
    if challenge is not None and WebhookSignatureVerifier.verify_subscription(
        mode, token, settings.whatsapp_verify_token
    ):
        return PlainTextResponse(challenge)
    logger.warning("webhook_verification_rejected", mode=mode, token_present=token is not None)
    return Response(status_code=status.HTTP_403_FORBIDDEN)


def get_ingestor(
    identity: Annotated[UserIdentity, Depends(get_identity)],
    inbox: Annotated[InboxRepository, Depends(get_inbox_repository)],
    outbox: Annotated[OutboxRepository, Depends(get_outbox_repository)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> WhatsAppWebhookIngestor:
    return WhatsAppWebhookIngestor(identity=identity, inbox=inbox, outbox=outbox, clock=clock)


@router.post("")
async def receive(
    request: Request,
    settings: SettingsDep,
    ingestor: Annotated[WhatsAppWebhookIngestor, Depends(get_ingestor)],
) -> Response:
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > settings.webhook_max_body_bytes:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    raw_body = await request.body()
    if len(raw_body) > settings.webhook_max_body_bytes:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    signature = request.headers.get("x-hub-signature-256")
    try:
        WebhookSignatureVerifier.verify(raw_body, signature, settings.whatsapp_app_secret)
    except SignatureInvalid as exc:
        logger.warning(
            "signature_invalid",
            reason=str(exc),
            header_present=signature is not None,
            header_length=len(signature or ""),
        )
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    body, parse_problem = WhatsAppWebhookIngestor.parse_body(raw_body)
    if body is None:
        # Authentic but unusable: answer 200, or Meta retries the same bytes for 7 days.
        # Only the location and type of the problem are logged: the payload is user content.
        logger.error("webhook_unparseable", size=len(raw_body), problem=parse_problem)
        return PlainTextResponse(WhatsAppWebhookIngestor.ACK)
    return await ingestor.ingest(body, settings)
