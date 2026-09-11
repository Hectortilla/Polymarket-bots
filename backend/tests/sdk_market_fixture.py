"""Valid official market models shared by adapter contract tests."""

from decimal import Decimal

from polybot.framework.outcomes import NO_OUTCOME, YES_OUTCOME
from polymarket.models.gamma.market import (
    FeeSchedule,
    MarketOutcome,
    MarketOutcomes,
    MarketState,
    MarketTrading,
)
from polymarket.models.gamma.market import Market as SdkMarket


def sdk_market(
    slug: str,
    *,
    no_token_id: str | None = "no-token",
    minimum_order_size: str | None = "1",
    minimum_tick_size: str | None = "0.01",
) -> SdkMarket:
    return SdkMarket.model_construct(
        id=f"id-{slug}",
        slug=slug,
        condition_id=f"condition-{slug}",
        question=f"Question {slug}?",
        events=(),
        state=MarketState(
            active=True,
            archived=False,
            closed=False,
            acceptingOrders=True,
            enableOrderBook=True,
            negRisk=False,
        ),
        outcomes=MarketOutcomes(
            yes=MarketOutcome(label=YES_OUTCOME, tokenId=f"yes-{slug}"),
            no=MarketOutcome(label=NO_OUTCOME, tokenId=no_token_id),
        ),
        trading=MarketTrading(
            minimumOrderSize=minimum_order_size,
            minimumTickSize=minimum_tick_size,
            feesEnabled=True,
            feeSchedule=FeeSchedule(
                exponent=2,
                rate=Decimal("0.05"),
                takerOnly=True,
                rebateRate=Decimal("0"),
            ),
        ),
    )
