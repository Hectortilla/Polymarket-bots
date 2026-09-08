"""Polling reconciliation for Gamma markets that became resolved."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from polybot.framework.cadence import RESOLUTION_RECONCILIATION_SECONDS
from polybot.framework.clock import system_now_ms
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.resolution import (
    GAMMA_RECONCILIATION_SOURCE,
    resolution_event_from_market,
)

from ..tracked_markets import TrackedMarketRegistry


async def reconcile_resolutions(
    registry: TrackedMarketRegistry,
    gamma: GammaClient,
    *,
    interval_seconds: float = RESOLUTION_RECONCILIATION_SECONDS,
    now_ms: Callable[[], int] | None = None,
) -> AsyncIterator[MarketResolutionEvent]:
    """Yield newly resolved tracked markets while tolerating provider outages."""

    clock = now_ms or system_now_ms
    while True:
        try:
            markets = registry.markets
            if markets:
                refreshed = await gamma.find_many(market.slug for market in markets)
                for market in refreshed:
                    if market is not None:
                        resolution = resolution_event_from_market(
                            market,
                            resolved_at_ms=clock(),
                            source=GAMMA_RECONCILIATION_SOURCE,
                        )
                        if resolution is not None:
                            yield resolution
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)
