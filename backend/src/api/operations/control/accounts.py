"""Suspension persistence without committing its enclosing operator transaction."""

from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.access import AccountAccessStore
from api.lifecycle.deletion.requests import DeletionRequests
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
        await DeletionRequests(self._session).require_no_request(owner_user_id)
        if user.restore_quarantined_at is not None:
            raise ValueError(
                "account deletion or restore quarantine prevents resumption"
            )
        outcome = (
            OperatorOutcome.APPLIED
            if user.suspended_at is not None
            else OperatorOutcome.UNCHANGED
        )
        user.suspended_at = None
        self._session.add(user)
        return outcome

    async def grant_admin(self, owner_user_id: UUID) -> OperatorOutcome:
        return await self._set_admin(owner_user_id, enabled=True)

    async def revoke_admin(self, owner_user_id: UUID) -> OperatorOutcome:
        return await self._set_admin(owner_user_id, enabled=False)

    async def _set_admin(
        self, owner_user_id: UUID, *, enabled: bool
    ) -> OperatorOutcome:
        user = await self._access.lock_account(owner_user_id)
        if user is None:
            return OperatorOutcome.NOT_FOUND
        if enabled:
            await DeletionRequests(self._session).require_no_request(owner_user_id)
            if not user.access_allowed or user.email_verified_at is None:
                raise ValueError("admin grants require a verified, active account")
        if user.is_admin == enabled:
            return OperatorOutcome.UNCHANGED
        user.is_admin = enabled
        self._session.add(user)
        await self._access.delete_sessions(user.id)
        return OperatorOutcome.APPLIED
