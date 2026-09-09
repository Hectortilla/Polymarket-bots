"""PostgreSQL run accounting: lifecycle rows are the durable reservations."""

from collections import Counter
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.bots.models import BotRow
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.limits.policy import PAPER_BETA
from api.runs.models import RunRow
from api.runs.status import INTERRUPTIBLE_RUN_STATUSES, RunStatus

RUN_ADMISSION_LOCK_ID = 17001


class RunAdmission:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def require_queue_capacity(self, bot_id: UUID) -> None:
        """Require room inside the caller's admission-locked transaction."""
        owner = await self._session.scalar(
            select(BotRow.owner_user_id).where(BotRow.id == bot_id)
        )
        if owner is None:
            raise RuntimeError("run admission requires a persisted bot owner")
        queued = await self._queued_owners()
        if queued.count(owner) >= PAPER_BETA.queued_runs:
            raise ResourceLimitError(
                ResourceLimitCode.USER_ALLOWANCE,
                "Your queued-run allowance is full. Stop a queued run or wait for one to start.",
            )
        if len(queued) >= PAPER_BETA.global_queued_runs:
            raise ResourceLimitError(
                ResourceLimitCode.GLOBAL_CAPACITY,
                "The shared run queue is full. Try again after a run starts.",
            )

    async def next_eligible_queued_run_id(self) -> UUID | None:
        await self.lock_transaction()
        active_owners = list(
            (
                await self._session.execute(
                    select(BotRow.owner_user_id)
                    .join(RunRow, RunRow.bot_id == BotRow.id)
                    .where(RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES))
                )
            ).scalars()
        )
        if len(active_owners) >= PAPER_BETA.global_active_runs:
            return None
        active = Counter(active_owners)
        queued = (
            await self._session.execute(
                select(RunRow.id, BotRow.owner_user_id)
                .join(BotRow, BotRow.id == RunRow.bot_id)
                .where(RunRow.status == RunStatus.QUEUED)
                .order_by(RunRow.created_at, RunRow.id)
            )
        ).all()
        for run_id, owner in queued:
            if active[owner] < PAPER_BETA.active_runs:
                return run_id
        return None

    async def lock_transaction(self) -> None:
        # One transaction lock serializes admission, claim and release across
        # processes. Committed lifecycle rows avoid a second mutable counter.
        await self._session.execute(
            select(func.pg_advisory_xact_lock(RUN_ADMISSION_LOCK_ID))
        )

    async def _queued_owners(self) -> list[UUID]:
        return list(
            (
                await self._session.execute(
                    select(BotRow.owner_user_id)
                    .join(RunRow, RunRow.bot_id == BotRow.id)
                    .where(RunRow.status == RunStatus.QUEUED)
                )
            ).scalars()
        )
