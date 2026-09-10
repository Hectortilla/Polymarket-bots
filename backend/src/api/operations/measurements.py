"""Read operational PostgreSQL aggregates without private run/account payloads."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.operations.measurement_contracts import DatabaseMeasurements
from api.operations.state import OperationControlStore
from api.runs.lease import ExecutionLease
from api.runs.models import RunRow
from api.runs.status import INTERRUPTIBLE_RUN_STATUSES, RunStatus


class OperationMeasurements:
    def __init__(self, session: AsyncSession, lease_seconds: float) -> None:
        self._session = session
        self._lease_seconds = lease_seconds

    async def read(self) -> DatabaseMeasurements:
        control = await OperationControlStore(self._session).require()
        queued_run_count, queue_age_seconds = await self._read_queue_metrics()
        stuck_run_count = await self._session.scalar(
            select(func.count())
            .select_from(RunRow)
            .where(
                RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES),
                ExecutionLease.expired_predicate(
                    func.clock_timestamp() - timedelta(seconds=self._lease_seconds)
                ),
            )
        )
        database_size_bytes = await self._session.scalar(
            select(func.pg_database_size(func.current_database()))
        )
        active_run_ids = tuple(
            (
                await self._session.scalars(
                    select(RunRow.id).where(
                        RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES)
                    )
                )
            ).all()
        )
        return DatabaseMeasurements(
            queue_depth=queued_run_count,
            queue_age_seconds=float(queue_age_seconds),
            stuck_runs=stuck_run_count,
            database_bytes=database_size_bytes,
            active_run_ids=active_run_ids,
            admissions_paused=control.admissions_paused,
        )

    async def _read_queue_metrics(self):
        return (
            await self._session.execute(
                select(
                    func.count(),
                    func.coalesce(
                        func.greatest(
                            0,
                            func.extract(
                                "epoch",
                                func.clock_timestamp() - func.min(RunRow.created_at),
                            ),
                        ),
                        0,
                    ),
                ).where(RunRow.status == RunStatus.QUEUED)
            )
        ).one()
