"""Small shared contracts for terminal and browser dashboard projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.framework.events import Side
    from polybot.performance.contracts.valuation_status import ValuationStatus


MAX_CHART_HISTORY_POINTS = 720
MAX_CHART_TOKENS = 20
MAX_WALLET_TIMELINE_EVENTS = 5_000
CHART_SAMPLE_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class MarketChartPoint:
    token_id: str
    label: str
    value: Decimal | None
    status: ValuationStatus
    markers: tuple[Side, ...]


@dataclass(frozen=True, slots=True)
class EquityChartPoint:
    value: Decimal | None
    status: ValuationStatus


@dataclass(frozen=True, slots=True)
class WalletChartPoint:
    source_key: str
    wallet: str
    trade_timestamp_ms: int
    side: Side
    notional: Decimal
    market_label: str
    accepted: bool | None


@dataclass(frozen=True, slots=True)
class DashboardSample:
    sampled_at_ms: int
    markets: tuple[MarketChartPoint, ...]
    equity: EquityChartPoint


def format_token_label(token_id: str) -> str:
    return token_id if len(token_id) <= 12 else f"{token_id[:7]}…{token_id[-4:]}"


def format_market_label(
    token_id: str,
    market_slug: str | None = None,
    outcome: str | None = None,
) -> str:
    if market_slug and outcome:
        return f"{market_slug} · {outcome}"
    return market_slug or outcome or format_token_label(token_id)
