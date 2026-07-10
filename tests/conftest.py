from dataclasses import dataclass

import pytest

from bots.execution.broker import Broker
from bots.framework.config import BotConfig
from bots.framework.context import BotContext
from bots.framework.events import FillEvent, OrderRequest, OrderStatus
from bots.framework.events.books import BookSnapshot
from bots.framework.events.wallet_trades import WalletTradeEvent
from bots.polymarket.types import Market, Position


@dataclass(slots=True)
class DummyBroker(Broker):
    submitted: list[OrderRequest]

    async def submit(self, order: OrderRequest) -> FillEvent:
        self.submitted.append(order)
        return FillEvent(
            order_id="dummy",
            token_id=order.token_id,
            side=order.side,
            status=OrderStatus.ACCEPTED,
            requested_size=order.size,
            filled_size=order.size,
            average_price=order.price,
            fee_usdc=0,
            received_at_ms=0,
        )

    async def cancel_all(self) -> None:
        return None


@dataclass(slots=True)
class DummyMarkets:
    async def find_by_slug(self, slug: str) -> Market | None:
        return None


@dataclass(slots=True)
class DummyBooks:
    async def latest(self, token_id: str) -> BookSnapshot | None:
        return None


@dataclass(slots=True)
class DummyWalletActivity:
    async def latest_trades(
        self,
        wallet: str,
        limit: int,
    ) -> tuple[WalletTradeEvent, ...]:
        return ()


@dataclass(slots=True)
class DummyPositions:
    async def positions(self, wallet: str) -> list[Position]:
        return []


@pytest.fixture
def dummy_context() -> BotContext:
    return BotContext(
        config=BotConfig(name="test"),
        broker=DummyBroker(submitted=[]),
        markets=DummyMarkets(),
        books=DummyBooks(),
        wallet_activity=DummyWalletActivity(),
        positions=DummyPositions(),
    )
