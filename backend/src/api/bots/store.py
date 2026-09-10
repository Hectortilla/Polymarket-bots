"""Persistence boundary for complete saved-bot configurations."""

from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.bots.contracts import BotRead
from api.bots.errors import BotHasActiveRunsError
from api.bots.models import BotRow
from api.catalog.values import DefinitionId
from api.limits.resources import SavedResourceAllowance
from api.runs.contracts import PaperRunConfig
from api.runs.models import RunRow
from api.runs.status import TERMINAL_RUN_STATUSES


class BotStore:
    def __init__(self, session: AsyncSession, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id
        self._owned_bots_statement = select(BotRow).where(
            BotRow.owner_user_id == owner_user_id, BotRow.deleted_at.is_(None)
        )

    async def create(
        self,
        *,
        definition_id: DefinitionId,
        config: PaperRunConfig,
    ) -> BotRead:
        await SavedResourceAllowance(self._session, self._owner_user_id).reserve_bot()
        row = BotRow(
            owner_user_id=self._owner_user_id,
            definition_id=definition_id,
            config=config.model_dump(mode="json"),
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.commit()
        await self._session.refresh(row)
        return self.read_from_row(row)

    async def read(self, bot_id: UUID, *, lock: bool = False) -> BotRead | None:
        statement = self._owned_bots_statement.where(BotRow.id == bot_id)
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        return self.read_from_row(row)

    async def list(self) -> tuple[BotRead, ...]:
        rows = (
            await self._session.execute(
                self._owned_bots_statement.order_by(
                    BotRow.updated_at.desc(), BotRow.id.desc()
                )
            )
        ).scalars()
        return tuple(self.read_from_row(row) for row in rows)

    async def soft_delete(self, bot_id: UUID) -> bool:
        # Launches and edits take this same lock before committing their writes.
        row = (
            await self._session.execute(
                self._owned_bots_statement.where(BotRow.id == bot_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        active_run = await self._session.scalar(
            select(RunRow.id)
            .where(
                RunRow.bot_id == bot_id,
                RunRow.status.not_in(TERMINAL_RUN_STATUSES),
            )
            .limit(1)
        )
        if active_run is not None:
            raise BotHasActiveRunsError
        row.deleted_at = system_now_utc()
        row.updated_at = row.deleted_at
        self._session.add(row)
        await self._session.commit()
        return True

    async def update_config(
        self,
        bot_id: UUID,
        config: PaperRunConfig,
    ) -> BotRead | None:
        statement = self._owned_bots_statement.where(
            BotRow.id == bot_id
        ).with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            await self._session.commit()
            return None
        row.config = config.model_dump(mode="json")
        row.updated_at = system_now_utc()
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return self.read_from_row(row)

    @staticmethod
    def read_from_row(
        row: BotRow,
    ) -> BotRead:
        return BotRead(
            id=row.id,
            definition_id=row.definition_id,
            config=PaperRunConfig.model_validate(row.config),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
