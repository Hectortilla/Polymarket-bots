"""Account-owned saved-resource admission and usage queries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.bots.models import BotRow
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.limits.policy import PAPER_BETA
from api.operations.admission import OperationAdmission


class SavedResourceAllowance:
    def __init__(self, session: AsyncSession, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def reserve_bot(self) -> None:
        await OperationAdmission(self._session).require_active_account(
            self._owner_user_id
        )
        count = await self.count_bots()
        if count >= PAPER_BETA.saved_bots:
            raise ResourceLimitError(
                ResourceLimitCode.USER_ALLOWANCE,
                "Your saved-bot allowance is full. Edit an existing bot.",
            )

    async def count_bots(self) -> int:
        return await self._session.scalar(
            select(func.count())
            .select_from(BotRow)
            .where(
                BotRow.owner_user_id == self._owner_user_id, BotRow.deleted_at.is_(None)
            )
        )
