"""Account-owned saved-resource admission and usage queries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.models import UserRow
from api.bots.models import BotRow
from api.graph_templates.models import GraphTemplateRow
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.limits.policy import PAPER_BETA


class SavedResourceAllowance:
    def __init__(self, session: AsyncSession, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def reserve_bot(self) -> None:
        await self._lock_owner()
        count = await self.count_bots()
        if count >= PAPER_BETA.saved_bots:
            raise ResourceLimitError(
                ResourceLimitCode.USER_ALLOWANCE,
                "Your saved-bot allowance is full. Edit an existing bot.",
            )

    async def reserve_template(self) -> None:
        await self._lock_owner()
        count = await self.count_templates()
        if count >= PAPER_BETA.saved_templates:
            raise ResourceLimitError(
                ResourceLimitCode.USER_ALLOWANCE,
                "Your saved-template allowance is full. Edit an existing template.",
            )

    async def count_bots(self) -> int:
        return await self._session.scalar(
            select(func.count())
            .select_from(BotRow)
            .where(BotRow.owner_user_id == self._owner_user_id)
        )

    async def count_templates(self) -> int:
        return await self._session.scalar(
            select(func.count())
            .select_from(GraphTemplateRow)
            .where(GraphTemplateRow.owner_user_id == self._owner_user_id)
        )

    async def _lock_owner(self) -> None:
        owner = await self._session.scalar(
            select(UserRow.id)
            .where(UserRow.id == self._owner_user_id)
            .with_for_update()
        )
        if owner is None:
            raise RuntimeError("resource admission requires a persisted account")
