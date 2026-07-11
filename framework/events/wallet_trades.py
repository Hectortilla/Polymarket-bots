from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from bots.framework.events import Side
from bots.framework.events.books import PRICE_CEILING, PRICE_FLOOR
from bots.framework.wallets import normalize_wallet_address


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
                and self.size > PRICE_FLOOR
                and PRICE_FLOOR < self.price <= PRICE_CEILING
                and bool(self.source_id)
                and self.trade_timestamp_ms >= 0
                and self.observed_at_ms >= self.trade_timestamp_ms
            )
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return False

    @property
    def source_key(self) -> str:
        return wallet_source_key(self.wallet, self.source_id)


def wallet_source_key(wallet: str, source_id: str) -> str:
    return f"{normalize_wallet_address(wallet)}\0{source_id}"
