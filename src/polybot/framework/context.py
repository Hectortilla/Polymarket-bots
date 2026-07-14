from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from polybot.execution.broker import Broker
from polybot.framework.config.models import BotConfig
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.types import Market, Position


class MarketClient(Protocol):
    async def find_by_slug(self, slug: str) -> Market | None: ...


class BookClient(Protocol):
    async def latest(self, token_id: str) -> BookSnapshot | None: ...


class WalletActivityClient(Protocol):
    async def latest_trades(
        self,
        wallet: str,
        limit: int,
    ) -> tuple[WalletTradeEvent, ...]: ...


class PositionClient(Protocol):
    async def positions(self, wallet: str) -> list[Position]: ...


@dataclass(frozen=True, slots=True)
class BotContext:
    config: BotConfig
    broker: Broker
    markets: MarketClient
    books: BookClient
    wallet_activity: WalletActivityClient
    positions: PositionClient | None = None
