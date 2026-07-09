from __future__ import annotations

from typing import Protocol

from bots.framework.events import FillEvent, OrderRequest


class Broker(Protocol):
    async def submit(self, order: OrderRequest) -> FillEvent: ...

    async def cancel_all(self) -> None: ...
