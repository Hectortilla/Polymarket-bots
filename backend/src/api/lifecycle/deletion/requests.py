"""Minimal durable deletion receipts and the account-reopening fence."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.lifecycle.deletion.models import DeletionRequestRow


class DeletionRequests:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, user_id: UUID) -> None:
        if await self._session.get(DeletionRequestRow, user_id) is None:
            self._session.add(DeletionRequestRow(user_id=user_id))

    async def require_no_request(self, user_id: UUID) -> None:
        if await self._session.get(DeletionRequestRow, user_id) is not None:
            raise ValueError("account deletion prevents reopening access")
