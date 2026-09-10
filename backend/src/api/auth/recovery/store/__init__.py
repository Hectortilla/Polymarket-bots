"""Credential workflows over one user-serialized PostgreSQL transaction."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.access import AccountAccessStore
from api.auth.models import UserRow
from api.auth.passwords import verify_password
from api.auth.recovery.errors import ReauthenticationFailed
from api.auth.recovery.policy import SessionRevocation, TokenPurpose
from api.auth.recovery.store.persistence import CredentialRows
from api.auth.recovery.tokens import AccountToken
from api.auth.store import AuthStore
from api.auth.store.tokens import SessionToken


class AccountCredentialStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rows = CredentialRows(session)

    async def issue_link(self, email: str, purpose: TokenPurpose) -> AccountToken:
        # Return an indistinguishable token for the HTTP mail flow to mitigate
        # account discovery; only eligible users receive a redeemable digest.
        account_token = AccountToken.issue()
        eligible_user = await self._rows.eligible_link_user(email, purpose)
        if eligible_user is not None:
            await self._rows.replace_link(eligible_user, purpose, account_token)
        await self._session.commit()
        return account_token

    async def redeem(
        self, account_token: AccountToken, purpose: TokenPurpose, password_hash: str
    ) -> None:
        user = await self._rows.lock_redeemable_user(account_token, purpose)
        if purpose.verifies_email:
            user.mark_email_verified()
        await self._rows.replace_password(user, password_hash)
        # Credential replacement, proof and revocation either all commit or all roll back.
        await self._session.commit()

    async def change_password(
        self,
        user_id: UUID,
        session_token: SessionToken,
        current_password: str,
        password_hash: str,
    ) -> None:
        user = await self.reauthenticate(user_id, session_token, current_password)
        await self._rows.replace_password(user, password_hash)
        await self._session.commit()

    async def revoke_sessions(
        self,
        user_id: UUID,
        session_token: SessionToken,
        current_password: str,
        scope: SessionRevocation,
    ) -> None:
        await self.reauthenticate(user_id, session_token, current_password)
        keep_token = None if scope.revokes_current else session_token
        await AccountAccessStore(self._session).delete_sessions(user_id, keep_token=keep_token)
        await self._session.commit()

    async def reauthenticate(
        self, user_id: UUID, session_token: SessionToken, current_password: str
    ) -> UserRow:
        user = await AccountAccessStore(self._session).require_locked_account(user_id)
        current_user = await AuthStore(self._session).current_user(session_token)
        if current_user is None or current_user.id != user_id:
            raise ReauthenticationFailed
        if not await verify_password(user.password_hash, current_password):
            raise ReauthenticationFailed
        return user
