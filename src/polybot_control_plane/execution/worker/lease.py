"""Fail-closed reconciliation for an expired owned-run lease."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot_control_plane.events.contracts import RunLifecycleEvent
from polybot_control_plane.events.writer import RunEventWriter
from polybot_control_plane.runs.status import RunStatus
from polybot_control_plane.runs.store import RunStore


async def reconcile_expired_run(
    run_id: UUID,
    *,
    expired_before: datetime,
    now: datetime,
    session_factory: async_sessionmaker[AsyncSession],
    event_writer: RunEventWriter,
) -> bool:
    """Interrupt one expired owner exactly once without relaunching it."""

    async with session_factory() as session:
        interrupted = await RunStore(session).interrupt_expired(
            run_id,
            expired_before=expired_before,
            now=now,
        )
    if not interrupted:
        return False
    await event_writer.append(
        RunLifecycleEvent.from_terminal_status(
            run_id,
            RunStatus.INTERRUPTED,
            occurred_at=now,
        )
    )
    return True
