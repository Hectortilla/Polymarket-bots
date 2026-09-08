from __future__ import annotations

from dataclasses import replace

from polybot.framework.events import Side
from polybot.framework.events.wallet_trades import WalletTradeEvent, WalletTradeKind
from polybot.framework.wallets import validate_wallet_address
from polybot.polymarket.normalization.values import normalize_text_or_none
from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_TYPE_FIELD,
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
from polybot.polymarket.wallet_activity.normalization.identity import (
    _canonical_source_id,
    _normalized_transaction_hash,
)
from polybot.polymarket.wallet_activity.normalization.source_fields import (
    _decimal,
    _get_trade_field,
    _has_trade_field,
    _normalized_trade_size,
    _timestamp_ms,
)


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
    trade_timestamp_ms = _timestamp_ms(
        _get_trade_field(source, SDK_TIMESTAMP_ATTRIBUTE)
    )
    raw_outcome = _get_trade_field(source, ACTIVITY_OUTCOME_FIELD)
    outcome = normalize_text_or_none(raw_outcome)
    raw_activity_type = _get_trade_field(source, ACTIVITY_TYPE_FIELD)
    activity_type = normalize_text_or_none(raw_activity_type)
    transaction_hash = _normalized_transaction_hash(
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
        or trade_timestamp_ms is None
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
            wallet=validate_wallet_address(wallet),
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
                trade_timestamp_ms=trade_timestamp_ms,
                upstream_source_id=upstream_source_id,
            ),
            trade_timestamp_ms=trade_timestamp_ms,
            observed_at_ms=observed_at_ms,
            kind=kind,
            market_slug=normalize_text_or_none(
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
    wallet = normalize_text_or_none(source.wallet)
    condition_id = normalize_text_or_none(source.condition_id)
    token_id = normalize_text_or_none(source.token_id)
    source_id = normalize_text_or_none(source.source_id)
    transaction_hash = _normalized_transaction_hash(source.transaction_hash)
    if None in (wallet, condition_id, token_id, source_id, transaction_hash):
        return None
    try:
        wallet = validate_wallet_address(wallet)
    except ValueError:
        return None
    normalized_outcome = normalize_text_or_none(source.outcome)
    if source.outcome is not None and normalized_outcome is None:
        return None
    if not source.is_valid() or not isinstance(source.side, Side):
        return None
    event = replace(
        source,
        wallet=validate_wallet_address(wallet),
        condition_id=condition_id,
        token_id=token_id,
        market_slug=normalize_text_or_none(source.market_slug),
        transaction_hash=transaction_hash,
        outcome=normalized_outcome,
        observed_at_ms=observed_at_ms,
        source_id=_canonical_source_id(
            wallet=wallet,
            condition_id=condition_id,
            token_id=token_id,
            side=source.side.value,
            size=source.size,
            price=source.price,
            trade_timestamp_ms=source.trade_timestamp_ms,
            upstream_source_id=transaction_hash,
        ),
    )
    return event if event.is_valid() else None


def sort_key(trade: WalletTradeEvent) -> tuple[int, str, str, str]:
    return (
        trade.trade_timestamp_ms,
        trade.transaction_hash or trade.source_id,
        trade.token_id,
        trade.wallet,
    )
