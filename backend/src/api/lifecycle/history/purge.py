"""Delete a bounded event batch while holding its terminal parent run lock."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.events.models import EventRow
from api.lifecycle.policy import CLEANUP_EVENT_BATCH_SIZE
from api.runs.models import RunRow
from api.runs.status import TERMINAL_RUN_STATUSES


class TerminalHistoryPurger:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def purge(self, run_id: UUID, now: datetime) -> bool:
        run = await self._session.scalar(
            select(RunRow).where(RunRow.id == run_id).with_for_update()
        )
        if run is None:
            return True
        if run.status not in TERMINAL_RUN_STATUSES:
            return False
        # Hide an expired run before partial event removal is committed. Readers
        # must never mistake a partially purged event prefix for complete history.
        run.history_expired_at = run.history_expired_at or now
        self._session.add(run)
        event_ids_query = (
            select(EventRow.id)
            .where(EventRow.run_id == run_id)
            .order_by(EventRow.id)
            .limit(CLEANUP_EVENT_BATCH_SIZE)
        )
        await self._session.execute(
            delete(EventRow).where(EventRow.id.in_(event_ids_query))
        )
        if (
            await self._session.scalar(
                select(EventRow.id).where(EventRow.run_id == run_id).limit(1)
            )
            is not None
        ):
            return False
        await self._session.delete(run)
        return True
