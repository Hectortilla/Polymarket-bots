"""Book-event dispatch and followed-wallet baseline updates."""

from polybot.async_io import run_blocking
from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason
from polybot.framework.runner import BotRunner

from ..followed_wallets.tracker import FollowedWalletTracker
from ..streams.contracts import BookStreamEvent
from ..tracked_markets import TrackedMarketRegistry


async def dispatch_book(
    runner: BotRunner,
    event: BookStreamEvent,
    followed_wallets: FollowedWalletTracker | None,
    registry: TrackedMarketRegistry | None = None,
) -> DispatchOutcome:
    if (
        registry is not None
        and event.event.condition_id is not None
        and registry.is_terminal(event.event.condition_id)
    ):
        return DispatchOutcome.skipped(DispatchSkipReason.MARKET_RESOLVED)
    outcome = await runner.dispatch_book(event.event)
    if outcome.accepted and followed_wallets is not None and event.event.bids:
        await run_blocking(
            followed_wallets.mark_baseline,
            event.event.token_id,
            max(level.price for level in event.event.bids),
        )
    return outcome
