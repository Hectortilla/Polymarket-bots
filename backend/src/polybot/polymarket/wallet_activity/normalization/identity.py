from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

from polybot.framework.wallets import normalize_wallet_address
from polybot.polymarket.normalization.market_data_fields import normalize_text_or_none

WALLET_TRADE_SOURCE_ID_VERSION = "wallet-trade-v1"


def _canonical_source_id(
    *,
    wallet: str,
    condition_id: str,
    token_id: str,
    side: object,
    size: Decimal,
    price: Decimal,
    trade_timestamp_ms: int,
    upstream_source_id: str,
) -> str:
    parts = (
        WALLET_TRADE_SOURCE_ID_VERSION,
        normalize_wallet_address(wallet),
        condition_id,
        token_id,
        str(side).upper(),
        format(size.normalize(), "f"),
        format(price.normalize(), "f"),
        str(trade_timestamp_ms),
        upstream_source_id,
    )
    return sha256("\0".join(parts).encode()).hexdigest()


def _normalized_transaction_hash(value: object) -> str | None:
    normalized = normalize_text_or_none(value)
    return None if normalized is None else normalized.casefold()
