"""Normalized deterministic market and book inputs, without external transport."""

from decimal import Decimal

from polybot.framework.clock import Clock
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.polymarket.markets import Market, MarketOutcome

from control_plane.onboarding_policy import OnboardingCase


class OnboardingMarketData:
    def __init__(self, case: OnboardingCase, clock: Clock):
        self._case = case
        self._clock = clock
        slug = case.market_slug
        self.market = Market(
            condition_id=f"condition-{slug}",
            slug=slug,
            question=f"Will {slug} happen?",
            minimum_tick_size=Decimal("0.01"),
            minimum_order_size=Decimal(1),
            neg_risk=False,
            fee_rate=Decimal(0),
            outcomes=(
                MarketOutcome("Yes", f"{slug}-yes"),
                MarketOutcome("No", f"{slug}-no"),
            ),
            active=True,
            closed=False,
            order_book_enabled=True,
            accepting_orders=True,
        )

    async def find_by_slug(self, slug: str) -> Market | None:
        return self.market if slug == self.market.slug else None

    async def latest(self, token_id: str) -> BookSnapshot | None:
        if token_id not in self.market.token_ids:
            return None
        ask = self._case.ask
        return BookSnapshot(
            token_id=token_id,
            bids=(BookLevel(ask - Decimal("0.01"), Decimal(100)),),
            asks=(BookLevel(ask, Decimal(100)),),
            received_at_ms=self._clock.now_ms(),
            market_slug=self.market.slug,
            condition_id=self.market.condition_id,
            outcome=self.market.outcome_label_for_token(token_id),
        )
