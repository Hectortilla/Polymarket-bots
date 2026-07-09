from __future__ import annotations

from collections.abc import AsyncIterator

from bots.framework.events import BookSnapshot


class MarketStream:
    async def books(self, token_ids: set[str]) -> AsyncIterator[BookSnapshot]:
        raise NotImplementedError("Implement CLOB market WebSocket subscription.")
        yield
