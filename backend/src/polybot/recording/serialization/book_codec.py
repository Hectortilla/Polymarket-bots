"""Order-book recording payload codecs."""

from __future__ import annotations

from typing import Any

from ..contracts.book import (
    BookBaselinePayload,
    BookChange,
    BookDeltaPayload,
    RecordedBookLevel,
    TickSizeChangePayload,
)
from . import fields
from .parsing import (
    decimal_to_json,
    optional_decimal_from_json,
    optional_text,
    require_array,
    require_decimal,
    require_exact_keys,
    require_object,
    require_side,
    require_text,
)


def encode_book_baseline(payload: BookBaselinePayload) -> dict[str, Any]:
    return {
        fields.ASKS_FIELD: [_encode_level(level) for level in payload.asks],
        fields.BIDS_FIELD: [_encode_level(level) for level in payload.bids],
        fields.SOURCE_HASH_FIELD: payload.source_hash,
        fields.TOKEN_ID_FIELD: payload.token_id,
    }


def decode_book_baseline(data: dict[str, Any]) -> BookBaselinePayload:
    require_exact_keys(data, fields.BOOK_BASELINE_FIELDS)
    return BookBaselinePayload(
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "book token ID"),
        bids=tuple(
            _decode_level(value)
            for value in require_array(data[fields.BIDS_FIELD], "book bids")
        ),
        asks=tuple(
            _decode_level(value)
            for value in require_array(data[fields.ASKS_FIELD], "book asks")
        ),
        source_hash=optional_text(data[fields.SOURCE_HASH_FIELD], "book source hash"),
    )


def encode_book_delta(payload: BookDeltaPayload) -> dict[str, Any]:
    return {
        fields.CHANGES_FIELD: [_encode_change(change) for change in payload.changes]
    }


def decode_book_delta(data: dict[str, Any]) -> BookDeltaPayload:
    require_exact_keys(data, fields.BOOK_DELTA_FIELDS)
    return BookDeltaPayload(
        changes=tuple(
            _decode_change(value)
            for value in require_array(data[fields.CHANGES_FIELD], "book changes")
        )
    )


def encode_tick_size_change(payload: TickSizeChangePayload) -> dict[str, Any]:
    return {
        fields.NEW_TICK_SIZE_FIELD: str(payload.new_tick_size),
        fields.OLD_TICK_SIZE_FIELD: decimal_to_json(payload.old_tick_size),
        fields.TOKEN_ID_FIELD: payload.token_id,
    }


def decode_tick_size_change(data: dict[str, Any]) -> TickSizeChangePayload:
    require_exact_keys(data, fields.TICK_SIZE_CHANGE_FIELDS)
    return TickSizeChangePayload(
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "tick-size token ID"),
        old_tick_size=optional_decimal_from_json(
            data[fields.OLD_TICK_SIZE_FIELD], "old tick size"
        ),
        new_tick_size=require_decimal(
            data[fields.NEW_TICK_SIZE_FIELD], "new tick size"
        ),
    )


def _encode_level(level: RecordedBookLevel) -> dict[str, str]:
    return {
        fields.PRICE_FIELD: str(level.price),
        fields.SIZE_FIELD: str(level.size),
    }


def _decode_level(value: object) -> RecordedBookLevel:
    data = require_object(value, "book level")
    require_exact_keys(data, fields.BOOK_LEVEL_FIELDS)
    return RecordedBookLevel(
        price=require_decimal(data[fields.PRICE_FIELD], "book price"),
        size=require_decimal(data[fields.SIZE_FIELD], "book size"),
    )


def _encode_change(change: BookChange) -> dict[str, Any]:
    return {
        fields.BEST_ASK_FIELD: decimal_to_json(change.best_ask),
        fields.BEST_BID_FIELD: decimal_to_json(change.best_bid),
        fields.PRICE_FIELD: str(change.price),
        fields.SIDE_FIELD: change.side.value,
        fields.SIZE_FIELD: str(change.size),
        fields.SOURCE_HASH_FIELD: change.source_hash,
        fields.TOKEN_ID_FIELD: change.token_id,
    }


def _decode_change(value: object) -> BookChange:
    data = require_object(value, "book change")
    require_exact_keys(data, fields.BOOK_CHANGE_FIELDS)
    return BookChange(
        token_id=require_text(data[fields.TOKEN_ID_FIELD], "book change token ID"),
        side=require_side(data[fields.SIDE_FIELD]),
        price=require_decimal(data[fields.PRICE_FIELD], "book change price"),
        size=require_decimal(data[fields.SIZE_FIELD], "book change size"),
        source_hash=optional_text(data[fields.SOURCE_HASH_FIELD], "change source hash"),
        best_bid=optional_decimal_from_json(data[fields.BEST_BID_FIELD], "best bid"),
        best_ask=optional_decimal_from_json(data[fields.BEST_ASK_FIELD], "best ask"),
    )
