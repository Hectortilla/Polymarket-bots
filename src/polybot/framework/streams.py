from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from polybot.framework.wallets import normalize_wallet_address


class StreamRelation(StrEnum):
    FILTERED = "filtered"
    INDEPENDENT = "independent"


@dataclass(frozen=True, slots=True)
class StreamScope:
    wallet_address: str | None = None
    market_slugs: tuple[str, ...] = ()

    def accepts_trade(self, wallet: str, market_slug: str | None) -> bool:
        wallet_matches = (
            self.wallet_address is None
            or normalize_wallet_address(wallet) == self.wallet_address
        )
        market_matches = (
            not self.market_slugs
            or market_slug is not None
            and market_slug in self.market_slugs
        )
        return wallet_matches and market_matches


@dataclass(frozen=True, slots=True)
class StreamRule:
    relation: StreamRelation
    market_slugs: tuple[str, ...] = ()
    wallet_addresses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        markets = tuple(dict.fromkeys(slug.strip() for slug in self.market_slugs if slug.strip()))
        wallets = tuple(
            dict.fromkeys(normalize_wallet_address(wallet.strip()) for wallet in self.wallet_addresses if wallet.strip())
        )
        if markets != self.market_slugs or wallets != self.wallet_addresses:
            object.__setattr__(self, "market_slugs", markets)
            object.__setattr__(self, "wallet_addresses", wallets)
        if self.relation is StreamRelation.FILTERED and (not markets or not wallets):
            raise ValueError("filtered stream rules require markets and wallets")
        if self.relation is StreamRelation.INDEPENDENT and not (markets or wallets):
            raise ValueError("independent stream rules require markets or wallets")

    def accepts_trade(self, wallet: str, market_slug: str | None) -> bool:
        return any(scope.accepts_trade(wallet, market_slug) for scope in self.scopes)

    @property
    def scopes(self) -> tuple[StreamScope, ...]:
        if self.relation is StreamRelation.FILTERED:
            return tuple(
                StreamScope(wallet_address=wallet, market_slugs=self.market_slugs)
                for wallet in self.wallet_addresses
            )
        scopes = [
            StreamScope(wallet_address=wallet)
            for wallet in self.wallet_addresses
        ]
        if self.market_slugs:
            scopes.append(StreamScope(market_slugs=self.market_slugs))
        return tuple(scopes)


@dataclass(frozen=True, slots=True)
class StreamPlan:
    current: tuple[StreamRule, ...]
    next: tuple[StreamRule, ...] = ()

    @property
    def current_market_slugs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(slug for rule in self.current for slug in rule.market_slugs))

    @property
    def next_market_slugs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(slug for rule in self.next for slug in rule.market_slugs))

    @property
    def current_wallet_addresses(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(wallet for rule in self.current for wallet in rule.wallet_addresses))

    def wallet_discovery_scopes(self) -> dict[str, frozenset[str] | None]:
        scopes: dict[str, set[str] | None] = {}
        for rule in self.current:
            for scope in rule.scopes:
                wallet = scope.wallet_address
                if wallet is None:
                    continue
                if not scope.market_slugs:
                    scopes[wallet] = None
                elif wallet not in scopes:
                    scopes[wallet] = set(scope.market_slugs)
                elif scopes[wallet] is not None:
                    scopes[wallet].update(scope.market_slugs)
        return {
            wallet: None if slugs is None else frozenset(slugs)
            for wallet, slugs in scopes.items()
        }

    def accepts_book(self, market_slug: str | None) -> bool:
        if not self.current:
            return True
        return market_slug is not None and market_slug in self.current_market_slugs

    def accepts_trade(self, wallet: str, market_slug: str | None) -> bool:
        if not self.current:
            return True
        return any(rule.accepts_trade(wallet, market_slug) for rule in self.current)
