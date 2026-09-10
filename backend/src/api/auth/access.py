"""Account access state and credential invalidation under the account lock."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.models import SessionRow, UserRow
from api.auth.recovery.models import AccountTokenRow
from api.auth.store.tokens import SessionToken


class AccountAccessStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def require_locked_account(self, owner_user_id: UUID) -> UserRow:
        account = await self.lock_account(owner_user_id)
        if account is None:
            raise NoResultFound("account is no longer available")
        return account

    async def lock_account(self, owner_user_id: UUID) -> UserRow | None:
        return await self._session.scalar(
            select(UserRow).where(UserRow.id == owner_user_id).with_for_update()
        )

    async def invalidate_credentials(self, owner_user_id: UUID) -> None:
        await self.delete_sessions(owner_user_id)
        await self._session.execute(
            delete(AccountTokenRow).where(AccountTokenRow.user_id == owner_user_id)
        )

    async def invalidate_all_credentials(self) -> None:
        await self._session.execute(delete(SessionRow))
        await self._session.execute(delete(AccountTokenRow))

    async def delete_sessions(
        self, owner_user_id: UUID, *, keep_token: SessionToken | None = None
    ) -> None:
        query = delete(SessionRow).where(SessionRow.user_id == owner_user_id)
        if keep_token is not None:
            query = query.where(SessionRow.token_digest != keep_token.digest)
        await self._session.execute(query)
