"""Identity persistence and digest-only session lookup."""

from datetime import timedelta

from polybot.framework.clock import system_now_utc
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.auth.contracts import CurrentUser
from api.auth.models import SessionRow, UserRow
from api.auth.policy import SESSION_LIFETIME_SECONDS
from api.auth.store.errors import RegistrationConflictError
from api.auth.store.tokens import SessionToken


class AuthStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_user(self, email: str, *, lock: bool = False) -> UserRow | None:
        query = select(UserRow).where(UserRow.email == email)
        if lock:
            query = query.with_for_update()
        return (await self._session.execute(query)).scalar_one_or_none()

    async def register(self, email: str, password_hash: str) -> UserRow:
        user = UserRow(email=email, password_hash=password_hash)
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError as error:
            if RegistrationConflictError.matches(error):
                raise RegistrationConflictError from None
            raise
        return user

    async def issue_session(
        self, user: UserRow, old_token: SessionToken | None
    ) -> SessionToken:
        await self.revoke(old_token)
        token = SessionToken.issue()
        self._session.add(
            SessionRow(
                token_digest=token.digest,
                user_id=user.id,
                expires_at=system_now_utc()
                + timedelta(seconds=SESSION_LIFETIME_SECONDS),
            )
        )
        await self._session.commit()
        return token

    async def current_user(self, token: SessionToken) -> CurrentUser | None:
        row = (
            await self._session.execute(
                select(UserRow)
                .join(SessionRow, SessionRow.user_id == UserRow.id)
                .where(
                    SessionRow.token_digest == token.digest,
                    UserRow.access_allowed,
                    SessionRow.expires_at > system_now_utc(),
                )
            )
        ).scalar_one_or_none()
        return None if row is None else CurrentUser.from_model(row)

    async def revoke(self, token: SessionToken | None) -> None:
        if token is not None:
            await self._session.execute(
                delete(SessionRow).where(SessionRow.token_digest == token.digest)
            )
