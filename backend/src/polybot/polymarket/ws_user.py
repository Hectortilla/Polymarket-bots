from __future__ import annotations

from collections.abc import AsyncIterator

from polybot.framework.events import FillEvent


class UserStream:
    async def fills(self) -> AsyncIterator[FillEvent]:
        raise NotImplementedError("Implement authenticated CLOB user WebSocket.")
        yield
