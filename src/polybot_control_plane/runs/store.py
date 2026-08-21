"""Small async persistence boundary for Slice 12A runs."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from polybot_control_plane.runs.contracts import PaperRunConfig, RunRead
from polybot_control_plane.runs.models import RunRow
from polybot_control_plane.runs.status import RunStatus


class RunStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        definition_id: str,
        definition_version: int,
        config: PaperRunConfig,
    ) -> RunRead:
        row = RunRow(
            definition_id=definition_id,
            definition_version=definition_version,
            config=config.model_dump(mode="json"),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return self._read_from_row(row)

    async def read(self, run_id: UUID) -> RunRead | None:
        row = await self._session.get(RunRow, run_id)
        return None if row is None else self._read_from_row(row)

    async def list(self) -> tuple[RunRead, ...]:
        statement = select(RunRow).order_by(
            RunRow.created_at.desc(),
            RunRow.id.desc(),
        )
        rows = (await self._session.execute(statement)).scalars()
        return tuple(self._read_from_row(row) for row in rows)

    async def claim(self, run_id: UUID, *, now: datetime) -> RunRead | None:
        statement = (
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status == RunStatus.QUEUED)
            .values(status=RunStatus.STARTING, started_at=now, heartbeat_at=now)
            .returning(RunRow)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        await self._session.commit()
        return None if row is None else self._read_from_row(row)

    async def heartbeat(self, run_id: UUID, *, now: datetime) -> None:
        await self._session.execute(update(RunRow).where(RunRow.id == run_id).values(heartbeat_at=now))
        await self._session.commit()

    async def set_status(self, run_id: UUID, status: RunStatus) -> None:
        await self._session.execute(update(RunRow).where(RunRow.id == run_id).values(status=status))
        await self._session.commit()

    async def status(self, run_id: UUID) -> RunStatus | None:
        row = await self._session.get(RunRow, run_id)
        return None if row is None else row.status

    async def finish(self, run_id: UUID, *, status: RunStatus, now: datetime, failure_detail: str | None = None) -> None:
        await self._session.execute(
            update(RunRow).where(RunRow.id == run_id).values(
                status=status, ended_at=now, heartbeat_at=now, failure_detail=failure_detail,
            )
        )
        await self._session.commit()

    @staticmethod
    def _read_from_row(row: RunRow) -> RunRead:
        return RunRead(
            id=row.id,
            definition_id=row.definition_id,
            definition_version=row.definition_version,
            config=PaperRunConfig.model_validate(row.config),
            status=row.status,
            created_at=row.created_at,
            started_at=row.started_at,
            ended_at=row.ended_at,
            heartbeat_at=row.heartbeat_at,
            failure_detail=row.failure_detail,
        )
