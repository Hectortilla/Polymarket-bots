"""Book-event dispatch and followed-wallet baseline updates."""

from polybot.async_io import run_blocking
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.runner import BotRunner

from ..followed_wallets.tracker import FollowedWalletTracker
from ..streams.contracts import BookStreamEvent


async def dispatch_book(
    runner: BotRunner,
    event: BookStreamEvent,
    followed_wallets: FollowedWalletTracker | None,
) -> DispatchOutcome:
    outcome = await runner.dispatch_book(event.event)
    if outcome.accepted and followed_wallets is not None and event.event.bids:
        await run_blocking(
            followed_wallets.mark_baseline,
            event.event.token_id,
            max(level.price for level in event.event.bids),
        )
    return outcome
