"""Per-account history selection under the approved age and count policy."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.lifecycle.history.purge import TerminalHistoryPurger
from api.lifecycle.history.selection import HistorySelection
from api.lifecycle.policy import CLEANUP_RUN_BATCH_SIZE
from api.limits.admission import RunAdmission


class HistoryRetention:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def clean(self, now: datetime) -> int:
        await RunAdmission(self._session).lock_transaction()
        run_ids = (
            await self._session.scalars(
                HistorySelection(now)
                .expired_run_ids_query()
                .limit(CLEANUP_RUN_BATCH_SIZE)
            )
        ).all()
        purger = TerminalHistoryPurger(self._session)
        removed_run_count = 0
        for run_id in run_ids:
            removed_run_count += await purger.purge(run_id, now)
        await self._session.commit()
        return removed_run_count
