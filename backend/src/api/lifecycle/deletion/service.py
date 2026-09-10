"""Self-deletion quiesces account access and paper work in one transaction."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.recovery.store import AccountCredentialStore
from api.auth.store.tokens import SessionToken
from api.lifecycle.deletion.requests import DeletionRequests
from api.limits.admission import RunAdmission
from api.operations.control.accounts import AccountControls
from api.operations.control.runs import RunTermination


class AccountDeletion:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request(self, user_id: UUID, token: SessionToken, password: str) -> None:
        # Keep the same admission -> account -> run lock order as operator controls.
        await RunAdmission(self._session).lock_transaction()
        await AccountCredentialStore(self._session).reauthenticate(
            user_id, token, password
        )
        await AccountControls(self._session).suspend(user_id)
        await RunTermination(self._session).terminate_account(user_id)
        await DeletionRequests(self._session).record(user_id)
        await self._session.commit()
