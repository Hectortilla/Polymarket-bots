"""Locked credential reads, eligibility validation and atomic row mutations."""

from datetime import timedelta
from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.auth.access import AccountAccessStore
from api.auth.models import UserRow
from api.auth.recovery.contracts import AccountStatus
from api.auth.recovery.errors import InvalidAccountToken
from api.auth.recovery.models import AccountTokenRow
from api.auth.recovery.policy import TOKEN_LIFETIME_SECONDS, TokenPurpose
from api.auth.recovery.tokens import AccountToken
from api.auth.store import AuthStore


class CredentialRows:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def status(self, user_id: UUID) -> AccountStatus:
        user = (
            await self._session.execute(select(UserRow).where(UserRow.id == user_id))
        ).scalar_one()
        return AccountStatus.from_model(user)

    async def eligible_link_user(
        self, email: str, purpose: TokenPurpose
    ) -> UserRow | None:
        user = await AuthStore(self._session).find_user(email, lock=True)
        if user is None or not user.access_allowed:
            return None
        if purpose.verifies_email and user.email_verified_at is not None:
            return None
        return user

    async def lock_redeemable_user(
        self, account_token: AccountToken, purpose: TokenPurpose
    ) -> UserRow:
        user_id = await self._session.scalar(
            select(AccountTokenRow.user_id).where(
                AccountTokenRow.token_digest == account_token.digest,
                AccountTokenRow.purpose == purpose,
            )
        )
        if user_id is None:
            raise InvalidAccountToken
        # Every credential workflow locks user before token/session rows. Recheck
        # expiry and suspension after waiting so redemption cannot reuse stale eligibility.
        user = await AccountAccessStore(self._session).require_locked_account(user_id)
        if not user.access_allowed:
            raise InvalidAccountToken
        token_row = (
            await self._session.execute(
                select(AccountTokenRow)
                .where(
                    AccountTokenRow.token_digest == account_token.digest,
                    AccountTokenRow.purpose == purpose,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if token_row is None or token_row.expires_at <= system_now_utc():
            raise InvalidAccountToken
        return user

    async def replace_link(
        self, user: UserRow, purpose: TokenPurpose, account_token: AccountToken
    ) -> None:
        await self._session.execute(
            delete(AccountTokenRow).where(
                AccountTokenRow.user_id == user.id,
                AccountTokenRow.purpose == purpose,
            )
        )
        self._session.add(
            AccountTokenRow(
                token_digest=account_token.digest,
                user_id=user.id,
                purpose=purpose,
                expires_at=system_now_utc() + timedelta(seconds=TOKEN_LIFETIME_SECONDS),
            )
        )

    async def replace_password(self, user: UserRow, password_hash: str) -> None:
        user.password_hash = password_hash
        self._session.add(user)
        await AccountAccessStore(self._session).invalidate_credentials(user.id)
