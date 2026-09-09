"""PostgreSQL recovery scans and serialized queue-delivery attempts."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.execution.recovery.policy import DELIVERY_RETRY_SECONDS
from api.limits.admission import RunAdmission
from api.limits.policy import PAPER_BETA
from api.runs.lease import ExecutionLease
from api.runs.models import RunRow
from api.runs.status import INTERRUPTIBLE_RUN_STATUSES, RunStatus
from api.runs.store import RunStore


class RecoveryStore:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], lease_seconds: float
    ) -> None:
        self._session_factory = session_factory
        self._lease_seconds = lease_seconds

    async def interrupt_expired(self) -> None:
        async with self._session_factory() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            expired_before = now - timedelta(seconds=self._lease_seconds)
            run_ids = tuple(
                (
                    await session.scalars(
                        select(RunRow.id)
                        .where(
                            RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES),
                            ExecutionLease.expired_predicate(expired_before),
                        )
                        .limit(PAPER_BETA.global_active_runs)
                    )
                ).all()
            )
        # Recheck each candidate transactionally so heartbeat/Stop races converge.
        for run_id in run_ids:
            async with self._session_factory() as session:
                await RunStore(session).interrupt_expired(
                    run_id, expired_before=expired_before, now=now
                )

    async def reserve_delivery_attempts(self) -> tuple[UUID, ...]:
        async with self._session_factory() as session:
            await RunAdmission(session).lock_transaction()
            now = await session.scalar(select(func.clock_timestamp()))
            rows = tuple(
                (
                    await session.scalars(
                        select(RunRow)
                        .where(
                            RunRow.status == RunStatus.QUEUED,
                            or_(
                                RunRow.delivery_attempted_at.is_(None),
                                RunRow.delivery_attempted_at
                                <= now - timedelta(seconds=DELIVERY_RETRY_SECONDS),
                            ),
                        )
                        .order_by(RunRow.created_at, RunRow.id)
                        .limit(PAPER_BETA.global_queued_runs)
                        .with_for_update()
                    )
                ).all()
            )
            # Commit attempt ownership before sending; a lost hint ages into retry.
            for row in rows:
                row.delivery_attempted_at = now
            await session.commit()
            return tuple(row.id for row in rows)
