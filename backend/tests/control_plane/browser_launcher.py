"""Workerless browser fixture delivery with the production recovery obligation."""

import asyncio
import logging
from contextlib import asynccontextmanager

from api.catalog.definitions import GraphRequirementError
from api.events.writer import RunEventWriter
from api.execution.recovery import RunRecovery
from api.execution.worker.lifecycle import RunLifecycleCoordinator
from api.runs.failures import RunSnapshotError
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.store import RunStore
from pydantic import ValidationError

from control_plane.onboarding_fixture.selection import onboarding_case
from control_plane.onboarding_policy import FIXTURE_TICK_SECONDS

LOGGER = logging.getLogger(__name__)


class BrowserRunLauncher:
    def __init__(self, redis, sessions):
        self.redis = redis
        self.sessions = sessions
        # Retain tasks for run-level deduplication and awaited shutdown.
        self.execution_tasks_by_run_id = {}
        self.recovery = RunRecovery(sessions, self, lease_seconds=DEFAULT_LEASE_SECONDS)

    async def launch(self, run_id):
        try:
            async with self.sessions() as session:
                run = await RunStore(session).read(run_id)
        except (GraphRequirementError, RunSnapshotError, ValidationError):
            # The real coordinator persists corrupt queued snapshots as failed.
            self._start_execution(run_id)
            return
        if run is None:
            raise LookupError("browser fixture delivery requires a persisted run")
        # Legacy ownership scenarios deliberately inspect queued state. Only the
        # explicit input cases execute here; claims/leases and recovery stay real.
        if onboarding_case(run.config.to_bot_config()) is not None:
            self._start_execution(run_id)
        else:
            await self.redis.rpush("polybot:browser:queued-runs", str(run_id))

    def install_lifespan(self, app):
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            async with original_lifespan(application):
                recovery_task = asyncio.create_task(self._recover())
                try:
                    yield
                finally:
                    await self._shutdown_background_tasks(recovery_task)

        app.router.lifespan_context = lifespan

    async def _shutdown_background_tasks(self, recovery_task):
        # Stop recovery before taking the execution snapshot so it cannot add work.
        recovery_task.cancel()
        await asyncio.gather(recovery_task, return_exceptions=True)
        tasks = tuple(self.execution_tasks_by_run_id.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _start_execution(self, run_id):
        if run_id in self.execution_tasks_by_run_id:
            return
        task = asyncio.create_task(self._execute(run_id))
        self.execution_tasks_by_run_id[run_id] = task
        task.add_done_callback(lambda done: self._on_execution_done(run_id, done))

    async def _execute(self, run_id):
        async with self.sessions() as session:
            await RunLifecycleCoordinator(
                RunStore(session),
                self.sessions,
                RunEventWriter(self.sessions, self.redis),
                heartbeat_seconds=FIXTURE_TICK_SECONDS,
            ).execute(run_id)

    def _on_execution_done(self, run_id, task):
        self.execution_tasks_by_run_id.pop(run_id, None)
        if not task.cancelled() and task.exception() is not None:
            LOGGER.error(
                "browser fixture execution failed; durable recovery will retry or interrupt",
                exc_info=task.exception(),
            )

    async def _recover(self):
        while True:
            try:
                await self.recovery.tick()
            except Exception:
                LOGGER.exception("browser fixture recovery unavailable; will retry")
            await asyncio.sleep(FIXTURE_TICK_SECONDS)
