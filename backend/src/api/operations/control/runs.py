"""Select incident-affected runs, then use the shared terminal event owner."""

from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.bots.models import BotRow
from api.operations.schema import OperatorOutcome
from api.runs.models import RunRow
from api.runs.status import TERMINAL_RUN_STATUSES, RunStatus
from api.runs.store import RunStore
from api.runs.terminal import TerminalRunWriter


class RunTermination:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._runs = RunStore(session)
        self._terminal = TerminalRunWriter(session)

    async def terminate_all(self) -> None:
        await self._terminate(self._unfinished_runs_query())

    async def terminate_account(self, owner_user_id: UUID) -> None:
        await self._terminate(
            self._unfinished_runs_query()
            .join(BotRow, BotRow.id == RunRow.bot_id)
            .where(BotRow.owner_user_id == owner_user_id)
        )

    async def terminate_run(self, run_id: UUID) -> OperatorOutcome:
        row = await self._session.get(RunRow, run_id)
        if row is None:
            return OperatorOutcome.NOT_FOUND
        if row.status in TERMINAL_RUN_STATUSES:
            return OperatorOutcome.UNCHANGED
        await self._terminate(self._unfinished_runs_query().where(RunRow.id == run_id))
        return OperatorOutcome.APPLIED

    async def _terminate(self, unfinished_runs_query) -> None:
        for row in (await self._session.scalars(unfinished_runs_query)).all():
            status = (
                RunStatus.STOPPED
                if row.status is RunStatus.QUEUED
                else RunStatus.INTERRUPTED
            )
            terminal = await self._runs.transition_row(
                row.id, status, ended_at=system_now_utc()
            )
            if terminal is not None:
                await self._terminal.stage(terminal)

    @staticmethod
    def _unfinished_runs_query():
        return (
            select(RunRow)
            .where(RunRow.status.not_in(TERMINAL_RUN_STATUSES))
            .order_by(RunRow.id)
        )
