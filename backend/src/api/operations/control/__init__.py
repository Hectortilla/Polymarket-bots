"""Atomic operator orchestration over account, incident, run and audit owners."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.limits.admission import RunAdmission
from api.operations.audit import OperatorAuditStore
from api.operations.control.accounts import AccountControls
from api.operations.control.runs import RunTermination
from api.operations.schema import OperatorAction, OperatorOutcome
from api.operations.state import OperationControlStore


class OperatorControl:
    def __init__(self, session: AsyncSession, actor: str) -> None:
        self._session = session
        self._actor = actor
        self._accounts = AccountControls(session)
        self._runs = RunTermination(session)
        self._global = OperationControlStore(session)
        self._audit = OperatorAuditStore(session)

    async def apply(
        self, action: OperatorAction, target: UUID | None = None
    ) -> OperatorOutcome:
        # Exhaustive command dispatch fails before mutation for an unknown action.
        handler = {
            OperatorAction.SUSPEND: self._suspend,
            OperatorAction.RESUME_ACCOUNT: self._accounts.resume,
            OperatorAction.STOP_RUN: self._runs.terminate_run,
            OperatorAction.STOP_ALL: self._stop_all,
            OperatorAction.RESUME_ADMISSIONS: self._resume_admissions,
        }[action]
        # Serialize with launch, claim and terminal release so incident controls
        # cannot race new work into the account after revoking access.
        await RunAdmission(self._session).lock_transaction()
        outcome = await handler(target)
        self._audit.record(self._actor, action, target, outcome)
        await self._session.commit()
        return outcome

    async def _suspend(self, owner_user_id: UUID) -> OperatorOutcome:
        outcome = await self._accounts.suspend(owner_user_id)
        if outcome is not OperatorOutcome.NOT_FOUND:
            await self._runs.terminate_account(owner_user_id)
        return outcome

    async def _stop_all(self, _target: None) -> OperatorOutcome:
        outcome = await self._global.set_admissions_paused(True)
        await self._runs.terminate_all()
        return outcome

    async def _resume_admissions(self, _target: None) -> OperatorOutcome:
        return await self._global.set_admissions_paused(False)
