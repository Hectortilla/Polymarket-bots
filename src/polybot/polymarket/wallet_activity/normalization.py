from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite

from polybot.framework.events import Side
from polybot.framework.events.wallet_trades import WalletTradeEvent, WalletTradeKind
from polybot.framework.wallets import normalize_wallet_address
from polybot.polymarket.normalization.values import normalize_text_or_none

from .fields import (
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_OUTCOME_FIELD,
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
    SDK_CONDITION_ID_ATTRIBUTE,
    SDK_SHARES_ATTRIBUTE,
    SDK_SIDE_ATTRIBUTE,
    SDK_SIZE_ATTRIBUTE,
    SDK_TIMESTAMP_ATTRIBUTE,
    SDK_TOKEN_ID_ATTRIBUTE,
    SDK_TRANSACTION_HASH_ATTRIBUTE,
    SDK_WALLET_ATTRIBUTE,
    TRADE_ACTIVITY_TYPE,
)

EPOCH_SECONDS_INTERPRETATION_CUTOFF = 10_000_000_000
WALLET_TRADE_SOURCE_ID_VERSION = "wallet-trade-v1"
_TRADE_FIELD_ALIASES = {
    SDK_WALLET_ATTRIBUTE: PROXY_WALLET_FIELD,
    SDK_CONDITION_ID_ATTRIBUTE: CONDITION_ID_FIELD,
    SDK_TOKEN_ID_ATTRIBUTE: ACTIVITY_TOKEN_ID_FIELD,
    SDK_TRANSACTION_HASH_ATTRIBUTE: ACTIVITY_TRANSACTION_HASH_FIELD,
    SDK_SIDE_ATTRIBUTE: ACTIVITY_SIDE_FIELD,
    SDK_SIZE_ATTRIBUTE: ACTIVITY_SIZE_FIELD,
    SDK_TIMESTAMP_ATTRIBUTE: ACTIVITY_TIMESTAMP_FIELD,
}
_MISSING_TRADE_FIELD = object()


def _get_trade_field(source: object, name: str) -> object:
    if isinstance(source, dict):
        alias = _TRADE_FIELD_ALIASES.get(name)
        primary = source.get(name, _MISSING_TRADE_FIELD)
        if alias is None or alias == name:
            return None if primary is _MISSING_TRADE_FIELD else primary
        secondary = source.get(alias, _MISSING_TRADE_FIELD)
        if primary is _MISSING_TRADE_FIELD:
            return None if secondary is _MISSING_TRADE_FIELD else secondary
        if secondary is _MISSING_TRADE_FIELD:
            return primary
        return primary if _aliases_agree(name, primary, secondary) else None
    return getattr(source, name, None)


def _has_trade_field(source: object, name: str) -> bool:
    if isinstance(source, dict):
        alias = _TRADE_FIELD_ALIASES.get(name)
        return name in source or (alias is not None and alias in source)
    return hasattr(source, name)


def _timestamp_ms(value: object) -> int | None:
    if isinstance(value, datetime):
        try:
            if value.tzinfo is None or value.utcoffset() is None:
                return None
            return int(value.timestamp() * 1000)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (OverflowError, TypeError, ValueError):
        return None
    if not isfinite(seconds) or seconds < 0:
        return None
    return (
        int(seconds * 1000)
        if seconds < EPOCH_SECONDS_INTERPRETATION_CUTOFF
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
    wallet = _get_trade_field(source, SDK_WALLET_ATTRIBUTE)
    condition_id = _get_trade_field(source, SDK_CONDITION_ID_ATTRIBUTE)
    token_id = _get_trade_field(source, SDK_TOKEN_ID_ATTRIBUTE)
    side = _get_trade_field(source, SDK_SIDE_ATTRIBUTE)
    size = _normalized_trade_size(
        _get_trade_field(source, SDK_SIZE_ATTRIBUTE),
        _get_trade_field(source, SDK_SHARES_ATTRIBUTE),
    )
    price = _get_trade_field(source, ACTIVITY_PRICE_FIELD)
    normalized_size = size
    normalized_price = _decimal(price)
    timestamp = _timestamp_ms(
        _get_trade_field(source, SDK_TIMESTAMP_ATTRIBUTE)
    )
    raw_outcome = _get_trade_field(source, ACTIVITY_OUTCOME_FIELD)
    outcome = _normalized_text(raw_outcome)
    raw_activity_type = _get_trade_field(source, ACTIVITY_TYPE_FIELD)
    activity_type = _normalized_text(raw_activity_type)
    transaction_hash = _normalized_text(
        _get_trade_field(source, SDK_TRANSACTION_HASH_ATTRIBUTE)
    )
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
        or (
            _has_trade_field(source, ACTIVITY_TYPE_FIELD)
            and (activity_type is None or activity_type.upper() != TRADE_ACTIVITY_TYPE)
        )
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
            market_slug=_normalized_text(
                _get_trade_field(source, ACTIVITY_SLUG_FIELD)
            ),
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
    wallet = _normalized_text(source.wallet)
    condition_id = _normalized_text(source.condition_id)
    token_id = _normalized_text(source.token_id)
    source_id = _normalized_text(source.source_id)
    if None in (wallet, condition_id, token_id, source_id):
        return None
    normalized_outcome = _normalized_text(source.outcome)
    if source.outcome is not None and normalized_outcome is None:
        return None
    if not source.is_valid() or not isinstance(source.side, Side):
        return None
    upstream_source_id = _normalized_text(source.transaction_hash) or source_id
    event = replace(
        source,
        wallet=normalize_wallet_address(wallet),
        condition_id=condition_id,
        token_id=token_id,
        market_slug=_normalized_text(source.market_slug),
        transaction_hash=_normalized_text(source.transaction_hash),
        outcome=normalized_outcome,
        observed_at_ms=observed_at_ms,
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


def _normalized_text(value: object) -> str | None:
    return normalize_text_or_none(value)


def _aliases_agree(name: str, primary: object, secondary: object) -> bool:
    first = _normalized_text(primary)
    second = _normalized_text(secondary)
    if name == SDK_WALLET_ATTRIBUTE:
        return (
            first is not None
            and second is not None
            and first.casefold() == second.casefold()
        )
    return first is not None and first == second


def _normalized_trade_size(size: object, shares: object) -> Decimal | None:
    """Accept one size field, or two agreeing representations of it."""
    normalized_size = _decimal(size)
    normalized_shares = _decimal(shares)
    if size is None:
        return normalized_shares
    if shares is None:
        return normalized_size
    if normalized_size is None or normalized_shares is None:
        return None
    return normalized_size if normalized_size == normalized_shares else None


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
