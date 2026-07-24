from dataclasses import dataclass
from decimal import Decimal

import pytest

from polybot.execution.broker import Broker
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
)
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.markets import Market
from polybot.polymarket.positions.contracts import Position


@dataclass(slots=True)
class DummyBroker(Broker):
    submitted: list[OrderRequest]

    async def submit(self, order: OrderRequest) -> FillEvent:
        self.submitted.append(order)
        if order.size <= 0:
            return FillEvent.rejected(
                order_id="dummy",
                token_id=order.token_id,
                side=order.side,
                requested_size=order.size,
                received_at_ms=0,
                reject_reason=FillRejectReason.BAD_SIZE,
                reject_message="order size must be positive",
            )
        return FillEvent(
            order_id="dummy",
            token_id=order.token_id,
            side=order.side,
            status=OrderStatus.FILLED,
            requested_size=order.size,
            filled_size=order.size,
            average_price=order.price,
            fee_usdc=Decimal("0"),
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
