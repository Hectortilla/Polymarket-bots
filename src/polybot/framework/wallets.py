from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Final


WALLET_ADDRESS_PATTERN: Final = re.compile(r"0x[a-fA-F0-9]{40}\Z")


def normalize_wallet_address(address: str) -> str:
    return address.lower()


def validate_wallet_address(address: str) -> str:
    normalized = address.strip()
    if WALLET_ADDRESS_PATTERN.fullmatch(normalized) is None:
        raise ValueError("wallet address must be a 0x-prefixed 20-byte address")
    return normalize_wallet_address(normalized)


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
