"""Worker capability bound to one execution lease."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.runs.failures import (
    ExecutionOwnershipLost,
)
from api.runs.lease import ExecutionLease
from api.runs.status import (
    RunStatus,
)

if TYPE_CHECKING:
    from api.runs.store import RunStore


class OwnedRunStore:
    """Narrow worker capability: every mutation requires its immutable lease."""

    def __init__(
        self, store: RunStore, session: AsyncSession, lease: ExecutionLease
    ) -> None:
        self._session = session
        self._store = store
        self._lease = lease

    async def status(self, run_id: UUID) -> RunStatus | None:
        return await self._store.status(run_id)

    async def mark_running(self, run_id: UUID) -> bool:
        return await self._store.transitions.commit(
            run_id, RunStatus.RUNNING, execution_lease=self._lease
        )

    async def begin_stopping(self, run_id: UUID) -> bool:
        return await self._store.transitions.commit(
            run_id, RunStatus.STOPPING, execution_lease=self._lease
        )

    async def heartbeat(self, run_id: UUID, *, now: datetime) -> bool:
        try:
            await self._lease.require(self._session, run_id)
        except ExecutionOwnershipLost:
            await self._session.rollback()
            return False
        return await self._store.heartbeat(run_id, now=now)

    async def finish(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        now: datetime,
        failure_detail: str | None = None,
    ) -> bool:
        return await self._store.finish(
            run_id,
            status=status,
            now=now,
            failure_detail=failure_detail,
            execution_lease=self._lease,
        )
