"""`marg` ops commands. Run as `.venv/bin/python -m app.cli <group> <command>`.

whatsapp reply-latest   send a text to the sender of the newest stored WhatsApp message
admin-link              print a 15-minute link to the admin dashboard (s13 §4.9)
ingest-corpus           validate, chunk and store corpus/ (s11 §4.8)
eval                    play the golden cases through the real pipeline and score them (s15)
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.core.clock import SystemClock
from app.core.config import load_settings
from app.core.errors import (
    ConfigError,
    CorpusValidationError,
    GoldenCaseInvalid,
    InvalidAddressCiphertext,
    ProviderError,
    StoreError,
)
from app.core.logging import configure_logging
from app.domain.enums import Channel, PartKind
from app.domain.models.reply import OutboundPart
from app.evals.eval_harness import HarnessOptions
from app.evals.eval_runner import CaseFilter, EvalRunConfig, EvalRunner, RunIdentity
from app.providers.ports import ChannelAddress
from app.rag.corpus_ingestor import CorpusIngestor
from app.rag.corpus_loader import CorpusLoader
from app.store.db import create_engine, create_session_factory
from app.telemetry.dashboard_link_codec import ADMIN
from app.wiring import build_container, build_rag, close_container, dashboard_links

EXIT_OK = 0
EXIT_NOTHING_TO_DO = 1
EXIT_FAILED = 2
EXIT_EVAL_HARNESS = 3  # s15 §4.7: the eval couldn't run
EVAL_COST_PER_TURN = Decimal("0.045")  # pipeline + judge, s15 §4.9: about $4 for 90 turns
EVAL_CONFIRM_ABOVE = Decimal(2)
GIT_TIMEOUT_S = 10


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
    ingest = groups.add_parser("ingest-corpus", help="validate, chunk and store corpus/")
    ingest.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    ingest.add_argument("--yes", action="store_true", help="confirm ingesting into production")
    _add_eval_arguments(groups)
    arguments = parser.parse_args(argv)
    if arguments.group == "eval":
        return asyncio.run(run_eval(_eval_request(arguments)))
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
    engine = create_engine(settings)
    rag = build_rag(settings, create_session_factory(engine))
    try:
        report = await CorpusIngestor(rag.store).ingest(files, dry_run=dry_run)
    except StoreError as exc:
        _say(f"Failed: {type(exc).__name__}: {exc}")
        return EXIT_FAILED
    finally:
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


@dataclass(frozen=True, slots=True)
class EvalRequest:
    case_filter: CaseFilter
    repeat: int
    options: HarnessOptions
    baseline: Path | None
    fail_on_regression: bool
    write: bool
    confirmed: bool


def _add_eval_arguments(groups: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    evaluate = groups.add_parser("eval", help="score the golden cases on the real pipeline")
    evaluate.add_argument("--file", action="append", default=[], help="e.g. crisis.yaml")
    evaluate.add_argument("--case", action="append", default=[], help="e.g. crisis-001")
    evaluate.add_argument("--tag", action="append", default=[], help="cases with this tag")
    evaluate.add_argument("--repeat", type=int, default=1, help="judge each turn N times")
    evaluate.add_argument("--with-tts", action="store_true", help="real text-to-speech")
    evaluate.add_argument("--live-images", action="store_true", help="real khoj-card pictures")
    evaluate.add_argument("--baseline", type=Path, default=None, help="compare with this run")
    evaluate.add_argument("--fail-on-regression", action="store_true", help="exit 2 if worse")
    evaluate.add_argument("--keep-db", action="store_true", help="keep the eval database")
    evaluate.add_argument("--no-write", action="store_true", help="don't write a scorecard")
    evaluate.add_argument("--yes", action="store_true", help="skip the cost confirmation")


def _eval_request(arguments: argparse.Namespace) -> EvalRequest:
    files: list[str] = arguments.file
    cases: list[str] = arguments.case
    tags: list[str] = arguments.tag
    repeat: int = arguments.repeat
    baseline: Path | None = arguments.baseline
    return EvalRequest(
        case_filter=CaseFilter(
            files=frozenset(files), case_ids=frozenset(cases), tags=frozenset(tags)
        ),
        repeat=max(repeat, 1),
        options=HarnessOptions(
            with_tts=bool(arguments.with_tts),
            live_images=bool(arguments.live_images),
            keep_db=bool(arguments.keep_db),
        ),
        baseline=baseline,
        fail_on_regression=bool(arguments.fail_on_regression),
        write=not arguments.no_write,
        confirmed=bool(arguments.yes),
    )


async def run_eval(request: EvalRequest) -> int:
    """s15 §4.8. Exit 0 fine, 1 a hard gate failed, 2 a regression (with --fail-on-regression),
    3 the harness couldn't run (nothing half-written)."""
    try:
        settings = load_settings()
        selected = EvalRunner.select(request.case_filter)
    except (ConfigError, GoldenCaseInvalid, CorpusValidationError) as exc:
        _say(f"Not run: {exc}")
        return EXIT_EVAL_HARNESS
    if not selected:
        _say("No case matches the filter.")
        return EXIT_EVAL_HARNESS
    estimate = (
        EVAL_COST_PER_TURN * sum(len(loaded.case.turns) for loaded in selected) * request.repeat
    )
    _say(f"{len(selected)} cases; estimated cost about ${estimate:.2f}.")
    if estimate > EVAL_CONFIRM_ABOVE and not request.confirmed:
        _say("Above $2: run again with --yes to go ahead.")
        return EXIT_NOTHING_TO_DO
    config = EvalRunConfig(
        case_filter=request.case_filter,
        repeat=request.repeat,
        options=request.options,
        baseline=request.baseline,
        fail_on_regression=request.fail_on_regression,
        write=request.write,
    )
    try:
        identity = await _run_identity()
        outcome = await EvalRunner(settings, config, SystemClock()).run(selected, identity)
    except (ConfigError, StoreError, ProviderError) as exc:
        _say(f"The eval harness failed; no scorecard was written: {type(exc).__name__}: {exc}")
        return EXIT_EVAL_HARNESS
    card = outcome.scorecard
    gates = ", ".join(f"{file} {'pass' if ok else 'FAIL'}" for file, ok in card.hard_gates.items())
    _say(
        f"Pass rate {card.pass_rate:.0%}; hard gates: {gates or 'none selected'}; cost "
        f"${card.cost_usd + card.judge_cost_usd:.2f}."
    )
    if outcome.regression is not None and outcome.regression.newly_failing:
        _say(f"Newly failing: {', '.join(outcome.regression.newly_failing)}")
    for path in outcome.written:
        _say(f"Wrote {path}")
    return outcome.exit_code


async def _run_identity() -> RunIdentity:
    """The commit the run measured, and whether there were uncommitted changes."""
    sha = (await _git("rev-parse", "--short", "HEAD")).strip() or "unknown"
    dirty = bool((await _git("status", "--porcelain")).strip())
    return RunIdentity(git_sha=sha, dirty=dirty)


async def _git(*arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "git", *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        async with asyncio.timeout(GIT_TIMEOUT_S):
            output, _ = await process.communicate()
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ConfigError("git did not answer") from exc
    return output.decode("utf-8", "replace")


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
