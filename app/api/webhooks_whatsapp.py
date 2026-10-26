"""The WhatsApp webhook (s03 §4.1). Thin: verify, parse, hand off to the store, answer fast.

No model calls and no outbound HTTP here; the reply is produced later by the worker.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from app.api.deps import get_clock, get_identity, get_inbound_store, get_settings
from app.channels.whatsapp.inbound import parse_webhook
from app.channels.whatsapp.payloads import WebhookBody
from app.channels.whatsapp.signature import verify_signature, verify_subscription
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import SignatureInvalid, StoreError
from app.core.identity import UserIdentity
from app.core.logging import get_logger
from app.store.repositories.inbound import InboundRecord, InboundStore

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
    if challenge is not None and verify_subscription(mode, token, settings.whatsapp_verify_token):
        return PlainTextResponse(challenge)
    logger.warning("webhook_verification_rejected", mode=mode, token_present=token is not None)
    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("")
async def receive(
    request: Request,
    settings: SettingsDep,
    identity: Annotated[UserIdentity, Depends(get_identity)],
    store: Annotated[InboundStore, Depends(get_inbound_store)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> Response:
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > settings.webhook_max_body_bytes:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    raw_body = await request.body()
    if len(raw_body) > settings.webhook_max_body_bytes:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    signature = request.headers.get("x-hub-signature-256")
    try:
        verify_signature(raw_body, signature, settings.whatsapp_app_secret)
    except SignatureInvalid as exc:
        logger.warning(
            "signature_invalid",
            reason=str(exc),
            header_present=signature is not None,
            header_length=len(signature or ""),
        )
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    body, parse_problem = _parse_body(raw_body)
    if body is None:
        # Authentic but unusable: answer 200, or Meta retries the same bytes for 7 days.
        # Only the location and type of the problem are logged: the payload is user content.
        logger.error("webhook_unparseable", size=len(raw_body), problem=parse_problem)
        return PlainTextResponse("ok")

    parsed = parse_webhook(body, settings.whatsapp_phone_number_id, identity, clock.now())
    records = [
        InboundRecord(
            message=item.inbound,
            address_ciphertext=identity.encrypt_address(
                item.inbound.user_hash, item.wa_id.get_secret_value()
            ),
            raw_payload=item.raw_payload,
        )
        for item in parsed.messages
    ]
    stored, store_problem = await _save(store, records)
    if store_problem is not None:
        # Unlike a parse failure, this one should be retried by Meta, so answer 503. The
        # driver's error isn't attached: it can quote the failing row, which holds user content.
        logger.error("webhook_store_failed", problem=store_problem)
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    for account_error in parsed.account_errors:
        logger.error("whatsapp_account_error", code=account_error.code, title=account_error.title)
    if parsed.foreign_phone_number_id:
        logger.warning("webhook_for_other_number", changes=parsed.foreign_phone_number_id)
    logger.info(
        "webhook_received",
        messages=len(parsed.messages),
        stored=stored,
        statuses=len(parsed.statuses),
        ignored=parsed.ignored,
        malformed=parsed.malformed,
    )
    return PlainTextResponse("ok")


def _parse_body(raw_body: bytes) -> tuple[WebhookBody | None, str | None]:
    """The parsed envelope, or None and a description of where it broke (no values)."""
    try:
        return WebhookBody.model_validate_json(raw_body), None
    except ValidationError as exc:
        first = exc.errors(include_input=False, include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"]) or "body"
        return None, f"{location}: {first['type']}"


async def _save(store: InboundStore, records: list[InboundRecord]) -> tuple[int, str | None]:
    """How many messages were stored, or a description of why storing failed."""
    try:
        return await store.save(records), None
    except StoreError as exc:
        return 0, str(exc)
