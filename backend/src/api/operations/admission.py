"""Incident policy over the shared persisted control and account boundaries."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.access import AccountAccessStore
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.operations.state import OperationControlStore

INCIDENT_ADMISSION_DETAIL = (
    "Paper launches are paused for maintenance. Try again later."
)
SUSPENDED_ACCOUNT_DETAIL = "This account is suspended. Contact support."


class OperationAdmission:
    def __init__(self, session: AsyncSession) -> None:
        self._state = OperationControlStore(session)
        self._accounts = AccountAccessStore(session)

    async def require_launch(self, owner_user_id: UUID) -> None:
        if await self.admissions_paused():
            raise ResourceLimitError(
                ResourceLimitCode.INCIDENT_PAUSED, INCIDENT_ADMISSION_DETAIL
            )
        await self.require_active_account(owner_user_id)

    async def admissions_paused(self) -> bool:
        return (await self._state.require()).admissions_paused

    async def require_active_account(self, owner_user_id: UUID) -> None:
        account = await self._accounts.lock_account(owner_user_id)
        if account is None:
            raise RuntimeError("admission requires a persisted account")
        if not account.access_allowed:
            raise ResourceLimitError(
                ResourceLimitCode.ACCOUNT_SUSPENDED, SUSPENDED_ACCOUNT_DETAIL
            )
