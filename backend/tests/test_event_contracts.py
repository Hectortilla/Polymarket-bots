from dataclasses import replace
from decimal import Decimal

import pytest
from polybot.execution.paper.portfolio import PAPER_SETTLEMENT_OWNER
from polybot.framework.events import FillEvent, OrderStatus, Side
from polybot.framework.events.resolutions import MarketResolutionEvent, SettledPosition
from polybot.polymarket.resolution import GAMMA_RECONCILIATION_SOURCE


@pytest.mark.parametrize("status", (OrderStatus.ACCEPTED, OrderStatus.CANCELED))
def test_nonexecution_status_has_no_execution_values(status):
    event = FillEvent(
        "order",
        "token",
        Side.BUY,
        status,
        Decimal("2"),
        Decimal("0"),
        None,
        Decimal("0"),
        1,
    )
    assert not event.has_execution
    for changes in (
        {"filled_size": Decimal("1")},
        {"average_price": Decimal("0.5")},
        {"fee_usdc": Decimal("0.01")},
    ):
        with pytest.raises(ValueError, match="execution values"):
            replace(event, **changes)


def test_filled_status_cannot_underfill_requested_size():
    with pytest.raises(ValueError, match="equal requested"):
        FillEvent(
            "order",
            "token",
            Side.BUY,
            OrderStatus.FILLED,
            Decimal("2"),
            Decimal("1"),
            Decimal("0.5"),
            Decimal("0"),
            1,
        )


def resolution():
    return MarketResolutionEvent(
        "condition",
        "market",
        ("yes", "no"),
        "yes",
        "Yes",
        1,
        GAMMA_RECONCILIATION_SOURCE,
    )


@pytest.mark.parametrize(
    "changes",
    (
        {"token_ids": ("yes",)},
        {"token_ids": ("yes", "no", "other")},
        {"token_ids": ("yes", "yes")},
        {"token_ids": ("yes", "")},
        {"token_ids": ("yes", None)},
        {"winning_token_id": ""},
        {"winning_token_id": None},
        {"winning_token_id": "other"},
    ),
)
def test_resolution_requires_two_distinct_tokens_and_a_member_winner(changes):
    with pytest.raises(ValueError):
        replace(resolution(), **changes)


def test_resolution_rejects_unrelated_payout_token():
    with pytest.raises(ValueError, match="does not belong"):
        resolution().payout_for("other")


@pytest.mark.parametrize(
    "changes",
    (
        {"owner": ""},
        {"token_id": ""},
        {"size": Decimal("NaN")},
        {"payout_per_token": Decimal("Infinity")},
        {"cash_payout_usdc": Decimal("NaN")},
        {"realized_pnl_usdc": Decimal("Infinity")},
        {"payout_per_token": Decimal("-0.01")},
        {"payout_per_token": Decimal("1.01")},
    ),
)
def test_settled_position_rejects_missing_identity_or_invalid_financial_values(changes):
    position = SettledPosition(
        PAPER_SETTLEMENT_OWNER, "token", Decimal("2"), Decimal("1"), Decimal("2")
    )
    with pytest.raises(ValueError):
        replace(position, **changes)
