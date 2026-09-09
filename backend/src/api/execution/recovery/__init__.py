"""Recurring durable queue delivery and expired execution reconciliation."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.execution.launcher import RunLauncher
from api.execution.recovery.store import RecoveryStore
from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS

LOGGER = logging.getLogger(__name__)


class RunRecovery:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        launcher: RunLauncher,
        *,
        lease_seconds: float,
    ) -> None:
        self._store = RecoveryStore(session_factory, lease_seconds)
        self._launcher = launcher

    async def tick(self) -> None:
        # Recover reservations even while Redis delivery is unavailable.
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            await self._store.interrupt_expired()
            queued_run_ids = await self._store.reserve_delivery_attempts()
        for run_id in queued_run_ids:
            try:
                async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                    await self._launcher.launch(run_id)
            except Exception:
                LOGGER.warning("queued run delivery unavailable; will retry")
                # A shared delivery outage defers the rest of this batch.
                break
