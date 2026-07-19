"""Followed-wallet discovery and bootstrap tracking."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from polybot.async_io import run_blocking
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.positions import Position, PositionClient
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.markets import Market

from ..followed_wallets.position_contracts import FollowPosition
from ..markets import MarketResolver
from ..market_identity import validate_position_market_identity
from ..tracked_markets import MarketInterest, TrackedMarketRegistry


class FollowedWalletStore(Protocol):
    def synchronize(self, wallets: tuple[str, ...]) -> tuple[str, ...]: ...

    def bootstrap(
        self,
        wallet: str,
        positions_with_baseline_marks: tuple[tuple[Position, Decimal | None], ...],
    ) -> None: ...

    def open_market_slugs(self) -> tuple[str, ...]: ...

    def tracked_market_positions(self) -> tuple[tuple[str, FollowPosition], ...]: ...


async def synchronize_followed_wallets(
    wallet_scopes: dict[str, frozenset[str] | None],
    followed_wallets: FollowedWalletStore,
    position_client: PositionClient,
    gamma: MarketResolver,
    clob: ClobClient,
    registry: TrackedMarketRegistry,
    resolved_markets: tuple[Market, ...] = (),
) -> None:
    new_wallets = (
        ()
        if not wallet_scopes
        else await run_blocking(followed_wallets.synchronize, tuple(wallet_scopes))
    )
    for wallet in new_wallets:
        allowlist = wallet_scopes[wallet]
        scoped_markets = await _resolve_scope_markets(
            allowlist,
            resolved_markets,
            gamma,
        )
        if scoped_markets is None:
            positions = tuple(await position_client.positions(wallet))
        else:
            positions = tuple(
                await position_client.positions(
                    wallet,
                    condition_ids=tuple(
                        market.condition_id for market in scoped_markets
                    ),
                )
            )
        if allowlist is not None:
            # Keep the scope check at the normalized contract boundary too. A
            # compatible source must not be able to widen a filtered bootstrap.
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
        position_markets: list[Market] = []
        for position in positions:
            market = by_slug.get(position.market_slug)
            validate_position_market_identity(
                position,
                market,
                "current wallet position has unresolved market identity",
            )
            position_markets.append(market)
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
        for market in position_markets:
            registry.add(market, MarketInterest.FOLLOWED_WALLET, owner=wallet)
        clob.set_markets(registry.markets)
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
    registrations: list[tuple[str, Market]] = []
    for wallet, position in followed_wallets.tracked_market_positions():
        if position.market_slug in by_slug:
            registrations.append((wallet, by_slug[position.market_slug]))
    for wallet, market in registrations:
        registry.add(market, MarketInterest.FOLLOWED_WALLET, owner=wallet)


async def _resolve_scope_markets(
    allowlist: frozenset[str] | None,
    resolved_markets: tuple[Market, ...],
    gamma: MarketResolver,
) -> tuple[Market, ...] | None:
    """Resolve filtered wallet slugs before making the scoped position read."""
    if allowlist is None:
        return None
    by_slug = {market.slug: market for market in resolved_markets}
    requested = tuple(sorted(allowlist))
    missing = tuple(slug for slug in requested if slug not in by_slug)
    if missing:
        for market in await gamma.find_many(missing):
            if market is not None:
                by_slug[market.slug] = market
    unresolved = tuple(slug for slug in requested if slug not in by_slug)
    if unresolved:
        raise RuntimeError(
            "filtered wallet markets could not be resolved: "
            + ", ".join(unresolved)
        )
    return tuple(by_slug[slug] for slug in requested)
