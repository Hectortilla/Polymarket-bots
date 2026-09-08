from __future__ import annotations

import pytest

from polybot.framework.events import Side
from polybot.framework.outcomes import YES_OUTCOME
from scripts.wallet_analysis.cash_metrics import fee_paid, signed_cash
from scripts.wallet_analysis.market_metrics import (
    hedge_score,
    market_trade_share,
    weighted_hedge_score,
)
from scripts.wallet_analysis.contracts import MarketMetrics
from scripts.wallet_payloads import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    ENRICHED_MARKET_SLUG_FIELD,
    ActivityType,
)


@pytest.mark.parametrize(
    ("activity_type", "side", "expected_cash"),
    (
        (ActivityType.TRADE, Side.BUY, -0.8),
        (ActivityType.TRADE, Side.SELL, 0.8),
        (ActivityType.REDEEM, Side.BUY, 0.8),
        (ActivityType.REWARD, Side.BUY, 0.8),
        (ActivityType.MERGE, Side.BUY, 0.8),
        (ActivityType.SPLIT, Side.BUY, -0.8),
    ),
)
def test_signed_cash_respects_activity_direction(
    activity_type: ActivityType,
    side: Side,
    expected_cash: float,
) -> None:
    row = _activity(activity_type, side=side)

    assert signed_cash(row) == expected_cash


def test_fee_paid_is_trade_notional_difference() -> None:
    assert fee_paid(_activity(ActivityType.TRADE, size=2, price=0.4, usdc_size=0.9)) == pytest.approx(0.1)
    assert fee_paid(_activity(ActivityType.REWARD, usdc_size=0.9)) == 0.0


def test_market_trade_share_matches_canonical_and_enriched_market_identity() -> None:
    trades = [
        _activity(ActivityType.TRADE, condition_id="condition-target"),
        _activity(ActivityType.TRADE, slug="target-market"),
        _activity(ActivityType.TRADE, enriched_slug="target-market"),
        _activity(ActivityType.TRADE, condition_id="other-condition"),
    ]

    assert market_trade_share(trades, target_condition_id="condition-target") == 25.0
    assert market_trade_share(trades, target_slug="target-market") == 50.0


def test_hedge_score_and_weighted_score_use_signed_position_sizes() -> None:
    balanced = MarketMetrics()
    balanced.signed_position_sizes_by_outcome.update(yes=2.0, no=2.0)
    unbalanced = MarketMetrics()
    unbalanced.signed_position_sizes_by_outcome.update(yes=4.0, no=1.0)

    assert hedge_score(balanced.signed_position_sizes_by_outcome) == 1.0
    assert hedge_score(unbalanced.signed_position_sizes_by_outcome) == pytest.approx(0.4)
    assert weighted_hedge_score((balanced, unbalanced)) == pytest.approx(2 / 3)


def _activity(
    activity_type: ActivityType,
    *,
    side: Side = Side.BUY,
    size: float = 2.0,
    price: float = 0.4,
    usdc_size: float = 0.8,
    condition_id: str | None = None,
    slug: str | None = None,
    enriched_slug: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        ACTIVITY_TYPE_FIELD: activity_type,
        ACTIVITY_SIDE_FIELD: side,
        ACTIVITY_SIZE_FIELD: size,
        ACTIVITY_PRICE_FIELD: price,
        ACTIVITY_USDC_SIZE_FIELD: usdc_size,
        ACTIVITY_OUTCOME_FIELD: YES_OUTCOME,
    }
    if condition_id is not None:
        row[CONDITION_ID_FIELD] = condition_id
    if slug is not None:
        row[ACTIVITY_SLUG_FIELD] = slug
    if enriched_slug is not None:
        row[ENRICHED_MARKET_SLUG_FIELD] = enriched_slug
    return row
