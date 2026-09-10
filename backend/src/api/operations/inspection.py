"""Minimal operator run diagnosis at the private persistence boundary."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.bots.models import BotRow
from api.events.models import EventRow
from api.operations.contracts import RunInspection
from api.runs.models import RunRow
from api.runs.status import TERMINAL_RUN_STATUSES


class RunInspector:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_unfinished(self) -> tuple[RunInspection, ...]:
        run_ids = (
            await self._session.scalars(
                select(RunRow.id)
                .where(RunRow.status.not_in(TERMINAL_RUN_STATUSES))
                .order_by(RunRow.created_at, RunRow.id)
            )
        ).all()
        return tuple([await self.read(run_id) for run_id in run_ids])

    async def read(self, run_id: UUID) -> RunInspection:
        run_snapshot = (
            (
                await self._session.execute(
                    select(
                        RunRow.id,
                        RunRow.status,
                        RunRow.created_at,
                        RunRow.heartbeat_at,
                        RunRow.ended_at,
                        BotRow.owner_user_id,
                    )
                    .join(BotRow, BotRow.id == RunRow.bot_id)
                    .where(RunRow.id == run_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if run_snapshot is None:
            raise ValueError("run not found")
        event_count = await self._session.scalar(
            select(func.count()).select_from(EventRow).where(EventRow.run_id == run_id)
        )
        return RunInspection(**run_snapshot, event_count=event_count)
