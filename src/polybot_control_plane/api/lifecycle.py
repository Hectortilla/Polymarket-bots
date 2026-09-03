"""Atomic run transitions owned by the HTTP API."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from polybot_control_plane.events.contracts import RunLifecycleEvent
from polybot_control_plane.events.models import EventRow
from polybot_control_plane.runs.contracts import RunRead
from polybot_control_plane.runs.models import RunRow
from polybot_control_plane.runs.status import QUEUED_PREVIOUS_STATUSES, RunStatus
from polybot_control_plane.runs.store import RunStore


type ApiRunTransition = tuple[RunRead, int | None]


class ApiRunLifecycle:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request_stop(
        self,
        run_id: UUID,
        *,
        now: datetime,
    ) -> ApiRunTransition | None:
        transition = await RunStore(self._session).request_stop_transition(
            run_id,
            now=now,
        )
        if transition.row is None:
            await self._session.commit()
            return None
        if transition.applied_status is RunStatus.STOPPED:
            return await self._commit_terminal(transition.row, occurred_at=now)

        run = await RunStore(self._session).read_row(transition.row)
        await self._session.commit()
        return run, None

    async def fail_launch(
        self,
        run_id: UUID,
        *,
        now: datetime,
        failure_detail: str,
    ) -> tuple[RunRead, int]:
        row = await RunStore(self._session).transition_row(
            run_id,
            RunStatus.FAILED,
            expected_statuses=QUEUED_PREVIOUS_STATUSES,
            ended_at=now,
            failure_detail=failure_detail,
        )
        if row is None:
            raise RuntimeError("queued launch failure transition was lost")
        return await self._commit_terminal(row, occurred_at=now)

    async def _commit_terminal(
        self,
        row: RunRow,
        *,
        occurred_at: datetime,
    ) -> tuple[RunRead, int]:
        try:
            run = await RunStore(self._session).read_row(row)
            event = RunLifecycleEvent.from_terminal_status(
                row.id,
                row.status,
                occurred_at=occurred_at,
            )
            event_row = EventRow.from_event(event)
            self._session.add(event_row)
            await self._session.flush()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.commit()
        return run, event_row.id
