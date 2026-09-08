"""Execute a decision preview using isolated, non-network framework services."""

from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.events import FillEvent, OrderRequest

from api.catalog.graphs.preview import (
    GraphPreviewRequest,
    GraphPreviewResponse,
)
from api.catalog.node_based.evaluator import GraphEvaluator


class PreviewClock:
    def __init__(self, now_ms: int) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms

    async def sleep(self, seconds: float) -> None:
        raise RuntimeError("Decision previews cannot wait or simulate fills")


class PreviewBroker:
    async def submit(self, order: OrderRequest) -> FillEvent:
        raise RuntimeError("Decision previews cannot submit orders")

    async def cancel_all(self) -> None:
        raise RuntimeError("Decision previews cannot cancel orders")


class RejectingPreviewData:
    async def latest(self, token_id: str):
        raise RuntimeError("Decision previews cannot fetch market data")

    async def find_by_slug(self, slug: str):
        raise RuntimeError("Decision previews cannot discover markets")

    async def latest_trades(self, wallet: str, limit: int):
        raise RuntimeError("Decision previews cannot read wallet activity")


async def preview_graph(request: GraphPreviewRequest) -> GraphPreviewResponse:
    rejecting_preview_data = RejectingPreviewData()
    ctx = BotContext(
        config=BotConfig(name="Decision preview"),
        broker=PreviewBroker(),
        markets=rejecting_preview_data,
        books=rejecting_preview_data,
        wallet_activity=rejecting_preview_data,
        portfolio=request.portfolio,
        clock=PreviewClock(request.now_ms),
    )
    result = await GraphEvaluator(request.graph, preview=True).evaluate_and_execute(
        request.hook_name, ctx, request.event
    )
    return GraphPreviewResponse(
        nodes=result.nodes, intended_orders=result.intended_orders
    )
