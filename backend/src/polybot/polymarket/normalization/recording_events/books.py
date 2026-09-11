from __future__ import annotations

from polybot.polymarket.markets import Market
from polybot.polymarket.normalization.book import normalize_price_change_level
from polybot.polymarket.normalization.market_data_fields import (
    optional_outcome_payout,
    require_outcome_price,
    require_positive_market_decimal,
    validate_optional_text,
)
from polybot.polymarket.normalization.recording_events.fields import normalize_side
from polybot.polymarket.normalization.recording_events.identity import (
    _condition_id,
    _identity,
    _token_id,
)
from polybot.polymarket.normalization.timestamps import datetime_to_epoch_ms
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookChange,
    BookDeltaPayload,
    RecordedBookLevel,
)

from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketPriceChangeEvent,
)
from polymarket.models.clob.order_book import OrderBookLevel


def _book_event(event: MarketBookEvent, market: Market) -> CapturedMarketEvent:
    payload = event.payload
    _condition_id(payload.market, market)
    token_id = _token_id(payload.token_id, market)
    return CapturedMarketEvent(
        source_timestamp_ms=datetime_to_epoch_ms(payload.timestamp),
        identity=_identity(market, token_id),
        payload=BookBaselinePayload(
            token_id=token_id,
            bids=_levels(payload.bids),
            asks=_levels(payload.asks),
            source_hash=validate_optional_text(payload.hash, "book hash"),
        ),
    )


def _price_change_event(
    event: MarketPriceChangeEvent,
    market: Market,
) -> CapturedMarketEvent:
    payload = event.payload
    _condition_id(payload.market, market)
    changes: list[BookChange] = []
    for source in payload.price_changes:
        token_id = _token_id(source.token_id, market)
        level = normalize_price_change_level(price=source.price, size=source.size)
        changes.append(
            BookChange(
                token_id=token_id,
                side=normalize_side(source.side),
                price=level.price,
                size=level.size,
                source_hash=validate_optional_text(source.hash, "price-change hash"),
                best_bid=optional_outcome_payout(source.best_bid, "best bid"),
                best_ask=optional_outcome_payout(source.best_ask, "best ask"),
            )
        )
    return CapturedMarketEvent(
        source_timestamp_ms=datetime_to_epoch_ms(payload.timestamp),
        identity=_identity(market),
        payload=BookDeltaPayload(changes=tuple(changes)),
    )


def _levels(source: tuple[OrderBookLevel, ...]) -> tuple[RecordedBookLevel, ...]:
    levels: list[RecordedBookLevel] = []
    for level in source:
        price = require_outcome_price(level.price, "book price")
        size = require_positive_market_decimal(level.size, "book size")
        levels.append(RecordedBookLevel(price=price, size=size))
    return tuple(levels)
