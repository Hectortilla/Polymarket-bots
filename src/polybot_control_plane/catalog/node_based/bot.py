"""Concrete paper bot for immutable node graphs."""

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events import FillEvent
from polybot.framework.events.books import BookGapEvent, BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.catalog.graphs.types import GraphHookName
from polybot_control_plane.catalog.node_based.evaluator import GraphEvaluator


class NodeBasedBot(BaseBot):
    def __init__(self, graph: NodeGraph) -> None:
        self._evaluator = GraphEvaluator(graph)

    async def on_start(self, ctx: BotContext) -> None:
        await self._process_event(BaseBot.on_start.__name__, ctx)

    async def on_book(
        self,
        ctx: BotContext,
        book: BookSnapshot,
    ) -> DispatchSkipReason | None:
        await self._process_event(BaseBot.on_book.__name__, ctx, book)
        return None

    async def on_book_gap(self, ctx: BotContext, gap: BookGapEvent) -> None:
        await self._process_event(BaseBot.on_book_gap.__name__, ctx, gap)

    async def on_wallet_trade(
        self,
        ctx: BotContext,
        trade: WalletTradeEvent,
    ) -> None:
        await self._process_event(BaseBot.on_wallet_trade.__name__, ctx, trade)

    async def on_fill(self, ctx: BotContext, fill: FillEvent) -> None:
        await self._process_event(BaseBot.on_fill.__name__, ctx, fill)

    async def on_market_resolved(
        self,
        ctx: BotContext,
        event: MarketResolutionEvent,
    ) -> None:
        await self._process_event(BaseBot.on_market_resolved.__name__, ctx, event)

    async def on_stop(self, ctx: BotContext) -> None:
        await self._process_event(BaseBot.on_stop.__name__, ctx)

    async def _process_event(
        self,
        hook_name: GraphHookName,
        ctx: BotContext,
        payload: object | None = None,
    ) -> None:
        await self._evaluator.evaluate_and_execute(hook_name, ctx, payload)
