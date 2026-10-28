"""`python -m app.worker`: one worker process (s04 §4.1). Runs until SIGTERM or SIGINT.

Run it beside an api started with RUN_WORKER_IN_API=false, or beside other workers: leases
keep each user's turns to one worker at a time.
"""

import asyncio
import signal

from app.core.config import load_settings
from app.core.logging import configure_logging, get_logger
from app.wiring import build_container, close_container

logger = get_logger(__name__)


async def run_worker() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, environment=settings.environment)
    container = build_container(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, stop.set)
    try:
        await container.worker.start()
        await stop.wait()
        logger.info("worker_shutdown_requested")
        await container.worker.stop()
    finally:
        await close_container(container)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
