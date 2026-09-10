"""Create the explicitly enabled local account without replacing existing identity."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.models import UserRow
from api.auth.passwords import hash_password
from api.auth.schema import USERS_EMAIL_CONSTRAINT_NAME
from api.auth.store import AuthStore

DEVELOPMENT_EMAIL = "a@a.a"
DEVELOPMENT_PASSWORD = "a"


class DevelopmentAccountStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_account(self) -> None:
        if await AuthStore(self._session).find_user(DEVELOPMENT_EMAIL) is not None:
            return
        user = UserRow(
            email=DEVELOPMENT_EMAIL,
            password_hash=await hash_password(DEVELOPMENT_PASSWORD),
        )
        user.mark_email_verified()
        # Multiple API workers may start together; the email constraint owns the race.
        await self._session.execute(
            insert(UserRow)
            .values(**user.model_dump())
            .on_conflict_do_nothing(constraint=USERS_EMAIL_CONSTRAINT_NAME)
        )
        await self._session.commit()
