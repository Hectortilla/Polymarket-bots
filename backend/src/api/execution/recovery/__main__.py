"""Long-running recovery process and graceful signal handling."""

import asyncio
import logging
import signal

from redis.asyncio import Redis

from api.deployment.settings import StartupSettings
from api.execution.recovery import RunRecovery
from api.execution.recovery.policy import DELIVERY_RETRY_SECONDS
from api.execution.taskiq_app import TaskiqRunLauncher
from api.execution.worker.database import create_worker_database
from api.io_policy import REDIS_SOCKET_OPTIONS
from api.operations.monitor import OperationMonitor

LOGGER = logging.getLogger(__name__)


async def serve_recovery(settings: StartupSettings) -> None:
    engine, session_factory = create_worker_database(
        settings.database_url.get_secret_value()
    )
    recovery = RunRecovery(
        session_factory, TaskiqRunLauncher(), lease_seconds=settings.lease_seconds
    )
    redis = Redis.from_url(settings.redis_url.get_secret_value(), **REDIS_SOCKET_OPTIONS)
    monitor = OperationMonitor(session_factory, redis, lease_seconds=settings.lease_seconds, storage_path=settings.storage_probe_path)
    monitor_task = asyncio.create_task(monitor.serve())
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)
    try:
        while not stopping.is_set():
            if monitor_task.done():
                await monitor_task
                raise RuntimeError("operation monitor ended unexpectedly")
            try:
                await recovery.tick()
            except Exception:
                LOGGER.error("run recovery requires PostgreSQL; retrying after outage")
            try:
                await asyncio.wait_for(stopping.wait(), timeout=DELIVERY_RETRY_SECONDS)
            except TimeoutError:
                continue
    finally:
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(serve_recovery(StartupSettings.from_env()))
