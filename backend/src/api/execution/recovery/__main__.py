"""Long-running recovery process and graceful signal handling."""

import asyncio
import logging
import signal

from api.deployment.settings import StartupSettings
from api.execution.recovery import RunRecovery
from api.execution.recovery.policy import DELIVERY_RETRY_SECONDS
from api.execution.taskiq_app import TaskiqRunLauncher
from api.execution.worker.database import create_worker_database

LOGGER = logging.getLogger(__name__)


async def serve_recovery(settings: StartupSettings) -> None:
    engine, session_factory = create_worker_database(
        settings.database_url.get_secret_value()
    )
    recovery = RunRecovery(
        session_factory, TaskiqRunLauncher(), lease_seconds=settings.lease_seconds
    )
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)
    try:
        while not stopping.is_set():
            try:
                await recovery.tick()
            except Exception:
                LOGGER.error("run recovery requires PostgreSQL; retrying after outage")
            try:
                await asyncio.wait_for(stopping.wait(), timeout=DELIVERY_RETRY_SECONDS)
            except TimeoutError:
                continue
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(serve_recovery(StartupSettings.from_env()))
