"""Bound private SSE delivery after session expiry or revocation."""

from time import monotonic
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.policy import SESSION_RECHECK_SECONDS
from api.auth.store import AuthStore
from api.auth.store.tokens import SessionToken


class StreamAuthorization:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        token: SessionToken,
        user_id: UUID,
    ) -> None:
        self._session_factory = session_factory
        self._token = token
        self._user_id = user_id
        self._next_session_recheck_at = 0.0

    async def allowed(self) -> bool:
        now = monotonic()
        # Bound revocation latency without querying PostgreSQL for every frame.
        if now < self._next_session_recheck_at:
            return True
        async with self._session_factory() as session:
            user = await AuthStore(session).current_user(self._token)
        if user is None or user.id != self._user_id:
            return False
        self._next_session_recheck_at = now + SESSION_RECHECK_SECONDS
        return True
