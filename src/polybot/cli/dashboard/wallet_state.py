"""Dashboard-only projection helpers for followed-wallet activity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.events import Side
from polybot.framework.events.wallet_trades import WalletTradeEvent

from .token_labels import format_token_label


@dataclass(slots=True)
class WalletTimelineEvent:
    source_key: str
    wallet: str
    trade_timestamp_ms: int
    side: Side
    notional: Decimal
    market_label: str
    accepted: bool | None = None


def wallet_market_label(trade: WalletTradeEvent) -> str:
    if trade.market_slug and trade.outcome:
        return f"{trade.market_slug} · {trade.outcome}"
    return trade.market_slug or trade.outcome or format_token_label(trade.token_id)
