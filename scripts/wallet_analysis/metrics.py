"""Wallet metric orchestration."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from dataclasses import dataclass

from polybot.framework.events import Side
from scripts.wallet_payload_contracts import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
    ActivityRow,
    ActivityType,
    PositionRow,
)

from .cash_metrics import fee_paid, signed_cash
from .contracts import (
    OPEN_POSITION_SIZE_THRESHOLD,
    MarketMetrics,
    PNL_SIGNIFICANCE_THRESHOLD,
    WalletMetrics,
)
from .market_metrics import weighted_hedge_score


@dataclass(slots=True)
class _ActivityAggregate:
    trades: list[ActivityRow]
    timestamps: list[int]
    cash_by_type: defaultdict[ActivityType, float]
    count_by_type: defaultdict[ActivityType, int]
    metrics_by_market: defaultdict[str, MarketMetrics]
    net_cash: float


def compute_metrics(
    activity: list[ActivityRow],
    positions: list[PositionRow],
    truncated: bool = False,
) -> WalletMetrics:
    aggregate = _aggregate_activity(activity)
    resolved, open_markets = _classify_market_states(aggregate.metrics_by_market)
    volume = sum(row[ACTIVITY_USDC_SIZE_FIELD] for row in aggregate.trades)
    fees = sum(fee_paid(row) for row in aggregate.trades)
    open_value = sum(position[POSITION_CURRENT_VALUE_FIELD] for position in positions)
    span_hours = max(
        ((max(aggregate.timestamps) - min(aggregate.timestamps)) / 3600)
        if aggregate.timestamps
        else 0,
        1e-9,
    )
    return {
        "activity_count": len(activity),
        "trade_count": len(aggregate.trades),
        "first_activity_at": _timestamp_as_datetime(aggregate.timestamps, min),
        "last_activity_at": _timestamp_as_datetime(aggregate.timestamps, max),
        "activity_span_hours": span_hours,
        "n_markets": len(aggregate.metrics_by_market),
        "n_resolved": len(resolved),
        "n_open": len(open_markets),
        "cash_by_activity_type": dict(aggregate.cash_by_type),
        "count_by_activity_type": dict(aggregate.count_by_type),
        "net_cash": aggregate.net_cash,
        "volume": volume,
        "fees": fees,
        "gross_before_fees": aggregate.net_cash + fees,
        "rewards": aggregate.cash_by_type.get(ActivityType.REWARD, 0.0),
        "hedge_avg": weighted_hedge_score(aggregate.metrics_by_market.values()),
        "wins": sum(
            1 for market in resolved if market.cash > PNL_SIGNIFICANCE_THRESHOLD
        ),
        "losses": sum(
            1 for market in resolved if market.cash < -PNL_SIGNIFICANCE_THRESHOLD
        ),
        "open_value": open_value,
        "pm_realized": sum(
            position[POSITION_REALIZED_PNL_FIELD] for position in positions
        ),
        "pm_unrealized": sum(
            position[POSITION_CASH_PNL_FIELD] for position in positions
        ),
        "has_positions": bool(positions),
        "net_cash_plus_open_value": aggregate.net_cash
        + (open_value if positions else 0),
        "truncated": truncated,
        "activity": activity,
    }


def _aggregate_activity(activity: list[ActivityRow]) -> _ActivityAggregate:
    aggregate = _ActivityAggregate(
        trades=[],
        timestamps=[row[ACTIVITY_TIMESTAMP_FIELD] for row in activity],
        cash_by_type=defaultdict(float),
        count_by_type=defaultdict(int),
        metrics_by_market=defaultdict(MarketMetrics),
        net_cash=0.0,
    )
    for row in activity:
        activity_type = ActivityType(row[ACTIVITY_TYPE_FIELD])
        aggregate.count_by_type[activity_type] += 1
        if activity_type is ActivityType.TRADE:
            aggregate.trades.append(row)
        cash = signed_cash(row)
        if cash is not None:
            aggregate.cash_by_type[activity_type] += cash
            aggregate.net_cash += cash
        market = aggregate.metrics_by_market[_activity_market_key(row)]
        if cash is not None:
            market.cash += cash
        _record_position_delta(market, row, activity_type)
    return aggregate


def _record_position_delta(
    market: MarketMetrics,
    row: ActivityRow,
    activity_type: ActivityType,
) -> None:
    outcome = str(row.get(ACTIVITY_OUTCOME_FIELD, "?"))
    size = row.get(ACTIVITY_SIZE_FIELD, 0.0)
    if activity_type is ActivityType.TRADE:
        market.signed_position_sizes_by_outcome[outcome] += (
            size if Side(row[ACTIVITY_SIDE_FIELD]) is Side.BUY else -size
        )
    elif activity_type in (ActivityType.REDEEM, ActivityType.MERGE):
        market.signed_position_sizes_by_outcome[outcome] -= size


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


def _timestamp_as_datetime(
    timestamps: list[int], selector: Callable[[list[int]], int]
) -> datetime | None:
    return (
        None
        if not timestamps
        else datetime.fromtimestamp(selector(timestamps), timezone.utc)
    )


def _activity_market_key(row: ActivityRow) -> str:
    return row[CONDITION_ID_FIELD]
