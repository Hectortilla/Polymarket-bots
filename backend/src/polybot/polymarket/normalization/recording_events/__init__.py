from __future__ import annotations

from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.markets import Market
from polybot.polymarket.normalization.recording_events.books import (
    _book_event,
    _price_change_event,
)
from polybot.polymarket.normalization.recording_events.market_events import (
    _resolution_event,
    _tick_size_event,
    _trade_event,
)
from polybot.polymarket.recording_events import CapturedMarketEvent

from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketEvent,
    MarketLastTradePriceEvent,
    MarketPriceChangeEvent,
    MarketResolvedEvent,
    MarketTickSizeChangeEvent,
)


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
