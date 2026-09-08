"""Editable, synthetic framework event samples for the decision preview form."""

from decimal import Decimal
from pydantic import TypeAdapter
from polybot.framework.events import FillEvent, OrderStatus, Side
from polybot.framework.events.books import (
    BookSnapshot,
    BookLevel,
    BookGapEvent,
    BookGapReason,
)
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent

PREVIEW_SAMPLE_TIME_MS = 1000


def sample_payload(hook_name: str) -> dict | None:
    samples = {
        "on_market_resolved": MarketResolutionEvent(
            "example-condition",
            "example-market",
            ("example-token", "other-token"),
            "example-token",
            "Up",
            PREVIEW_SAMPLE_TIME_MS,
            "preview",
        ),
        "on_book": BookSnapshot(
            "example-token",
            (BookLevel(Decimal("0.39"), Decimal("100")),),
            (BookLevel(Decimal("0.40"), Decimal("100")),),
            PREVIEW_SAMPLE_TIME_MS,
        ),
        "on_book_gap": BookGapEvent(
            None, PREVIEW_SAMPLE_TIME_MS, BookGapReason.BOOK_STREAM_GAP
        ),
        "on_fill": FillEvent(
            "example-order",
            "example-token",
            Side.BUY,
            OrderStatus.FILLED,
            Decimal("1"),
            Decimal("1"),
            Decimal("0.4"),
            Decimal("0"),
            PREVIEW_SAMPLE_TIME_MS,
        ),
        "on_wallet_trade": WalletTradeEvent(
            wallet="0x0000000000000000000000000000000000000001",
            condition_id="example-condition",
            token_id="example-token",
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
