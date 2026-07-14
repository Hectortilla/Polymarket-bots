"""Market-share and hedge metrics for wallet activity."""

from collections.abc import Iterable, Mapping

from scripts.wallet_payload_contracts import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_TITLE_FIELD,
    CONDITION_ID_FIELD,
    ENRICHED_MARKET_SLUG_FIELD,
    ActivityRow,
)

from .contracts import MarketMetrics


def market_trade_share(
    trades: Iterable[ActivityRow],
    *,
    target_slug: str | None = None,
    target_condition_id: str | None = None,
) -> float:
    trade_rows = tuple(trades)
    if not trade_rows:
        return 0.0
    matched = sum(
        1
        for trade in trade_rows
        if _trade_matches_target_market(
            trade,
            target_slug=target_slug,
            target_condition_id=target_condition_id,
        )
    )
    return _market_trade_percentage(matched, len(trade_rows))


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
        or (
            target_slug
            and (
                trade.get(ACTIVITY_SLUG_FIELD) == target_slug
                or trade.get(ENRICHED_MARKET_SLUG_FIELD) == target_slug
            )
        )
    )


def hedge_score(signed_position_sizes_by_outcome: Mapping[str, float]) -> float:
    values = sorted(
        (value for value in signed_position_sizes_by_outcome.values() if value > 0.5),
        reverse=True,
    )
    if len(values) < 2:
        return 0.0
    return _hedge_score_for_two_positive_values(values[0], values[1])


def _hedge_score_for_two_positive_values(first: float, second: float) -> float:
    return 1 - abs(first - second) / (first + second)


def weighted_hedge_score(markets: Iterable[MarketMetrics]) -> float:
    weighted_scores: list[float] = []
    total_weight = 0.0
    for market in markets:
        weight = sum(
            abs(value)
            for value in market.signed_position_sizes_by_outcome.values()
        )
        if weight == 0:
            continue
        total_weight += weight
        weighted_scores.append(
            hedge_score(market.signed_position_sizes_by_outcome) * weight
        )
    if total_weight == 0:
        return 0.0
    return sum(weighted_scores) / total_weight
