"""Per-runtime dispatch into bot, market registration, and wallet accounting."""

from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason
from polybot.framework.runner import BotRunner
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.errors import MarketDataError
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.markets import Market
from polybot.polymarket.wallet_activity.stream import WalletActivityStream

from ..followed_wallets.tracker import FollowedWalletTracker
from ..market_identity import MarketIdentity
from ..resolution.settlement import ResolutionSettlementService
from ..streams.contracts import (
    BookGapStreamEvent,
    BookStreamEvent,
    StreamEvent,
    WalletStreamEvent,
)
from ..streams.kinds import StreamKind
from ..tracked_markets import MarketInterest, TrackedMarketRegistry


class StreamEventDispatcher:
    def __init__(
        self,
        runner: BotRunner,
        wallet_stream: WalletActivityStream,
        *,
        gamma: GammaClient,
        clob: ClobClient,
        registry: TrackedMarketRegistry | None,
        followed_wallets: FollowedWalletTracker | None,
        resolution_service: ResolutionSettlementService | None,
    ) -> None:
        self._runner = runner
        self._wallet_stream = wallet_stream
        self._gamma = gamma
        self._clob = clob
        self._registry = registry
        self._followed_wallets = followed_wallets
        self._resolution_service = resolution_service

    async def dispatch(self, stream_event: StreamEvent) -> DispatchOutcome | None:
        if isinstance(stream_event, BookGapStreamEvent):
            await self._runner.dispatch_book_gap(stream_event.event)
        elif stream_event.kind is StreamKind.BOOK:
            return await self.dispatch_book(stream_event)
        elif stream_event.kind is StreamKind.WALLET:
            return await self.dispatch_wallet_trade(stream_event)
        elif stream_event.kind is StreamKind.MARKET_HINT:
            self._wallet_stream.wake_market(stream_event.event.condition_id)
        elif stream_event.kind is StreamKind.RESOLUTION:
            if self._resolution_service is None:
                raise RuntimeError(
                    "resolution dispatch dependencies are required for resolution events"
                )
            await self._resolution_service.apply(stream_event.event)
        return None

    async def dispatch_book(self, event: BookStreamEvent) -> DispatchOutcome:
        if (
            self._registry is not None
            and event.event.condition_id is not None
            and self._registry.is_terminal(event.event.condition_id)
        ):
            return DispatchOutcome.skipped(DispatchSkipReason.MARKET_RESOLVED)
        outcome = await self._runner.dispatch_book(event.event)
        if outcome.accepted and self._followed_wallets is not None and event.event.bids:
            self._followed_wallets.mark_baseline(
                event.event.token_id,
                max(level.price for level in event.event.bids),
            )
        return outcome

    async def dispatch_wallet_trade(
        self, stream_event: WalletStreamEvent
    ) -> DispatchOutcome:
        event = stream_event.event
        if self._registry is not None and self._registry.is_terminal(
            event.condition_id
        ):
            return DispatchOutcome.skipped(DispatchSkipReason.MARKET_RESOLVED)
        if not event.market_slug:
            return DispatchOutcome.skipped(DispatchSkipReason.MARKET_METADATA_MISSING)
        market = self._known_market(event.condition_id, event.market_slug)
        if market is None:
            market = await self._find_market(event.market_slug)
        if market is None or not MarketIdentity.from_wallet_trade(event).matches(
            market
        ):
            return DispatchOutcome.skipped(DispatchSkipReason.MARKET_METADATA_MISSING)
        if self._registry is not None and market is not None:
            try:
                self._registry.ensure_compatible(market)
            except MarketDataError:
                return DispatchOutcome.skipped(
                    DispatchSkipReason.MARKET_METADATA_MISSING
                )
            self._registry.require_capacity(market)
        if not self._clob.has_market_slug(event.market_slug):
            try:
                self._clob.add_market(market)
            except MarketDataError:
                return DispatchOutcome.skipped(
                    DispatchSkipReason.MARKET_METADATA_MISSING
                )
        outcome = await self._runner.dispatch_wallet_trade(event)
        if not outcome.accepted:
            return outcome
        if self._followed_wallets is not None:
            self._followed_wallets.record_trade(event)
        if self._registry is not None and market is not None:
            self._registry.add(
                market, MarketInterest.FOLLOWED_WALLET, owner=event.wallet
            )
        return outcome

    async def _find_market(self, slug: str) -> Market | None:
        try:
            return await self._gamma.find_by_slug(slug)
        except MarketDataError:
            return None

    def _known_market(self, condition_id: str, market_slug: str) -> Market | None:
        if self._registry is None:
            return None
        entry = self._registry.get(condition_id)
        if entry is None or entry.market.slug != market_slug:
            return None
        return entry.market
