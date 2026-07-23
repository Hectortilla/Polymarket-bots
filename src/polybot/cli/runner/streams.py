"""Runner stream-plan refresh and selector compilation."""

from __future__ import annotations

import asyncio

from polybot.framework.cadence import STREAM_PLAN_REFRESH_INTERVAL_SECONDS
from polybot.framework.runner import BotRunner
from polybot.framework.streams import StreamPlan
from polybot.polymarket.markets import Market
from polybot.polymarket.wallet_activity.contracts import WalletTradeSelector

async def wait_for_stream_plan_change(
    runner: BotRunner, current_stream_plan: StreamPlan
) -> StreamPlan:
    """Wait until a dynamic bot changes its active subscriptions."""
    while True:
        await asyncio.sleep(STREAM_PLAN_REFRESH_INTERVAL_SECONDS)
        candidate = await runner.refresh_stream_plan()
        if candidate.current != current_stream_plan.current:
            return candidate


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


async def refresh_runner_plan(runner: BotRunner) -> StreamPlan:
    """Refresh the sole stream-rule topology owned by the bot runner."""
    return await runner.refresh_stream_plan()
