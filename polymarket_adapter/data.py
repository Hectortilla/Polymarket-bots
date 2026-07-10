from __future__ import annotations

from bots.polymarket.types import Position


class DataClient:
    async def positions(self, wallet: str) -> list[Position]:
        raise NotImplementedError("Implement public Data API positions lookup.")
