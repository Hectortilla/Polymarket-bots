"""Database execution ownership, shared by worker writes and paper fills."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from api.runs.failures import ExecutionOwnershipLost
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.models import RunRow
from api.runs.status import INTERRUPTIBLE_RUN_STATUSES


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    token: UUID
    seconds: float = DEFAULT_LEASE_SECONDS

    async def require(self, session: AsyncSession, run_id: UUID) -> None:
        # Lock first, then evaluate the database clock: time spent waiting for
        # another publisher must not let a formerly fresh lease pass the fence.
        await session.execute(
            select(RunRow.id).where(RunRow.id == run_id).with_for_update()
        )
        owned_run_id = await session.scalar(
            select(RunRow.id).where(RunRow.id == run_id, self.owned_predicate())
        )
        if owned_run_id is None:
            raise ExecutionOwnershipLost("paper execution lease is no longer valid")

    def owned_predicate(self) -> ColumnElement[bool]:
        return and_(
            RunRow.execution_token == self.token,
            RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES),
            RunRow.heartbeat_at
            >= func.clock_timestamp() - timedelta(seconds=self.seconds),
        )

    @staticmethod
    def expired_predicate(expired_before: datetime) -> ColumnElement[bool]:
        return or_(RunRow.heartbeat_at < expired_before, RunRow.heartbeat_at.is_(None))
