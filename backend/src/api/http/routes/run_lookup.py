"""HTTP lookup boundary shared by run-owned routes."""

from typing import Never
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.runs.contracts import RunRead
from api.runs.store import RunStore

RUN_NOT_FOUND_DETAIL = "run not found"


async def require_stored_run(
    session: AsyncSession, run_id: UUID, owner_user_id: UUID
) -> RunRead:
    return require_run(await RunStore(session).read_owned(run_id, owner_user_id))


def require_run(run: RunRead | None) -> RunRead:
    if run is None:
        raise_run_not_found()
    return run


def raise_run_not_found() -> Never:
    raise HTTPException(status.HTTP_404_NOT_FOUND, RUN_NOT_FOUND_DETAIL)
