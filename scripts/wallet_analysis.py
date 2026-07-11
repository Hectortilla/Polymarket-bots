from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import TypedDict

from polybot.framework.events import Side
from scripts.wallet_payloads import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TITLE_FIELD,
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

HEDGE_SCORE_THRESHOLD = 0.80


class WalletVerdict(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"


class WalletClassificationReason(StrEnum):
    NET_POSITIVE_DIRECTIONAL_REALIZED = "net_positive_directional_realized"
    HEDGED = "hedged"
    FEE_EATEN = "fee_eaten"
    NET_NEGATIVE_OR_FLAT = "net_negative_or_flat"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class WalletClassification:
    verdict: WalletVerdict
    reason: WalletClassificationReason
    explanation: str

    @property
    def is_good(self) -> bool:
        return self.verdict is WalletVerdict.GOOD


class WalletMetrics(TypedDict):
    n_items: int
    n_trades: int
    t0: datetime | None
    t1: datetime | None
    span_h: float
    n_markets: int
    n_resolved: int
    n_open: int
    by_type_cash: dict[ActivityType, float]
    by_type_n: dict[ActivityType, int]
    net_cash: float
    volume: float
    fees: float
    gross_before_fees: float
    rewards: float
    hedge_avg: float
    wins: int
    losses: int
    open_value: float
    pm_realized: float
    pm_unrealized: float
    has_positions: bool
    total_real: float
    truncated: bool
    activity: list[ActivityRow]


@dataclass(slots=True)
class MarketMetrics:
    cash: float = 0.0
    net: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))


def signed_cash(item: ActivityRow) -> float | None:
    activity_type = ActivityType(item[ACTIVITY_TYPE_FIELD])
    usdc_size = item[ACTIVITY_USDC_SIZE_FIELD]
    if activity_type is ActivityType.TRADE:
        return -usdc_size if Side(item[ACTIVITY_SIDE_FIELD]) is Side.BUY else usdc_size
    if activity_type in (ActivityType.REDEEM, ActivityType.REWARD, ActivityType.MERGE):
        return usdc_size
    if activity_type is ActivityType.SPLIT:
        return -usdc_size
    return None


def fee_paid(item: ActivityRow) -> float:
    if ActivityType(item[ACTIVITY_TYPE_FIELD]) is not ActivityType.TRADE:
        return 0.0
    notional = item[ACTIVITY_SIZE_FIELD] * item[ACTIVITY_PRICE_FIELD]
    return abs(item[ACTIVITY_USDC_SIZE_FIELD] - notional)


def market_trade_share(
    trades: Iterable[ActivityRow],
    *,
    target_slug: str | None = None,
    target_condition_id: str | None = None,
) -> float:
    trades = tuple(trades)
    if not trades:
        return 0.0
    matched = sum(
        1
        for trade in trades
        if _trade_matches_target_market(
            trade,
            target_slug=target_slug,
            target_condition_id=target_condition_id,
        )
    )
    return _market_trade_percentage(matched, len(trades))


def _market_trade_percentage(matched: int, total: int) -> float:
    return matched / total * 100


def _trade_matches_target_market(
    trade: ActivityRow,
    *,
    target_slug: str | None,
    target_condition_id: str | None,
) -> bool:
    return bool(
        (target_condition_id and trade.get(CONDITION_ID_FIELD) == target_condition_id)
        or (target_slug and trade.get("market_slug") == target_slug)
    )


def compute_metrics(
    activity: list[ActivityRow],
    positions: list[PositionRow],
    truncated: bool = False,
) -> WalletMetrics:
    trades = [row for row in activity if ActivityType(row[ACTIVITY_TYPE_FIELD]) is ActivityType.TRADE]
    timestamps = [row[ACTIVITY_TIMESTAMP_FIELD] for row in activity if row.get(ACTIVITY_TIMESTAMP_FIELD)]
    cash_by_type: defaultdict[ActivityType, float] = defaultdict(float)
    count_by_type: defaultdict[ActivityType, int] = defaultdict(int)
    metrics_by_market: defaultdict[str, MarketMetrics] = defaultdict(MarketMetrics)
    net_cash = 0.0
    for row in activity:
        activity_type = ActivityType(row[ACTIVITY_TYPE_FIELD])
        count_by_type[activity_type] += 1
        cash = signed_cash(row)
        if cash is not None:
            cash_by_type[activity_type] += cash
            net_cash += cash
        market = metrics_by_market[_activity_market_key(row)]
        if cash is not None:
            market.cash += cash
        outcome = str(row.get(ACTIVITY_OUTCOME_FIELD, "?"))
        size = row.get(ACTIVITY_SIZE_FIELD, 0.0)
        if activity_type is ActivityType.TRADE:
            market.net[outcome] += size if Side(row[ACTIVITY_SIDE_FIELD]) is Side.BUY else -size
        elif activity_type in (ActivityType.REDEEM, ActivityType.MERGE):
            market.net[outcome] -= size
    resolved = [market for market in metrics_by_market.values() if all(abs(value) < 1 for value in market.net.values())]
    open_markets = [market for market in metrics_by_market.values() if any(abs(value) >= 1 for value in market.net.values())]
    volume = sum(row[ACTIVITY_USDC_SIZE_FIELD] for row in trades)
    fees = sum(fee_paid(row) for row in trades)
    open_value = sum(position[POSITION_CURRENT_VALUE_FIELD] for position in positions)
    span_hours = max(((max(timestamps) - min(timestamps)) / 3600) if timestamps else 0, 1e-9)
    return {
        "n_items": len(activity), "n_trades": len(trades),
        "t0": datetime.fromtimestamp(min(timestamps), timezone.utc) if timestamps else None,
        "t1": datetime.fromtimestamp(max(timestamps), timezone.utc) if timestamps else None,
        "span_h": span_hours, "n_markets": len(metrics_by_market),
        "n_resolved": len(resolved), "n_open": len(open_markets),
        "by_type_cash": dict(cash_by_type), "by_type_n": dict(count_by_type),
        "net_cash": net_cash, "volume": volume, "fees": fees,
        "gross_before_fees": net_cash + fees,
        "rewards": cash_by_type.get(ActivityType.REWARD, 0.0),
        "hedge_avg": weighted_hedge_score(metrics_by_market.values()),
        "wins": sum(1 for market in resolved if market.cash > 0.005),
        "losses": sum(1 for market in resolved if market.cash < -0.005),
        "open_value": open_value,
        "pm_realized": sum(position[POSITION_REALIZED_PNL_FIELD] for position in positions),
        "pm_unrealized": sum(position[POSITION_CASH_PNL_FIELD] for position in positions),
        "has_positions": bool(positions), "total_real": net_cash + (open_value if positions else 0),
        "truncated": truncated, "activity": activity,
    }


def _activity_market_key(row: ActivityRow) -> str:
    return str(
        row.get(CONDITION_ID_FIELD)
        or row.get(ACTIVITY_SLUG_FIELD)
        or row.get(ACTIVITY_TITLE_FIELD)
        or "?"
    )


def hedge_score(net: Mapping[str, float]) -> float:
    values = sorted((value for value in net.values() if value > 0.5), reverse=True)
    if len(values) < 2:
        return 0.0
    return _hedge_score_for_two_positive_values(values[0], values[1])


def _hedge_score_for_two_positive_values(first: float, second: float) -> float:
    return 1 - abs(first - second) / (first + second)


def weighted_hedge_score(markets: Iterable[MarketMetrics]) -> float:
    weighted_scores = []
    total_weight = 0.0
    for market in markets:
        weight = sum(abs(value) for value in market.net.values())
        if weight == 0:
            continue
        total_weight += weight
        weighted_scores.append(hedge_score(market.net) * weight)
    if total_weight == 0:
        return 0.0
    return _weighted_average(weighted_scores, total_weight)


def _weighted_average(weighted_values: list[float], total_weight: float) -> float:
    return sum(weighted_values) / total_weight


def classify_wallet_candidate(wallet_metrics: WalletMetrics) -> WalletClassification:
    net_cash = wallet_metrics["net_cash"]
    fee_eaten = wallet_metrics["gross_before_fees"] > 0 and net_cash < 0
    hedged = wallet_metrics["hedge_avg"] >= HEDGE_SCORE_THRESHOLD
    if net_cash > 0 and not hedged and not fee_eaten:
        return WalletClassification(
            WalletVerdict.GOOD,
            WalletClassificationReason.NET_POSITIVE_DIRECTIONAL_REALIZED,
            "net positive after fees, directional, realized",
        )
    if hedged:
        return WalletClassification(
            WalletVerdict.BAD,
            WalletClassificationReason.HEDGED,
            "hedged both sides (volume/airdrop farm shape)",
        )
    if fee_eaten:
        return WalletClassification(
            WalletVerdict.BAD,
            WalletClassificationReason.FEE_EATEN,
            "edge eaten by fees -> net loser",
        )
    if net_cash <= 0:
        return WalletClassification(
            WalletVerdict.BAD,
            WalletClassificationReason.NET_NEGATIVE_OR_FLAT,
            "net negative/flat after fees",
        )
    return WalletClassification(
        WalletVerdict.BAD,
        WalletClassificationReason.INCONCLUSIVE,
        "inconclusive",
    )
