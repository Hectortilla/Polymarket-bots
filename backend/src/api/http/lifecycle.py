"""Atomic run transitions owned by the HTTP API."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.runs.contracts import RunRead
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from api.runs.store.transitions import RunTransitions
from api.runs.terminal import TerminalRunWriter

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
        transition = await RunTransitions(self._session).request_stop_transition(
            run_id,
            now=now,
        )
        if transition.row is None:
            await self._session.commit()
            return None
        if transition.applied_status is RunStatus.STOPPED:
            return await self._commit_terminal(transition.row)

        run = await RunStore(self._session).read_row(transition.row)
        await self._session.commit()
        return run, None

    async def _commit_terminal(
        self,
        row: RunRow,
    ) -> tuple[RunRead, int]:
        run = await RunStore(self._session).read_row(row)
        event_id = await TerminalRunWriter(self._session).commit(row)
        return run, event_id
