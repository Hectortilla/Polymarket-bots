"""Read-only market-target planning for recorder runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from polybot.execution.broker import Broker
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BookClient, BotContext, MarketClient
from polybot.framework.events import FillEvent, OrderRequest
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.streams import StreamPlan, StreamRelation, StreamRule


ORDERING_DISABLED_MESSAGE = "the recording planner cannot submit or cancel orders"
WALLET_ACTIVITY_DISABLED_MESSAGE = (
    "the market-only recording planner cannot query wallet activity"
)


class StreamPlanProvider(Protocol):
    async def plan(self, now_ms: int) -> StreamPlan: ...


class RejectingRecordingBroker(Broker):
    async def submit(self, order: OrderRequest) -> FillEvent:
        raise RuntimeError(ORDERING_DISABLED_MESSAGE)

    async def cancel_all(self) -> None:
        raise RuntimeError(ORDERING_DISABLED_MESSAGE)


class RejectingRecordingWalletActivityClient:
    async def latest_trades(
        self,
        wallet: str,
        limit: int,
    ) -> tuple[WalletTradeEvent, ...]:
        raise RuntimeError(WALLET_ACTIVITY_DISABLED_MESSAGE)


@dataclass(frozen=True, slots=True)
class BotStreamPlanProvider:
    bot: BaseBot
    context: BotContext

    async def plan(self, now_ms: int) -> StreamPlan:
        return StreamPlan(
            current=await self.bot.current_stream_rules(self.context, now_ms),
            next=await self.bot.next_stream_rules(self.context, now_ms),
        )


@dataclass(frozen=True, slots=True)
class StaticStreamPlanProvider:
    market_slugs: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = tuple(
            dict.fromkeys(
                slug.strip() for slug in self.market_slugs if slug.strip()
            )
        )
        if not normalized:
            raise ValueError("at least one market slug is required")
        if normalized != self.market_slugs:
            object.__setattr__(self, "market_slugs", normalized)

    async def plan(self, now_ms: int) -> StreamPlan:
        return StreamPlan(
            current=(
                StreamRule(
                    relation=StreamRelation.INDEPENDENT,
                    market_slugs=self.market_slugs,
                ),
            )
        )


def planning_context(
    config: BotConfig,
    *,
    markets: MarketClient,
    books: BookClient,
) -> BotContext:
    return BotContext(
        config=config,
        broker=RejectingRecordingBroker(),
        markets=markets,
        books=books,
        wallet_activity=RejectingRecordingWalletActivityClient(),
    )
