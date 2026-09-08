"""Runner stream-plan refresh and selector compilation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from polybot.framework.streams import StreamPlan
from polybot.polymarket.wallet_activity.contracts import WalletTradeSelector

if TYPE_CHECKING:
    from polybot.polymarket.markets import Market


def compile_selectors(
    plan: StreamPlan,
    markets: tuple[Market, ...],
) -> tuple[WalletTradeSelector, ...]:
    by_slug = {market.slug: market.condition_id for market in markets}
    selectors: set[WalletTradeSelector] = set()
    for rule in plan.current:
        for scope in rule.scopes:
            selectors.add(
                WalletTradeSelector(
                    wallet=scope.wallet_address,
                    condition_ids=tuple(by_slug[slug] for slug in scope.market_slugs),
                )
            )
    return tuple(
        sorted(selectors, key=lambda item: (item.wallet or "", item.condition_ids))
    )
