from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WalletSubscription:
    address: str
    role: str = "leader"


@dataclass(frozen=True, slots=True)
class WalletPlan:
    current: tuple[WalletSubscription, ...]

    @property
    def active_addresses(self) -> frozenset[str]:
        return frozenset(wallet.address.lower() for wallet in self.current)


def subscriptions_from_addresses(
    addresses: tuple[str, ...],
) -> tuple[WalletSubscription, ...]:
    normalized_addresses = dict.fromkeys(address.lower() for address in addresses)
    return tuple(
        WalletSubscription(address=address) for address in normalized_addresses
    )
