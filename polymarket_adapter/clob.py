from __future__ import annotations

from bots.framework.events.books import BookSnapshot


class ClobClient:
    async def latest(self, token_id: str) -> BookSnapshot | None:
        raise NotImplementedError("Implement public CLOB book lookup or cache read.")
