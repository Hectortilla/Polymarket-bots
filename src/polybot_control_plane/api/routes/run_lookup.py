"""HTTP lookup boundary shared by run-owned routes."""

from typing import Never
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from polybot_control_plane.runs.contracts import RunRead
from polybot_control_plane.runs.store import RunStore


RUN_NOT_FOUND_DETAIL = "run not found"


def require_run(run: RunRead | None) -> RunRead:
    if run is None:
        raise_run_not_found()
    return run


def raise_run_not_found() -> Never:
    raise HTTPException(status.HTTP_404_NOT_FOUND, RUN_NOT_FOUND_DETAIL)


async def require_stored_run(session: AsyncSession, run_id: UUID) -> RunRead:
    return require_run(await RunStore(session).read(run_id))
