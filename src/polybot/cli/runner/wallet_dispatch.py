"""Wallet-trade dispatch and dynamic market registration."""

from polybot.async_io import run_blocking
from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason
from polybot.framework.runner import BotRunner
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.gamma import GammaClient

from ..followed_wallets.tracker import FollowedWalletTracker
from ..market_identity import validate_wallet_trade_market_identity
from ..streams.contracts import StreamEvent
from ..tracked_markets import MarketInterest, TrackedMarketRegistry


async def dispatch_wallet_trade(
    runner: BotRunner,
    stream_event: StreamEvent,
    *,
    gamma: GammaClient,
    clob: ClobClient,
    registry: TrackedMarketRegistry | None,
    followed_wallets: FollowedWalletTracker | None,
) -> DispatchOutcome:
    event = stream_event.event
    if not event.market_slug:
        return DispatchOutcome.skipped(DispatchSkipReason.MARKET_METADATA_MISSING)
    market = _known_market(registry, event.condition_id, event.market_slug)
    if market is None:
        market = await _find_market(gamma, event.market_slug)
    try:
        validate_wallet_trade_market_identity(
            event,
            market,
            "wallet trade market identity is incomplete or mismatched",
        )
    except RuntimeError:
        return DispatchOutcome.skipped(DispatchSkipReason.MARKET_METADATA_MISSING)
    if not clob.has_market_slug(event.market_slug):
        try:
            clob.add_market(market)
        except Exception:
            return DispatchOutcome.skipped(DispatchSkipReason.MARKET_METADATA_MISSING)
    outcome = await runner.dispatch_wallet_trade(event)
    if not outcome.accepted:
        return outcome
    if followed_wallets is not None:
        await run_blocking(followed_wallets.record_trade, event)
    if registry is not None and market is not None:
        registry.add(market, MarketInterest.FOLLOWED_WALLET, owner=event.wallet)
    return outcome


async def _find_market(gamma: GammaClient, slug: str):
    try:
        return await gamma.find_by_slug(slug)
    except Exception:
        return None


def _known_market(
    registry: TrackedMarketRegistry | None,
    condition_id: str,
    market_slug: str,
):
    if registry is None:
        return None
    entry = registry.get(condition_id)
    if entry is None or entry.market.slug != market_slug:
        return None
    return entry.market
