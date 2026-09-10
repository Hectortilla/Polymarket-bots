"""Commit a conditional terminal transition and its durable event together."""

from sqlalchemy.ext.asyncio import AsyncSession

from api.events.contracts import RunLifecycleEvent
from api.events.ids import require_persisted_event_id
from api.events.models import EventRow
from api.runs.models import RunRow


class TerminalRunWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self, row: RunRow) -> int:
        try:
            event_id = await self.stage(row)
            await self._session.commit()
            return event_id
        except BaseException:
            await self._session.rollback()
            raise

    async def stage(self, row: RunRow) -> int:
        """Stage the shared terminal event inside a larger atomic transaction."""
        event = RunLifecycleEvent.from_terminal_status(
            row.id,
            row.status,
            occurred_at=row.ended_at,
        )
        event_row = EventRow.from_event(event)
        self._session.add(event_row)
        await self._session.flush()
        event_id = require_persisted_event_id(event_row.id)
        return event_id
