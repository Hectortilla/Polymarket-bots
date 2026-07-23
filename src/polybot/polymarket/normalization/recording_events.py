"""Normalize official market-channel events for lossless recording."""

from __future__ import annotations

from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketEvent,
    MarketLastTradePriceEvent,
    MarketPriceChangeEvent,
    MarketResolvedEvent,
    MarketTickSizeChangeEvent,
)
from polymarket.models.clob.order_book import OrderBookLevel

from polybot.framework.events import Side
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.normalization.book import normalize_price_change_level
from polybot.polymarket.normalization.timestamps import datetime_to_epoch_ms
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.markets import Market
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookChange,
    BookDeltaPayload,
    RecordedBookLevel,
    TickSizeChangePayload,
)
from polybot.recording.contracts.market import MarketIdentity
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)

from .values import (
    _optional_non_negative_decimal,
    _optional_positive_decimal,
    _optional_probability,
    _optional_text,
    _positive_decimal,
    _probability,
    _required_text,
)


MARKET_WEBSOCKET_SOURCE = "market_websocket"


def normalize_recording_event(
    event: MarketEvent,
    *,
    market: Market,
) -> CapturedMarketEvent | None:
    try:
        if isinstance(event, MarketBookEvent):
            return _book_event(event, market)
        if isinstance(event, MarketPriceChangeEvent):
            return _price_change_event(event, market)
        if isinstance(event, MarketLastTradePriceEvent):
            return _trade_event(event, market)
        if isinstance(event, MarketTickSizeChangeEvent):
            return _tick_size_event(event, market)
        if isinstance(event, MarketResolvedEvent):
            return _resolution_event(event, market)
        return None
    except MarketDataError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market-channel recording payload is malformed",
        ) from error

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
            source_hash=_optional_text(payload.hash, "book hash"),
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
                side=_side(source.side),
                price=level.price,
                size=level.size,
                source_hash=_optional_text(source.hash, "price-change hash"),
                best_bid=_optional_probability(source.best_bid, "best bid"),
                best_ask=_optional_probability(source.best_ask, "best ask"),
            )
        )
    return CapturedMarketEvent(
        source_timestamp_ms=datetime_to_epoch_ms(payload.timestamp),
        identity=_identity(market),
        payload=BookDeltaPayload(changes=tuple(changes)),
    )


def _trade_event(
    event: MarketLastTradePriceEvent,
    market: Market,
) -> CapturedMarketEvent:
    payload = event.payload
    _condition_id(payload.market, market)
    token_id = _token_id(payload.token_id, market)
    return CapturedMarketEvent(
        source_timestamp_ms=datetime_to_epoch_ms(payload.timestamp),
        identity=_identity(market, token_id),
        payload=PublicTradePayload(
            token_id=token_id,
            price=_probability(payload.price, "trade price"),
            size=_positive_decimal(payload.size, "trade size"),
            side=_side(payload.side),
            fee_rate_bps=_optional_non_negative_decimal(
                payload.fee_rate_bps,
                "trade fee rate",
            ),
            transaction_hash=_optional_text(
                payload.transaction_hash,
                "trade transaction hash",
            ),
        ),
    )


def _tick_size_event(
    event: MarketTickSizeChangeEvent,
    market: Market,
) -> CapturedMarketEvent:
    payload = event.payload
    _condition_id(payload.market, market)
    token_id = _token_id(payload.token_id, market)
    return CapturedMarketEvent(
        source_timestamp_ms=datetime_to_epoch_ms(payload.timestamp),
        identity=_identity(market, token_id),
        payload=TickSizeChangePayload(
            token_id=token_id,
            old_tick_size=_optional_positive_decimal(
                payload.old_tick_size,
                "old tick size",
            ),
            new_tick_size=_positive_decimal(payload.new_tick_size, "new tick size"),
        ),
    )


def _resolution_event(
    event: MarketResolvedEvent,
    market: Market,
) -> CapturedMarketEvent:
    payload = event.payload
    _condition_id(payload.market, market)
    token_ids = _token_ids(payload.token_ids)
    if len(token_ids) != 2 or set(token_ids) != set(market.token_ids):
        raise MarketDataError(
            MarketDataIssue.INVALID_RESOLUTION,
            "resolved token IDs do not match market metadata",
        )
    winning_token_id = _required_text(payload.winning_token_id, "winning token ID")
    if winning_token_id not in token_ids:
        raise MarketDataError(
            MarketDataIssue.INVALID_RESOLUTION,
            "winning token ID is not part of the resolved market",
        )
    winning_outcome = _required_text(payload.winning_outcome, "winning outcome")
    expected_outcome = market.outcome_label_for_token(winning_token_id)
    if (
        expected_outcome is None
        or expected_outcome.casefold() != winning_outcome.casefold()
    ):
        raise MarketDataError(
            MarketDataIssue.INVALID_RESOLUTION,
            "winning outcome does not match market metadata",
        )
    resolution_id = _optional_text(payload.id, "resolution ID")
    resolved_token_ids = (token_ids[0], token_ids[1])
    return CapturedMarketEvent(
        source_timestamp_ms=datetime_to_epoch_ms(payload.timestamp),
        identity=_identity(market),
        payload=ResolutionPayload(
            token_ids=resolved_token_ids,
            winning_token_id=winning_token_id,
            winning_outcome=expected_outcome,
            source=MARKET_WEBSOCKET_SOURCE,
            resolution_id=resolution_id,
        ),
    )


def _levels(source: tuple[OrderBookLevel, ...]) -> tuple[RecordedBookLevel, ...]:
    levels: list[RecordedBookLevel] = []
    for level in source:
        price = _probability(level.price, "book price")
        size = _positive_decimal(level.size, "book size")
        levels.append(RecordedBookLevel(price=price, size=size))
    return tuple(levels)


def _condition_id(value: object, market: Market) -> str:
    condition_id = _required_text(value, "condition ID")
    if condition_id != market.condition_id:
        raise MarketDataError(
            MarketDataIssue.BOOK_IDENTITY_MISMATCH,
            "market-channel condition ID does not match resolved metadata",
        )
    return condition_id


def _token_id(value: object, market: Market) -> str:
    token_id = _required_text(value, "token ID")
    if token_id not in market.token_ids:
        raise MarketDataError(
            MarketDataIssue.BOOK_IDENTITY_MISMATCH,
            "market-channel token ID does not match resolved metadata",
        )
    return token_id


def _token_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise MarketDataError(
            MarketDataIssue.INVALID_RESOLUTION,
            "resolved token IDs are missing",
        )
    return tuple(_required_text(token_id, "resolved token ID") for token_id in value)


def _identity(market: Market, token_id: str | None = None) -> MarketIdentity:
    return MarketIdentity(
        condition_id=market.condition_id,
        market_slug=market.slug,
        token_id=token_id,
    )


def _side(value: object) -> Side:
    try:
        return Side(value)
    except (TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_SIDE,
            "market-channel side is invalid",
        ) from error
