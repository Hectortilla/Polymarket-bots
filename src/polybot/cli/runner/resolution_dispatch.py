"""Resolution-event dispatch into paper and followed-wallet settlement."""

from polybot.execution.paper import PaperBroker
from polybot.framework.runner import BotRunner

from ..followed_wallets.tracker import FollowedWalletTracker
from ..observability.observer import RuntimeObserver
from ..resolution.settlement import apply_resolution
from ..resolution_state.ledger import ResolutionLedger
from ..streams.contracts import StreamEvent
from ..tracked_markets import TrackedMarketRegistry


async def dispatch_resolution(
    runner: BotRunner,
    event: StreamEvent,
    *,
    registry: TrackedMarketRegistry,
    followed_wallets: FollowedWalletTracker,
    paper_broker: PaperBroker,
    resolution_ledger: ResolutionLedger,
    observer: RuntimeObserver | None,
) -> None:
    await apply_resolution(
        runner,
        event.event,
        registry=registry,
        followed_wallets=followed_wallets,
        paper_broker=paper_broker,
        resolution_ledger=resolution_ledger,
        observer=observer,
    )
