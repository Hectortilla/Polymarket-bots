"""Payload codec registry and structured-data dispatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
    TickSizeChangePayload,
)
from ..contracts.gaps import CoverageGapPayload
from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketMetadataPayload
from ..contracts.payloads import (
    RECORDED_PAYLOAD_TYPES,
    PublicTradePayload,
    RecordedPayload,
    ResolutionPayload,
)
from .book_codec import (
    decode_book_baseline,
    decode_book_delta,
    decode_tick_size_change,
    encode_book_baseline,
    encode_book_delta,
    encode_tick_size_change,
)
from .event_codec import (
    decode_coverage_gap,
    decode_public_trade,
    decode_resolution,
    encode_coverage_gap,
    encode_public_trade,
    encode_resolution,
)
from .market_codec import decode_market_metadata, encode_market_metadata


@dataclass(frozen=True, slots=True)
class PayloadCodec:
    kind: PayloadKind
    payload_type: type
    encode: Callable[[Any], dict[str, Any]]
    decode: Callable[[dict[str, Any]], RecordedPayload]


PAYLOAD_CODECS = (
    PayloadCodec(
        PayloadKind.MARKET_METADATA,
        MarketMetadataPayload,
        encode_market_metadata,
        decode_market_metadata,
    ),
    PayloadCodec(
        PayloadKind.BOOK_BASELINE,
        BookBaselinePayload,
        encode_book_baseline,
        decode_book_baseline,
    ),
    PayloadCodec(
        PayloadKind.BOOK_DELTA,
        BookDeltaPayload,
        encode_book_delta,
        decode_book_delta,
    ),
    PayloadCodec(
        PayloadKind.PUBLIC_TRADE,
        PublicTradePayload,
        encode_public_trade,
        decode_public_trade,
    ),
    PayloadCodec(
        PayloadKind.TICK_SIZE_CHANGE,
        TickSizeChangePayload,
        encode_tick_size_change,
        decode_tick_size_change,
    ),
    PayloadCodec(
        PayloadKind.RESOLUTION,
        ResolutionPayload,
        encode_resolution,
        decode_resolution,
    ),
    PayloadCodec(
        PayloadKind.COVERAGE_GAP,
        CoverageGapPayload,
        encode_coverage_gap,
        decode_coverage_gap,
    ),
)
_CODEC_BY_KIND = {codec.kind: codec for codec in PAYLOAD_CODECS}
_CODEC_BY_TYPE = {codec.payload_type: codec for codec in PAYLOAD_CODECS}

if len(_CODEC_BY_KIND) != len(PayloadKind) or frozenset(_CODEC_BY_TYPE) != frozenset(
    RECORDED_PAYLOAD_TYPES
):
    raise RuntimeError("recording payload codec registry is incomplete")


def payload_kind(payload: RecordedPayload) -> PayloadKind:
    return codec_for_payload(payload).kind


def encode_payload(payload: RecordedPayload) -> dict[str, Any]:
    return codec_for_payload(payload).encode(payload)


def decode_payload_data(
    kind: PayloadKind,
    data: dict[str, Any],
) -> RecordedPayload:
    return _CODEC_BY_KIND[kind].decode(data)


def codec_for_payload(payload: RecordedPayload) -> PayloadCodec:
    codec = _CODEC_BY_TYPE.get(type(payload))
    if codec is None:
        raise ValueError("recording payload type is unsupported")
    return codec
