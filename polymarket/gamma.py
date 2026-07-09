from __future__ import annotations

from bots.polymarket.types import Market


class GammaClient:
    async def find_by_slug(self, slug: str) -> Market | None:
        raise NotImplementedError("Implement public Gamma market lookup.")
