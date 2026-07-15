from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite

from polybot.framework.events import Side
from polybot.framework.events.wallet_trades import WalletTradeEvent, WalletTradeKind
from polybot.framework.wallets import normalize_wallet_address

from .constants import (
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_OUTCOME_FIELD,
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
)

MILLISECONDS_TIMESTAMP_THRESHOLD = 10_000_000_000
WALLET_TRADE_SOURCE_ID_VERSION = "wallet-trade-v1"


def _get_trade_field(source: object, name: str) -> object:
    if isinstance(source, dict):
        aliases = {
            "wallet": PROXY_WALLET_FIELD,
            "condition_id": CONDITION_ID_FIELD,
            "token_id": ACTIVITY_TOKEN_ID_FIELD,
            "transaction_hash": ACTIVITY_TRANSACTION_HASH_FIELD,
            "side": ACTIVITY_SIDE_FIELD,
            "size": ACTIVITY_SIZE_FIELD,
            "timestamp": ACTIVITY_TIMESTAMP_FIELD,
        }
        return source.get(name, source.get(aliases.get(name, name)))
    return getattr(source, name, None)


def _timestamp_ms(value: object) -> int | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not isfinite(seconds) or seconds < 0:
        return None
    return (
        int(seconds * 1000)
        if seconds < MILLISECONDS_TIMESTAMP_THRESHOLD
        else int(seconds)
    )


def _decimal(value: object) -> Decimal | None:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def normalize_wallet_trade(
    source: object,
    *,
    observed_at_ms: int,
    kind: WalletTradeKind = WalletTradeKind.BACKFILL,
) -> WalletTradeEvent | None:
    """Convert an external wallet trade row into the package event contract."""
    wallet = _get_trade_field(source, "wallet")
    condition_id = _get_trade_field(source, "condition_id")
    token_id = _get_trade_field(source, "token_id")
    side = _get_trade_field(source, "side")
    size = _get_trade_field(source, "size") or _get_trade_field(source, "shares")
    price = _get_trade_field(source, "price")
    normalized_size = _decimal(size)
    normalized_price = _decimal(price)
    timestamp = _timestamp_ms(_get_trade_field(source, "timestamp"))
    raw_outcome = _get_trade_field(source, ACTIVITY_OUTCOME_FIELD)
    outcome = _optional_text(raw_outcome)
    transaction_hash = _optional_text(_get_trade_field(source, "transaction_hash"))
    upstream_source_id = transaction_hash
    required_fields = (wallet, condition_id, token_id, upstream_source_id)
    if not all(isinstance(value, str) for value in required_fields):
        return None
    normalized_fields = tuple(value.strip() for value in required_fields)
    if (
        not all(normalized_fields)
        or not isinstance(side, str)
        or timestamp is None
        or (raw_outcome is not None and outcome is None)
    ):
        return None
    wallet, condition_id, token_id, upstream_source_id = normalized_fields
    if normalized_size is None or normalized_price is None:
        return None
    try:
        event = WalletTradeEvent(
            wallet=normalize_wallet_address(wallet),
            condition_id=condition_id,
            token_id=token_id,
            side=Side(side.upper()),
            size=normalized_size,
            price=normalized_price,
            source_id=_canonical_source_id(
                wallet=wallet,
                condition_id=condition_id,
                token_id=token_id,
                side=side,
                size=normalized_size,
                price=normalized_price,
                timestamp=timestamp,
                upstream_source_id=upstream_source_id,
            ),
            trade_timestamp_ms=timestamp,
            observed_at_ms=observed_at_ms,
            kind=kind,
            market_slug=_optional_text(_get_trade_field(source, "slug")),
            transaction_hash=transaction_hash,
            outcome=outcome,
        )
    except (TypeError, ValueError):
        return None
    return event if event.is_valid() else None


def normalize_stream_event(
    source: object,
    *,
    observed_at_ms: int,
) -> WalletTradeEvent | None:
    if not isinstance(source, WalletTradeEvent):
        return normalize_wallet_trade(
            source,
            observed_at_ms=observed_at_ms,
            kind=WalletTradeKind.TRADE,
        )
    wallet = _required_text(source.wallet)
    condition_id = _required_text(source.condition_id)
    token_id = _required_text(source.token_id)
    source_id = _required_text(source.source_id)
    if None in (wallet, condition_id, token_id, source_id):
        return None
    normalized_outcome = _optional_text(source.outcome)
    if source.outcome is not None and normalized_outcome is None:
        return None
    if not source.is_valid() or not isinstance(source.side, Side):
        return None
    upstream_source_id = _optional_text(source.transaction_hash) or source_id
    event = replace(
        source,
        wallet=normalize_wallet_address(wallet),
        condition_id=condition_id,
        token_id=token_id,
        market_slug=_optional_text(source.market_slug),
        transaction_hash=_optional_text(source.transaction_hash),
        outcome=normalized_outcome,
        source_id=_canonical_source_id(
            wallet=wallet,
            condition_id=condition_id,
            token_id=token_id,
            side=source.side.value,
            size=source.size,
            price=source.price,
            timestamp=source.trade_timestamp_ms,
            upstream_source_id=upstream_source_id,
        ),
    )
    return event if event.is_valid() else None


def _required_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def sort_key(trade: WalletTradeEvent) -> tuple[int, str, str, str]:
    return (
        trade.trade_timestamp_ms,
        trade.transaction_hash or trade.source_id,
        trade.token_id,
        trade.wallet,
    )


def _canonical_source_id(
    *,
    wallet: str,
    condition_id: str,
    token_id: str,
    side: object,
    size: Decimal,
    price: Decimal,
    timestamp: int,
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
        str(timestamp),
        upstream_source_id,
    )
    return sha256("\0".join(parts).encode()).hexdigest()
