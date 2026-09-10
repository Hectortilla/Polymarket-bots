"""Explicit global quarantine and individual reconciliation share one transaction gate."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.access import AccountAccessStore
from api.lifecycle.restoration.state import RestoreAccountState
from api.limits.admission import RunAdmission
from api.operations.audit import OperatorAuditStore
from api.operations.control.runs import RunTermination
from api.operations.schema import OperatorAction, OperatorOutcome
from api.operations.state import OperationControlStore


class RestoreQuarantine:
    def __init__(self, session: AsyncSession, actor: str) -> None:
        self._session = session
        self._actor = actor
        self._accounts = RestoreAccountState(session)

    async def apply(self) -> None:
        await RunAdmission(self._session).lock_transaction()
        await OperationControlStore(self._session).set_admissions_paused(True)
        await RunTermination(self._session).terminate_all()
        await self._accounts.quarantine_all()
        await AccountAccessStore(self._session).invalidate_all_credentials()
        OperatorAuditStore(self._session).record(
            self._actor, OperatorAction.STOP_ALL, None, OperatorOutcome.APPLIED
        )
        await self._session.commit()

    async def approve_account(self, user_id: UUID) -> None:
        await RunAdmission(self._session).lock_transaction()
        await self._accounts.approve_reconciled_account(user_id)
        OperatorAuditStore(self._session).record(
            self._actor, OperatorAction.RESUME_ACCOUNT, user_id, OperatorOutcome.APPLIED
        )
        await self._session.commit()
