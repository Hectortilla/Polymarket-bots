from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from polybot.framework.events import Side
from polybot.framework.events.prices import (
    OUTCOME_PRICE_FLOOR,
    is_outcome_price,
)
from polybot.framework.wallets import normalize_wallet_address
from polybot.framework.timestamps import is_nonnegative_timestamp


WALLET_SOURCE_KEY_SEPARATOR: Final = "\0"


class WalletTradeKind(StrEnum):
    TRADE = "trade"
    BACKFILL = "backfill"
    RECONCILIATION = "reconciliation"


class WalletTradeValidationIssue(StrEnum):
    INVALID = "wallet_trade_invalid"
    FUTURE_DATED = "wallet_trade_future_dated"
    STALE = "wallet_trade_stale"


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
                and self.size > OUTCOME_PRICE_FLOOR
                and is_outcome_price(self.price)
                and bool(self.source_id)
                and WALLET_SOURCE_KEY_SEPARATOR not in self.source_id
                and is_nonnegative_timestamp(self.trade_timestamp_ms)
                and is_nonnegative_timestamp(self.observed_at_ms)
                and self.observed_at_ms >= self.trade_timestamp_ms
            )
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return False

    def validation_issue(
        self,
        now_ms: int,
        max_age_ms: int,
    ) -> WalletTradeValidationIssue | None:
        if not self.is_valid():
            return WalletTradeValidationIssue.INVALID
        return self.freshness_issue(now_ms, max_age_ms)

    def freshness_issue(
        self,
        now_ms: int,
        max_age_ms: int,
    ) -> WalletTradeValidationIssue | None:
        """Recheck time-sensitive validity after awaited decision work."""
        if self.observed_at_ms > now_ms:
            return WalletTradeValidationIssue.FUTURE_DATED
        if now_ms - self.observed_at_ms > max_age_ms:
            return WalletTradeValidationIssue.STALE
        if self.observed_at_ms - self.trade_timestamp_ms > max_age_ms:
            return WalletTradeValidationIssue.STALE
        return None

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
