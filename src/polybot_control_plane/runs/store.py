"""Async persistence boundary for durable paper-run lifecycle state."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from polybot_control_plane.runs.contracts import PaperRunConfig, RunRead
from polybot_control_plane.runs.models import RunRow
from polybot_control_plane.runs.status import (
    INTERRUPTIBLE_RUN_STATUSES,
    OWNED_STOP_PREVIOUS_STATUSES,
    QUEUED_PREVIOUS_STATUSES,
    TERMINAL_RUN_STATUSES,
    RunStatus,
)


@dataclass(frozen=True, slots=True)
class RunStopTransition:
    row: RunRow | None
    applied_status: RunStatus | None


class RunStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        definition_id: str,
        config: PaperRunConfig,
    ) -> RunRead:
        row = RunRow(
            definition_id=definition_id,
            config=config.model_dump(mode="json"),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return self.read_from_row(row)

    async def read(self, run_id: UUID) -> RunRead | None:
        row = await self._session.get(RunRow, run_id)
        return None if row is None else self.read_from_row(row)

    async def list(self) -> tuple[RunRead, ...]:
        statement = select(RunRow).order_by(
            RunRow.created_at.desc(),
            RunRow.id.desc(),
        )
        rows = (await self._session.execute(statement)).scalars()
        return tuple(self.read_from_row(row) for row in rows)

    async def claim(self, run_id: UUID, *, now: datetime) -> RunRead | None:
        # The status predicate makes duplicate Taskiq deliveries race on one
        # database write; only the winner receives a typed run to execute.
        statement = (
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status == RunStatus.QUEUED)
            .values(status=RunStatus.STARTING, started_at=now, heartbeat_at=now)
            .returning(RunRow)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            await self._session.commit()
            return None
        try:
            claimed = self.read_from_row(row)
        except Exception:
            await self._session.rollback()
            raise
        await self._session.commit()
        return claimed

    async def mark_running(self, run_id: UUID) -> bool:
        return await self._transition(run_id, RunStatus.RUNNING)

    async def begin_completion(self, run_id: UUID) -> bool:
        return await self._transition(
            run_id,
            RunStatus.STOPPING,
            expected_statuses=frozenset({RunStatus.RUNNING}),
        )

    async def begin_stopping(self, run_id: UUID) -> bool:
        return await self._transition(
            run_id,
            RunStatus.STOPPING,
            expected_statuses=frozenset({RunStatus.STOP_REQUESTED}),
        )

    async def request_stop(self, run_id: UUID, *, now: datetime) -> RunStatus | None:
        transition = await self.request_stop_transition(run_id, now=now)
        await self._session.commit()
        return None if transition.row is None else transition.row.status

    async def request_stop_transition(
        self,
        run_id: UUID,
        *,
        now: datetime,
    ) -> RunStopTransition:
        stopped_row = await self.transition_row(
            run_id,
            RunStatus.STOPPED,
            expected_statuses=QUEUED_PREVIOUS_STATUSES,
            ended_at=now,
        )
        if stopped_row is not None:
            return RunStopTransition(stopped_row, RunStatus.STOPPED)

        requested_row = await self.transition_row(
            run_id,
            RunStatus.STOP_REQUESTED,
            expected_statuses=OWNED_STOP_PREVIOUS_STATUSES,
        )
        if requested_row is not None:
            return RunStopTransition(requested_row, RunStatus.STOP_REQUESTED)

        return RunStopTransition(await self._session.get(RunRow, run_id), None)

    async def heartbeat(self, run_id: UUID, *, now: datetime) -> bool:
        result = await self._session.execute(
            update(RunRow)
            .where(
                RunRow.id == run_id,
                RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES),
            )
            .values(heartbeat_at=now)
        )
        await self._session.commit()
        return result.rowcount == 1

    async def status(self, run_id: UUID) -> RunStatus | None:
        row = await self._session.get(RunRow, run_id)
        return None if row is None else row.status

    async def finish(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        now: datetime,
        failure_detail: str | None = None,
    ) -> bool:
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError("finish requires a terminal run status")
        expected_statuses = (
            frozenset({RunStatus.STOPPING})
            if status is RunStatus.STOPPED
            else None
        )
        return await self._transition(
            run_id,
            status,
            expected_statuses=expected_statuses,
            ended_at=now,
            failure_detail=failure_detail,
        )

    async def interrupt_expired(
        self,
        run_id: UUID,
        *,
        expired_before: datetime,
        now: datetime,
    ) -> bool:
        result = await self._session.execute(
            update(RunRow)
            .where(
                RunRow.id == run_id,
                RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES),
                RunRow.heartbeat_at < expired_before,
            )
            .values(status=RunStatus.INTERRUPTED, ended_at=now)
        )
        await self._session.commit()
        return result.rowcount == 1

    async def transition_row(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        expected_statuses: frozenset[RunStatus] | None = None,
        **values: object,
    ) -> RunRow | None:
        allowed_previous = status.previous_statuses()
        expected = expected_statuses or allowed_previous
        if not expected or not expected.issubset(allowed_previous):
            raise ValueError(f"invalid previous statuses for transition to {status}")
        statement = (
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status.in_(expected))
            .values(status=status, **values)
            .returning(RunRow)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _transition(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        expected_statuses: frozenset[RunStatus] | None = None,
        **values: object,
    ) -> bool:
        row = await self.transition_row(
            run_id,
            status,
            expected_statuses=expected_statuses,
            **values,
        )
        await self._session.commit()
        return row is not None

    @staticmethod
    def read_from_row(row: RunRow) -> RunRead:
        return RunRead(
            id=row.id,
            definition_id=row.definition_id,
            config=PaperRunConfig.model_validate(row.config),
            status=row.status,
            created_at=row.created_at,
            started_at=row.started_at,
            ended_at=row.ended_at,
            heartbeat_at=row.heartbeat_at,
            failure_detail=row.failure_detail,
        )
