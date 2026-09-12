"""Wallet metric orchestration."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from polybot.polymarket.wallet_reports.contracts import (
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    ActivityRow,
    ActivityType,
    PositionRow,
)
from polybot.polymarket.wallet_reports.fields import (
    ACTIVITY_TRUNCATED_FIELD,
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
)

from .cash_metrics import fee_paid, signed_cash
from .contracts import (
    ACTIVITY_COUNT_METRIC,
    ACTIVITY_METRIC,
    ACTIVITY_SPAN_HOURS_METRIC,
    FEES_METRIC,
    GROSS_BEFORE_FEES_METRIC,
    HEDGE_AVERAGE_METRIC,
    MARKET_COUNT_METRIC,
    NET_CASH_METRIC,
    PNL_SIGNIFICANCE_THRESHOLD,
    TRADE_COUNT_METRIC,
    VOLUME_METRIC,
    MarketMetrics,
    WalletMetrics,
)
from .market_metrics import weighted_hedge_score

OPEN_POSITION_SIZE_THRESHOLD = 1.0


@dataclass(slots=True)
class _ActivityAggregate:
    trades: list[ActivityRow]
    activity_timestamps_seconds: list[int]
    cash_by_type: defaultdict[ActivityType, float]
    count_by_type: defaultdict[ActivityType, int]
    metrics_by_market: defaultdict[str, MarketMetrics]
    net_cash_flow_usdc: float


def compute_metrics(
    activity: list[ActivityRow],
    positions: list[PositionRow],
    truncated: bool = False,
) -> WalletMetrics:
    aggregate = _aggregate_activity(activity)
    resolved, open_markets = _classify_market_states(aggregate.metrics_by_market)
    traded_volume_usdc = sum(row[ACTIVITY_USDC_SIZE_FIELD] for row in aggregate.trades)
    fees = sum(fee_paid(row) for row in aggregate.trades)
    open_value = sum(position[POSITION_CURRENT_VALUE_FIELD] for position in positions)
    span_hours = _activity_span_hours(aggregate.activity_timestamps_seconds)
    return {
        ACTIVITY_COUNT_METRIC: len(activity),
        TRADE_COUNT_METRIC: len(aggregate.trades),
        "first_activity_at": _activity_timestamp_seconds_as_datetime(
            aggregate.activity_timestamps_seconds, min
        ),
        "last_activity_at": _activity_timestamp_seconds_as_datetime(
            aggregate.activity_timestamps_seconds, max
        ),
        ACTIVITY_SPAN_HOURS_METRIC: span_hours,
        MARKET_COUNT_METRIC: len(aggregate.metrics_by_market),
        "n_resolved": len(resolved),
        "n_open": len(open_markets),
        "cash_by_activity_type": dict(aggregate.cash_by_type),
        "count_by_activity_type": dict(aggregate.count_by_type),
        NET_CASH_METRIC: aggregate.net_cash_flow_usdc,
        VOLUME_METRIC: traded_volume_usdc,
        FEES_METRIC: fees,
        GROSS_BEFORE_FEES_METRIC: aggregate.net_cash_flow_usdc + fees,
        "rewards": aggregate.cash_by_type.get(ActivityType.REWARD, 0.0),
        HEDGE_AVERAGE_METRIC: weighted_hedge_score(
            aggregate.metrics_by_market.values()
        ),
        "wins": sum(
            1
            for market in resolved
            if market.net_cash_flow_usdc > PNL_SIGNIFICANCE_THRESHOLD
        ),
        "losses": sum(
            1
            for market in resolved
            if market.net_cash_flow_usdc < -PNL_SIGNIFICANCE_THRESHOLD
        ),
        "open_value": open_value,
        "pm_realized": sum(
            position[POSITION_REALIZED_PNL_FIELD] for position in positions
        ),
        "pm_unrealized": sum(
            position[POSITION_CASH_PNL_FIELD] for position in positions
        ),
        "has_positions": bool(positions),
        "net_cash_plus_open_value": aggregate.net_cash_flow_usdc
        + (open_value if positions else 0),
        ACTIVITY_TRUNCATED_FIELD: truncated,
        ACTIVITY_METRIC: activity,
    }


def _aggregate_activity(activity: list[ActivityRow]) -> _ActivityAggregate:
    aggregate = _ActivityAggregate(
        trades=[],
        activity_timestamps_seconds=[row[ACTIVITY_TIMESTAMP_FIELD] for row in activity],
        cash_by_type=defaultdict(float),
        count_by_type=defaultdict(int),
        metrics_by_market=defaultdict(MarketMetrics),
        net_cash_flow_usdc=0.0,
    )
    for row in activity:
        activity_type = ActivityType(row[ACTIVITY_TYPE_FIELD])
        aggregate.count_by_type[activity_type] += 1
        if activity_type is ActivityType.TRADE:
            aggregate.trades.append(row)
        cash = signed_cash(row)
        if cash is not None:
            aggregate.cash_by_type[activity_type] += cash
            aggregate.net_cash_flow_usdc += cash
        market = aggregate.metrics_by_market[_activity_market_key(row)]
        if cash is not None:
            market.net_cash_flow_usdc += cash
        market.record_position_delta(row, activity_type)
    return aggregate


def _classify_market_states(
    metrics_by_market: defaultdict[str, MarketMetrics],
) -> tuple[list[MarketMetrics], list[MarketMetrics]]:
    resolved: list[MarketMetrics] = []
    open_markets: list[MarketMetrics] = []
    for market in metrics_by_market.values():
        if all(
            abs(value) < OPEN_POSITION_SIZE_THRESHOLD
            for value in market.signed_position_sizes_by_outcome.values()
        ):
            resolved.append(market)
        else:
            open_markets.append(market)
    return resolved, open_markets


def _activity_timestamp_seconds_as_datetime(
    activity_timestamps_seconds: list[int], selector: Callable[[list[int]], int]
) -> datetime | None:
    return (
        None
        if not activity_timestamps_seconds
        else datetime.fromtimestamp(selector(activity_timestamps_seconds), timezone.utc)
    )


def _activity_market_key(row: ActivityRow) -> str:
    return row[CONDITION_ID_FIELD]


def _activity_span_hours(activity_timestamps_seconds: list[int]) -> float:
    span_seconds = (
        max(activity_timestamps_seconds) - min(activity_timestamps_seconds)
        if activity_timestamps_seconds
        else 0
    )
    return max(span_seconds / 3600, 1e-9)
