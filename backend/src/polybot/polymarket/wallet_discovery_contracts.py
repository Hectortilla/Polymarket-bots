"""Package-owned wallet choices for discovery interfaces."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WalletSuggestion:
    address: str
    name: str | None


@dataclass(frozen=True, slots=True)
class WalletSearchResults:
    wallets: tuple[WalletSuggestion, ...]
    has_more: bool
