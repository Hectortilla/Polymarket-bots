from __future__ import annotations

from polybot.framework.events.resolution_tokens import MARKET_RESOLUTION_TOKEN_COUNT
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.markets import Market
from polybot.polymarket.normalization.recording_events.fields import normalize_side
from polybot.polymarket.normalization.recording_events.identity import (
    _condition_id,
    _identity,
    _token_id,
    _token_ids,
)
from polybot.polymarket.normalization.timestamps import datetime_to_epoch_ms
from polybot.polymarket.normalization.values import (
    _optional_non_negative_decimal,
    _optional_positive_decimal,
    _positive_decimal,
    _probability,
    require_text,
    validate_optional_text,
)
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.recording.contracts.book import (
    TickSizeChangePayload,
)
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)

from polymarket.models.clob.market_events import (
    MarketLastTradePriceEvent,
    MarketResolvedEvent,
    MarketTickSizeChangeEvent,
)

MARKET_WEBSOCKET_SOURCE = "market_websocket"


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
            side=normalize_side(payload.side),
            fee_rate_bps=_optional_non_negative_decimal(
                payload.fee_rate_bps,
                "trade fee rate",
            ),
            transaction_hash=validate_optional_text(
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
    if len(token_ids) != MARKET_RESOLUTION_TOKEN_COUNT or set(token_ids) != set(
        market.token_ids
    ):
        raise MarketDataError(
            MarketDataIssue.INVALID_RESOLUTION,
            "resolved token IDs do not match market metadata",
        )
    winning_token_id = require_text(payload.winning_token_id, "winning token ID")
    if winning_token_id not in token_ids:
        raise MarketDataError(
            MarketDataIssue.INVALID_RESOLUTION,
            "winning token ID is not part of the resolved market",
        )
    winning_outcome = require_text(payload.winning_outcome, "winning outcome")
    expected_outcome = market.outcome_label_for_token(winning_token_id)
    if (
        expected_outcome is None
        or expected_outcome.casefold() != winning_outcome.casefold()
    ):
        raise MarketDataError(
            MarketDataIssue.INVALID_RESOLUTION,
            "winning outcome does not match market metadata",
        )
    resolution_id = validate_optional_text(payload.id, "resolution ID")
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
