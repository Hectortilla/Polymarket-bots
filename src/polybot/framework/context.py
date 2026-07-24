from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from polybot.execution.broker import Broker
from polybot.framework.activity import ActivitySink, NullActivitySink
from polybot.framework.clock import Clock, SystemClock
from polybot.framework.config.models import BotConfig
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.markets import Market
from polybot.polymarket.positions.contracts import Position


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
    activity: ActivitySink = field(default_factory=NullActivitySink)
    clock: Clock = field(default_factory=SystemClock)
    rng: random.Random = field(default_factory=random.Random)

    def is_book_current(self, book: BookSnapshot) -> bool:
        """Recheck a book after awaited work before using it for a decision."""
        return (
            book.validation_issue(
                self.clock.now_ms(),
                self.config.event_max_age_ms,
            )
            is None
        )
