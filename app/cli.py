"""`marg` ops commands. Run as `.venv/bin/python -m app.cli <group> <command>`.

whatsapp reply-latest   send a text to the sender of the newest stored WhatsApp message
admin-link              print a 15-minute link to the admin dashboard (s13 §4.9)
ingest-corpus           validate, chunk, embed and store corpus/ (s11 §4.8)
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from app.core.clock import SystemClock
from app.core.config import load_settings
from app.core.errors import (
    CorpusValidationError,
    InvalidAddressCiphertext,
    ProviderError,
    StoreError,
)
from app.core.logging import configure_logging
from app.domain.enums import Channel, PartKind
from app.domain.models.reply import OutboundPart
from app.providers.ports import ChannelAddress
from app.rag.corpus_ingestor import CorpusIngestor
from app.rag.corpus_loader import CorpusLoader
from app.store.db import create_engine, create_session_factory
from app.telemetry.dashboard_link_codec import ADMIN
from app.wiring import build_container, build_rag, build_retry, close_container, dashboard_links

EXIT_OK = 0
EXIT_NOTHING_TO_DO = 1
EXIT_FAILED = 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marg", description="Marg.ai ops commands")
    groups = parser.add_subparsers(dest="group", required=True)
    whatsapp = groups.add_parser("whatsapp", help="WhatsApp channel tools")
    commands = whatsapp.add_subparsers(dest="command", required=True)
    reply = commands.add_parser(
        "reply-latest", help="reply to the sender of the newest stored WhatsApp message"
    )
    reply.add_argument("--text", default=None, help="message to send (default: an acknowledgement)")
    admin = groups.add_parser("admin-link", help="print a 15-minute admin dashboard link")
    admin.add_argument(
        "--base-url", default=None, help="the app's public address (default: PUBLIC_BASE_URL)"
    )
    ingest = groups.add_parser("ingest-corpus", help="validate, chunk, embed and store corpus/")
    ingest.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    ingest.add_argument("--yes", action="store_true", help="confirm ingesting into production")
    arguments = parser.parse_args(argv)
    if arguments.group == "ingest-corpus":
        dry_run: bool = arguments.dry_run
        confirmed: bool = arguments.yes
        return asyncio.run(ingest_corpus(dry_run=dry_run, confirmed=confirmed))
    if arguments.group == "admin-link":
        base_url: str | None = arguments.base_url
        return admin_link(base_url)
    text: str | None = arguments.text
    return asyncio.run(reply_latest(text))


async def ingest_corpus(*, dry_run: bool, confirmed: bool) -> int:
    """The corpus isn't user data, so ingesting into production is allowed, but only with
    --yes (s11 §4.8)."""
    settings = load_settings()
    configure_logging(settings.log_level, environment=settings.environment)
    if settings.environment == "prod" and not confirmed and not dry_run:
        _say("ENVIRONMENT is prod: run again with --yes to ingest into it.")
        return EXIT_NOTHING_TO_DO
    try:
        files = CorpusLoader.load(SystemClock().now().date())
    except CorpusValidationError as exc:
        _say(f"The corpus is invalid; nothing was written:\n{exc}")
        return EXIT_FAILED
    clock = SystemClock()
    engine = create_engine(settings)
    rag = build_rag(settings, create_session_factory(engine), build_retry(clock), clock)
    try:
        report = await CorpusIngestor(rag.embedder, rag.store).ingest(files, dry_run=dry_run)
    except (ProviderError, StoreError) as exc:
        _say(f"Failed: {type(exc).__name__}: {exc}")
        return EXIT_FAILED
    finally:
        await rag.embedder.aclose()
        await engine.dispose()
    verb = "Would write" if dry_run else "Wrote"
    _say(
        f"{verb}: {report.added} added, {report.updated} updated, {report.unchanged} unchanged, "
        f"{report.deleted} deleted, {report.chunks_written} chunks ({len(files)} files)."
    )
    return EXIT_OK


def admin_link(base_url: str | None) -> int:
    """The link is a bearer token for 15 minutes: it's printed to this terminal only."""
    settings = load_settings()
    links = dashboard_links(settings, SystemClock())
    base = (base_url or str(settings.public_base_url)).rstrip("/")
    _say(f"{base}/dashboard?t={links.link_token(ADMIN)}")
    minutes = settings.dashboard_link_ttl_s // 60
    _say(f"Valid for {minutes} minutes. Once opened, /status also shows the admin numbers.")
    return EXIT_OK


async def reply_latest(text: str | None) -> int:
    settings = load_settings()
    configure_logging(settings.log_level, environment=settings.environment)
    container = build_container(settings)
    try:
        latest = await container.inbox_repository.latest_whatsapp_message()
        if latest is None:
            _say("No WhatsApp message is stored yet.")
            return EXIT_NOTHING_TO_DO
        ciphertext = await container.inbox_repository.load_address(latest.user_hash)
        if ciphertext is None:
            _say("The newest message's sender has no stored address.")
            return EXIT_NOTHING_TO_DO
        address = container.identity.decrypt_address(latest.user_hash, ciphertext)
        part = OutboundPart(
            part_no=0,
            kind=PartKind.TEXT,
            text=text or f"Marg.ai received your {latest.kind.value} message.",
            audio_blob_id=None,
            image_blob_id=None,
            buttons=[],
            template=None,
        )
        receipt = await container.whatsapp_sender.send(
            part, ChannelAddress(channel=Channel.WHATSAPP, address=address)
        )
    except (StoreError, InvalidAddressCiphertext, ProviderError) as exc:
        _say(f"Failed: {type(exc).__name__}: {exc}")
        return EXIT_FAILED
    finally:
        await close_container(container)
    message_id = receipt.provider_message_id or "?"
    _say(f"Sent (message id {message_id[:14]}…) to user {latest.user_hash[:8]}…")
    return EXIT_OK


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
