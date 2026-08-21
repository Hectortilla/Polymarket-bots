"""Small async persistence boundary for Slice 12A runs."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from polybot_control_plane.runs.contracts import PaperRunConfig, RunRead
from polybot_control_plane.runs.models import RunRow


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

    @staticmethod
    def _read_from_row(row: RunRow) -> RunRead:
        return RunRead(
            id=row.id,
            definition_id=row.definition_id,
            definition_version=row.definition_version,
            config=PaperRunConfig.model_validate(row.config),
            status=row.status,
            created_at=row.created_at,
        )
