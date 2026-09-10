"""Supervised bounded data maintenance; failures are visible and retryable."""

import asyncio

from polybot.framework.clock import system_now_utc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.lifecycle.audit import AuditRetention
from api.lifecycle.deletion.purge import AccountPurger
from api.lifecycle.history.retention import HistoryRetention
from api.lifecycle.policy import CLEANUP_INTERVAL_SECONDS
from api.operations.observations.contracts import FailureObservation, Observation
from api.operations.observations.sink import OPERATION_LOG


class DataMaintenance:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def serve(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                OPERATION_LOG.emit(
                    FailureObservation(Observation.DATA_MAINTENANCE_FAILED)
                )
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

    async def tick(self) -> None:
        now = system_now_utc()
        for maintenance in (AccountPurger, HistoryRetention, AuditRetention):
            async with (
                asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS),
                self._sessions() as session,
            ):
                await maintenance(session).clean(now)
