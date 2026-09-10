"""Restore markers and account reconciliation eligibility under the account lock."""

from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.access import AccountAccessStore
from api.auth.models import UserRow
from api.lifecycle.deletion.requests import DeletionRequests
from api.operations.state import OperationControlStore


class RestoreAccountState:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def quarantine_all(self) -> None:
        await self._session.execute(
            update(UserRow).values(
                restore_quarantined_at=func.coalesce(
                    UserRow.restore_quarantined_at, system_now_utc()
                )
            )
        )

    async def approve_reconciled_account(self, user_id: UUID) -> None:
        control = await OperationControlStore(self._session).require()
        if not control.admissions_paused:
            raise ValueError("restore approval requires paused admissions")
        user = await AccountAccessStore(self._session).require_locked_account(user_id)
        await DeletionRequests(self._session).require_no_request(user_id)
        if user.suspended_at is not None or user.restore_quarantined_at is None:
            raise ValueError(
                "restore approval requires a quarantined, unsuspended account"
            )
        user.restore_quarantined_at = None
        self._session.add(user)
