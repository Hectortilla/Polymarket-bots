from __future__ import annotations

import re
from typing import Final


WALLET_ADDRESS_PATTERN_TEXT: Final = r"0x[a-fA-F0-9]{40}"
WALLET_ADDRESS_SCHEMA_PATTERN: Final = f"^(?:{WALLET_ADDRESS_PATTERN_TEXT})$"
WALLET_ADDRESS_PATTERN: Final = re.compile(WALLET_ADDRESS_PATTERN_TEXT)


def normalize_wallet_address(address: str) -> str:
    return address.lower()


def validate_wallet_address(address: str) -> str:
    normalized = address.strip()
    if WALLET_ADDRESS_PATTERN.fullmatch(normalized) is None:
        raise ValueError("wallet address must be a 0x-prefixed 20-byte address")
    return normalize_wallet_address(normalized)
