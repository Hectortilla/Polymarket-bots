"""Small shared contracts for terminal and browser dashboard projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.framework.events import Side
    from polybot.performance.contracts.valuation_status import ValuationStatus


class BucketRounding(StrEnum):
    FLOOR = "floor"


MAX_CHART_HISTORY_POINTS = 720
MAX_CHART_TOKENS = 20
MAX_WALLET_TIMELINE_EVENTS = 5_000
CHART_SAMPLE_INTERVAL_SECONDS = 0.25
MIN_TIME_ZOOM_LEVEL = -3
MAX_TIME_ZOOM_LEVEL = 3
INITIAL_TIME_ZOOM_LEVEL = 0
TIME_ZOOM_FACTOR = 2
CHART_WINDOW_ROUNDING = BucketRounding.FLOOR
CHART_WINDOW_CLAMP_MINIMUM = True
CHART_WINDOW_CLAMP_MAXIMUM = True
WALLET_NOTIONAL_TIER_UPPER_NUMERATORS = (1, 2)
WALLET_NOTIONAL_TIER_DENOMINATOR = 3
WALLET_NOTIONAL_TIER_COUNT = len(WALLET_NOTIONAL_TIER_UPPER_NUMERATORS) + 1
FIRST_WALLET_NOTIONAL_TIER = 1
NONPOSITIVE_MAX_NOTIONAL_THRESHOLD = Decimal("0")
WALLET_BUCKET_ROUNDING = BucketRounding.FLOOR
WALLET_BUCKET_CLAMP_TO_LAST_COLUMN = True
WALLET_NOTIONAL_TIER_UPPER_BOUND_INCLUSIVE = True
TOKEN_LABEL_MAXIMUM_LENGTH = 12
TOKEN_LABEL_PREFIX_LENGTH = 7
TOKEN_LABEL_SUFFIX_LENGTH = 4
TOKEN_LABEL_ELLIPSIS = "…"
MARKET_LABEL_PART_SEPARATOR = " · "


class DashboardKey(StrEnum):
    CLOSER = "z"
    WIDER = "x"
    RESET = "r"
    VIEW = "v"
    NEXT_WALLET_PAGE = "j"
    PREVIOUS_WALLET_PAGE = "k"


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
    return (
        token_id
        if len(token_id) <= TOKEN_LABEL_MAXIMUM_LENGTH
        else (
            f"{token_id[:TOKEN_LABEL_PREFIX_LENGTH]}{TOKEN_LABEL_ELLIPSIS}"
            f"{token_id[-TOKEN_LABEL_SUFFIX_LENGTH:]}"
        )
    )


def format_market_label(
    token_id: str,
    market_slug: str | None = None,
    outcome: str | None = None,
) -> str:
    if market_slug and outcome:
        return f"{market_slug}{MARKET_LABEL_PART_SEPARATOR}{outcome}"
    return market_slug or outcome or format_token_label(token_id)


def scaled_chart_window_points(
    base_points: int,
    zoom_level: int,
    minimum_points: int,
    maximum_points: int,
) -> int:
    if CHART_WINDOW_ROUNDING is not BucketRounding.FLOOR:
        raise ValueError("unsupported chart-window rounding policy")
    scaled = base_points * (TIME_ZOOM_FACTOR**zoom_level)
    points = int(scaled // 1)
    if CHART_WINDOW_CLAMP_MINIMUM:
        points = max(minimum_points, points)
    if CHART_WINDOW_CLAMP_MAXIMUM:
        points = min(maximum_points, points)
    return points
