from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


def normalize_wallet_address(address: str) -> str:
    return address.lower()


class WalletSubscriptionRole(StrEnum):
    LEADER = "leader"


@dataclass(frozen=True, slots=True)
class WalletSubscription:
    address: str
    role: WalletSubscriptionRole = WalletSubscriptionRole.LEADER

    @classmethod
    def from_addresses(
        cls,
        addresses: tuple[str, ...],
    ) -> tuple[WalletSubscription, ...]:
        normalized_addresses = dict.fromkeys(
            normalize_wallet_address(address) for address in addresses
        )
        return tuple(cls(address=address) for address in normalized_addresses)


@dataclass(frozen=True, slots=True)
class WalletPlan:
    current: tuple[WalletSubscription, ...]

    @property
    def active_addresses(self) -> frozenset[str]:
        return frozenset(
            normalize_wallet_address(wallet.address) for wallet in self.current
        )

    def accepts_address(self, wallet: str) -> bool:
        active_addresses = self.active_addresses
        if not active_addresses:
            return True
        return normalize_wallet_address(wallet) in active_addresses
