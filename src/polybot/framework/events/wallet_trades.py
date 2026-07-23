from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from polybot.framework.events import Side
from polybot.framework.events.prices import (
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
)
from polybot.framework.wallets import normalize_wallet_address


WALLET_SOURCE_KEY_SEPARATOR: Final = "\0"


class WalletTradeKind(StrEnum):
    TRADE = "trade"
    BACKFILL = "backfill"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class WalletTradeEvent:
    wallet: str
    condition_id: str
    token_id: str
    side: Side
    size: Decimal
    price: Decimal
    source_id: str
    trade_timestamp_ms: int
    observed_at_ms: int
    kind: WalletTradeKind = WalletTradeKind.TRADE
    market_slug: str | None = None
    transaction_hash: str | None = None
    outcome: str | None = None

    def is_valid(self) -> bool:
        try:
            return (
                bool(self.wallet)
                and bool(self.condition_id)
                and bool(self.token_id)
                and isinstance(self.side, Side)
                and self.size.is_finite()
                and self.price.is_finite()
                and self.size > OUTCOME_PRICE_FLOOR
                and OUTCOME_PRICE_FLOOR < self.price <= OUTCOME_PRICE_CEILING
                and bool(self.source_id)
                and WALLET_SOURCE_KEY_SEPARATOR not in self.source_id
                and isinstance(self.trade_timestamp_ms, int)
                and not isinstance(self.trade_timestamp_ms, bool)
                and isinstance(self.observed_at_ms, int)
                and not isinstance(self.observed_at_ms, bool)
                and self.trade_timestamp_ms >= 0
                and self.observed_at_ms >= self.trade_timestamp_ms
            )
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return False

    @property
    def source_key(self) -> str:
        return wallet_source_key(self.wallet, self.source_id)


def wallet_source_key(wallet: str, source_id: str) -> str:
    if not source_id or WALLET_SOURCE_KEY_SEPARATOR in source_id:
        raise ValueError("wallet trade source ID must not contain the source-key separator")
    return f"{normalize_wallet_address(wallet)}{WALLET_SOURCE_KEY_SEPARATOR}{source_id}"


def source_key_belongs_to_wallet(wallet: str, source_key: str) -> bool:
    """Return whether a strict encoded source key belongs to one wallet."""
    parsed = parse_wallet_source_key(source_key)
    return parsed is not None and parsed[0] == normalize_wallet_address(wallet)


def parse_wallet_source_key(source_key: str) -> tuple[str, str] | None:
    """Parse the single-separator wallet/source identifier used for deduping."""
    if not isinstance(source_key, str):
        return None
    wallet, separator, source_id = source_key.partition(WALLET_SOURCE_KEY_SEPARATOR)
    if (
        not separator
        or not wallet
        or not source_id
        or WALLET_SOURCE_KEY_SEPARATOR in source_id
    ):
        return None
    return normalize_wallet_address(wallet), source_id
