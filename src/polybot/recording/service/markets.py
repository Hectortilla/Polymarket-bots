"""Initial market resolution for a recording session."""

from __future__ import annotations

from collections.abc import Iterable

from polybot.framework.streams import StreamPlan
from polybot.polymarket.recording_metadata.contracts import RecordingMarket
from polybot.polymarket.recording_metadata.resolver import RecordingMarketResolver


async def resolve_initial_markets(
    resolver: RecordingMarketResolver,
    plan: StreamPlan,
    restored_slugs: Iterable[str],
) -> tuple[tuple[RecordingMarket, ...], tuple[str, ...]]:
    """Resolve planned and resumed markets, requiring every current market."""
    restored = tuple(dict.fromkeys(restored_slugs))
    requested = tuple(
        dict.fromkeys(
            (
                *plan.current_market_slugs,
                *plan.next_market_slugs,
                *restored,
            )
        )
    )
    resolved = await resolver.find_many(requested)
    by_slug = dict(zip(requested, resolved, strict=True))
    missing_current = tuple(
        slug for slug in plan.current_market_slugs if by_slug[slug] is None
    )
    if missing_current:
        raise RuntimeError(
            "initial current markets could not be resolved: "
            + ", ".join(missing_current)
        )
    markets = tuple(recording for recording in resolved if recording is not None)
    missing_restored = tuple(slug for slug in restored if by_slug[slug] is None)
    return markets, missing_restored
