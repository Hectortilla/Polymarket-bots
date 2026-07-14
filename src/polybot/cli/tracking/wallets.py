"""Followed-wallet discovery and bootstrap tracking."""

from __future__ import annotations

from polybot.async_io import run_blocking
from polybot.framework.streams import StreamPlan
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.data import DataClient
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.types import Position

from ..followed_wallets.tracker import FollowedWalletTracker
from ..market_identity import validate_position_market_identity
from ..tracked_markets import MarketInterest, TrackedMarketRegistry


async def synchronize_followed_wallets(
    wallet_scopes: dict[str, frozenset[str] | None],
    followed_wallets: FollowedWalletTracker,
    position_client: DataClient,
    gamma: GammaClient,
    clob: ClobClient,
    registry: TrackedMarketRegistry,
) -> None:
    new_wallets = (
        ()
        if not wallet_scopes
        else await run_blocking(followed_wallets.synchronize, tuple(wallet_scopes))
    )
    for wallet in new_wallets:
        positions = tuple(await position_client.positions(wallet))
        allowlist = wallet_scopes[wallet]
        if allowlist is not None:
            positions = tuple(
                position for position in positions if position.market_slug in allowlist
            )
        markets = await gamma.find_many(
            dict.fromkeys(
                position.market_slug
                for position in positions
                if position.market_slug is not None
            )
        )
        by_slug = {market.slug: market for market in markets if market is not None}
        for position in positions:
            market = by_slug.get(position.market_slug)
            validate_position_market_identity(
                position,
                market,
                "current wallet position has unresolved market identity",
            )
            registry.add(market, MarketInterest.FOLLOWED_WALLET, owner=wallet)
        clob.set_markets(registry.markets)
        marked_positions = []
        for position in positions:
            book = await clob.latest(position.token_id)
            if book is not None and (
                not book.has_valid_levels() or book.is_crossed()
            ):
                raise MarketDataError(
                    MarketDataIssue.INVALID_BOOK_LEVEL,
                    "followed-wallet bootstrap received an invalid market book",
                )
            mark = None if book is None else book.executable_mark(position.size)
            marked_positions.append((position, mark))
        await run_blocking(followed_wallets.bootstrap, wallet, tuple(marked_positions))

    known_slugs = {market.slug for market in registry.markets}
    persisted_slugs = tuple(
        slug for slug in followed_wallets.open_market_slugs() if slug not in known_slugs
    )
    if not persisted_slugs:
        return
    markets = await gamma.find_many(persisted_slugs)
    by_slug = {market.slug: market for market in markets if market is not None}
    missing = [slug for slug in persisted_slugs if slug not in by_slug]
    if missing:
        raise RuntimeError(
            "persisted followed-wallet markets could not be resolved: "
            + ", ".join(missing)
        )
    for wallet, position in followed_wallets.tracked_market_positions():
        if position.market_slug in by_slug:
            registry.add(
                by_slug[position.market_slug],
                MarketInterest.FOLLOWED_WALLET,
                owner=wallet,
            )
