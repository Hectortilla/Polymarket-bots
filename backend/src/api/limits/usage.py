"""Private account usage projected from authoritative persisted resources."""

from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.bots.models import BotRow
from api.lifecycle.history.selection import HistorySelection
from api.limits.contracts import AccountUsage
from api.limits.policy import PAPER_BETA
from api.limits.resources import SavedResourceAllowance
from api.runs.models import RunRow
from api.runs.status import INTERRUPTIBLE_RUN_STATUSES, RunStatus


class AccountUsageReader:
    def __init__(self, session: AsyncSession, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id
        self._saved = SavedResourceAllowance(session, owner_user_id)

    async def usage(self) -> AccountUsage:
        counts = dict(
            (
                await self._session.execute(
                    select(RunRow.status, func.count())
                    .join(BotRow, BotRow.id == RunRow.bot_id)
                    .where(BotRow.owner_user_id == self._owner_user_id)
                    .group_by(RunRow.status)
                )
            ).all()
        )
        return AccountUsage(
            policy=PAPER_BETA,
            active_runs=sum(
                counts.get(status, 0) for status in INTERRUPTIBLE_RUN_STATUSES
            ),
            queued_runs=counts.get(RunStatus.QUEUED, 0),
            saved_bots=await self._saved.count_bots(),
            retained_runs=await self._retained_run_count(),
        )

    async def _retained_run_count(self) -> int:
        retained_run_ids_query = HistorySelection(
            system_now_utc()
        ).retained_run_ids_query(self._owner_user_id)
        return await self._session.scalar(
            select(func.count()).select_from(retained_run_ids_query.subquery())
        )
