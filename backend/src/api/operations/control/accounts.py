"""Suspension persistence without committing its enclosing operator transaction."""

from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.access import AccountAccessStore
from api.operations.schema import OperatorOutcome


class AccountControls:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._access = AccountAccessStore(session)

    async def suspend(self, owner_user_id: UUID) -> OperatorOutcome:
        user = await self._access.lock_account(owner_user_id)
        if user is None:
            return OperatorOutcome.NOT_FOUND
        outcome = (
            OperatorOutcome.APPLIED
            if user.suspended_at is None
            else OperatorOutcome.UNCHANGED
        )
        user.suspended_at = user.suspended_at or system_now_utc()
        self._session.add(user)
        await self._access.invalidate_credentials(user.id)
        return outcome

    async def resume(self, owner_user_id: UUID) -> OperatorOutcome:
        user = await self._access.lock_account(owner_user_id)
        if user is None:
            return OperatorOutcome.NOT_FOUND
        outcome = (
            OperatorOutcome.APPLIED
            if user.suspended_at is not None
            else OperatorOutcome.UNCHANGED
        )
        user.suspended_at = None
        self._session.add(user)
        return outcome
