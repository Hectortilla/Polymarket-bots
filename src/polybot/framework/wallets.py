from __future__ import annotations

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
