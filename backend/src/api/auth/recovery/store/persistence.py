"""Locked credential reads, eligibility validation and atomic row mutations."""

from datetime import timedelta
from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.auth.models import SessionRow, UserRow
from api.auth.recovery.contracts import AccountStatus
from api.auth.recovery.errors import InvalidAccountToken
from api.auth.recovery.models import AccountTokenRow
from api.auth.recovery.policy import TOKEN_LIFETIME_SECONDS, TokenPurpose
from api.auth.recovery.tokens import AccountToken
from api.auth.store import AuthStore
from api.auth.store.tokens import SessionToken


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
        if user is None:
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
        # expiry after waiting so concurrent redemption cannot reuse stale eligibility.
        user = await self.lock_user(user_id)
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

    async def lock_user(self, user_id: UUID) -> UserRow:
        return (
            await self._session.execute(
                select(UserRow).where(UserRow.id == user_id).with_for_update()
            )
        ).scalar_one()

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
        await self.delete_sessions(user.id)
        await self._session.execute(
            delete(AccountTokenRow).where(AccountTokenRow.user_id == user.id)
        )

    async def delete_sessions(
        self, user_id: UUID, *, keep_token: SessionToken | None = None
    ) -> None:
        query = delete(SessionRow).where(SessionRow.user_id == user_id)
        if keep_token is not None:
            query = query.where(SessionRow.token_digest != keep_token.digest)
        await self._session.execute(query)
