"""Atomic run status and lease transition persistence."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.limits.admission import RunAdmission
from api.runs.failures import (
    INTERRUPTION_DETAIL,
    ExecutionOwnershipLost,
)
from api.runs.lease import ExecutionLease
from api.runs.models import RunRow
from api.runs.status import (
    OWNED_STOP_PREVIOUS_STATUSES,
    QUEUED_PREVIOUS_STATUSES,
    TERMINAL_RUN_STATUSES,
    RunStatus,
)
from api.runs.terminal import TerminalRunWriter


@dataclass(frozen=True, slots=True)
class RunStopTransition:
    row: RunRow | None
    applied_status: RunStatus | None


class RunTransitions:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request_stop_transition(
        self,
        run_id: UUID,
        *,
        now: datetime,
    ) -> RunStopTransition:
        stopped_row = await self.transition_row(
            run_id,
            RunStatus.STOPPED,
            expected_statuses=QUEUED_PREVIOUS_STATUSES,
            ended_at=now,
        )
        if stopped_row is not None:
            return RunStopTransition(stopped_row, RunStatus.STOPPED)

        requested_row = await self.transition_row(
            run_id,
            RunStatus.STOP_REQUESTED,
            expected_statuses=OWNED_STOP_PREVIOUS_STATUSES,
        )
        if requested_row is not None:
            return RunStopTransition(requested_row, RunStatus.STOP_REQUESTED)

        return RunStopTransition(await self._session.get(RunRow, run_id), None)

    async def transition_row(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        expected_statuses: frozenset[RunStatus] | None = None,
        expired_before: datetime | None = None,
        execution_lease: ExecutionLease | None = None,
        **transition_updates: object,
    ) -> RunRow | None:
        if status in TERMINAL_RUN_STATUSES:
            await RunAdmission(self._session).lock_transaction()
        if execution_lease is not None:
            try:
                await execution_lease.require(self._session, run_id)
            except ExecutionOwnershipLost:
                await self._session.rollback()
                return None
        if status is RunStatus.INTERRUPTED:
            transition_updates["failure_detail"] = INTERRUPTION_DETAIL
        allowed_previous = status.previous_statuses()
        expected = expected_statuses or allowed_previous
        if not expected or not expected.issubset(allowed_previous):
            raise ValueError(f"invalid previous statuses for transition to {status}")
        statement = (
            update(RunRow)
            .where(
                RunRow.id == run_id,
                RunRow.status.in_(expected),
            )
            .values(status=status, **transition_updates)
            .returning(RunRow)
        )
        if expired_before is not None:
            statement = statement.where(
                ExecutionLease.expired_predicate(expired_before)
            )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def commit(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        expected_statuses: frozenset[RunStatus] | None = None,
        **transition_updates: object,
    ) -> bool:
        row = await self.transition_row(
            run_id,
            status,
            expected_statuses=expected_statuses,
            **transition_updates,
        )
        if row is not None and status in TERMINAL_RUN_STATUSES:
            await TerminalRunWriter(self._session).commit(row)
        else:
            await self._session.commit()
        return row is not None
