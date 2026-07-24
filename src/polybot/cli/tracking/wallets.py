"""Followed-wallet discovery and bootstrap tracking."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from polybot.async_io import run_blocking
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.positions.client import PositionClient
from polybot.polymarket.positions.contracts import Position
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.markets import Market

from ..followed_wallets.position_contracts import FollowPosition
from ..markets import MarketResolver
from ..market_identity import MarketIdentity
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


class FollowedWalletSynchronizer:
    """Own followed-wallet bootstrap collaborators and synchronization."""

    def __init__(
        self,
        followed_wallets: FollowedWalletStore,
        position_client: PositionClient,
        gamma: MarketResolver,
        clob: ClobClient,
        registry: TrackedMarketRegistry,
    ) -> None:
        self._followed_wallets = followed_wallets
        self._position_client = position_client
        self._gamma = gamma
        self._clob = clob
        self._registry = registry

    async def synchronize(
        self,
        wallet_scopes: dict[str, frozenset[str] | None],
        *,
        resolved_markets: tuple[Market, ...] = (),
    ) -> None:
        new_wallets = (
            ()
            if not wallet_scopes
            else await run_blocking(
                self._followed_wallets.synchronize,
                tuple(wallet_scopes),
            )
        )
        for wallet in new_wallets:
            await self._bootstrap(
                wallet,
                allowlist=wallet_scopes[wallet],
                resolved_markets=resolved_markets,
            )
        await self._register_persisted_markets()

    async def _bootstrap(
        self,
        wallet: str,
        *,
        allowlist: frozenset[str] | None,
        resolved_markets: tuple[Market, ...],
    ) -> None:
        """Capture a newly followed wallet's current positions and marks."""
        scoped_markets = await self._resolve_scope_markets(
            allowlist,
            resolved_markets,
        )
        if scoped_markets is None:
            positions = tuple(await self._position_client.positions(wallet))
        else:
            positions = tuple(
                await self._position_client.positions(
                    wallet,
                    condition_ids=tuple(
                        market.condition_id for market in scoped_markets
                    ),
                )
            )
        if allowlist is not None:
            positions = tuple(
                position
                for position in positions
                if position.market_slug in allowlist
            )
        markets = await self._gamma.find_many(
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
            if market is None or not MarketIdentity.from_position(position).matches(
                market
            ):
                raise RuntimeError(
                    "current wallet position has unresolved market identity"
                )
            position_markets.append(market)
        marked_positions = []
        for position in positions:
            book = await self._clob.latest(position.token_id)
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
            self._registry.add(
                market,
                MarketInterest.FOLLOWED_WALLET,
                owner=wallet,
            )
        self._clob.set_markets(self._registry.markets)
        await run_blocking(
            self._followed_wallets.bootstrap,
            wallet,
            tuple(marked_positions),
        )

    async def _register_persisted_markets(self) -> None:
        """Re-register markets referenced by persisted followed positions."""
        known_slugs = {market.slug for market in self._registry.markets}
        persisted_slugs = tuple(
            slug
            for slug in self._followed_wallets.open_market_slugs()
            if slug not in known_slugs
        )
        if not persisted_slugs:
            return
        markets = await self._gamma.find_many(persisted_slugs)
        by_slug = {market.slug: market for market in markets if market is not None}
        missing = [slug for slug in persisted_slugs if slug not in by_slug]
        if missing:
            raise RuntimeError(
                "persisted followed-wallet markets could not be resolved: "
                + ", ".join(missing)
            )
        for wallet, position in self._followed_wallets.tracked_market_positions():
            market = by_slug.get(position.market_slug)
            if market is not None:
                self._registry.add(
                    market,
                    MarketInterest.FOLLOWED_WALLET,
                    owner=wallet,
                )

    async def _resolve_scope_markets(
        self,
        allowlist: frozenset[str] | None,
        resolved_markets: tuple[Market, ...],
    ) -> tuple[Market, ...] | None:
        if allowlist is None:
            return None
        by_slug = {market.slug: market for market in resolved_markets}
        requested = tuple(sorted(allowlist))
        missing = tuple(slug for slug in requested if slug not in by_slug)
        if missing:
            for market in await self._gamma.find_many(missing):
                if market is not None:
                    by_slug[market.slug] = market
        unresolved = tuple(slug for slug in requested if slug not in by_slug)
        if unresolved:
            raise RuntimeError(
                "filtered wallet markets could not be resolved: "
                + ", ".join(unresolved)
            )
        return tuple(by_slug[slug] for slug in requested)
