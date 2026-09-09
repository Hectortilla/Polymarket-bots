"""Host-owned database fence immediately before a paper portfolio mutation."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.runs.lease import ExecutionLease


class FillOwnership:
    def __init__(
        self,
        run_id: UUID,
        session_factory: async_sessionmaker[AsyncSession],
        lease: ExecutionLease,
    ) -> None:
        self._run_id = run_id
        self._session_factory = session_factory
        self._lease = lease

    @asynccontextmanager
    async def scope(self) -> AsyncIterator[None]:
        async with (
            asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS),
            self._session_factory() as session,
        ):
            await self._lease.require(session, self._run_id)
            yield
