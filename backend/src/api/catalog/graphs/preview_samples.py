"""Editable, synthetic framework event samples for the decision preview form."""

from decimal import Decimal
from pydantic import TypeAdapter
from polybot.framework.base import BaseBot
from polybot.framework.events import FillEvent, OrderStatus, Side
from polybot.framework.events.books import (
    BookSnapshot,
    BookLevel,
    BookGapEvent,
    BookGapReason,
)
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.portfolio import PortfolioPosition

PREVIEW_SAMPLE_TIME_MS = 1000
PREVIEW_SAMPLE_TOKEN_ID = "example-token"
PREVIEW_SAMPLE_POSITIONS = (
    PortfolioPosition(
        token_id=PREVIEW_SAMPLE_TOKEN_ID,
        size=Decimal("2"),
        average_entry_price=Decimal("0.4"),
    ),
)


def sample_payload(hook_name: str) -> dict | None:
    samples = {
        BaseBot.on_market_resolved.__name__: MarketResolutionEvent(
            condition_id="example-condition",
            market_slug="example-market",
            token_ids=(PREVIEW_SAMPLE_TOKEN_ID, "other-token"),
            winning_token_id=PREVIEW_SAMPLE_TOKEN_ID,
            winning_outcome="Up",
            resolved_at_ms=PREVIEW_SAMPLE_TIME_MS,
            source="preview",
        ),
        BaseBot.on_book.__name__: BookSnapshot(
            token_id=PREVIEW_SAMPLE_TOKEN_ID,
            bids=(BookLevel(price=Decimal("0.39"), size=Decimal("100")),),
            asks=(BookLevel(price=Decimal("0.40"), size=Decimal("100")),),
            received_at_ms=PREVIEW_SAMPLE_TIME_MS,
        ),
        BaseBot.on_book_gap.__name__: BookGapEvent(
            condition_id=None,
            observed_at_ms=PREVIEW_SAMPLE_TIME_MS,
            reason=BookGapReason.BOOK_STREAM_GAP,
        ),
        BaseBot.on_fill.__name__: FillEvent(
            order_id="example-order",
            token_id=PREVIEW_SAMPLE_TOKEN_ID,
            side=Side.BUY,
            status=OrderStatus.FILLED,
            requested_size=Decimal("1"),
            filled_size=Decimal("1"),
            average_price=Decimal("0.4"),
            fee_usdc=Decimal("0"),
            received_at_ms=PREVIEW_SAMPLE_TIME_MS,
        ),
        BaseBot.on_wallet_trade.__name__: WalletTradeEvent(
            wallet="0x0000000000000000000000000000000000000001",
            condition_id="example-condition",
            token_id=PREVIEW_SAMPLE_TOKEN_ID,
            side=Side.BUY,
            price=Decimal("0.4"),
            size=Decimal("1"),
            source_id="example-trade",
            trade_timestamp_ms=PREVIEW_SAMPLE_TIME_MS,
            observed_at_ms=PREVIEW_SAMPLE_TIME_MS,
        ),
    }
    event = samples.get(hook_name)
    return (
        TypeAdapter(type(event)).dump_python(event, mode="json")
        if event is not None
        else None
    )
