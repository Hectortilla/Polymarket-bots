from __future__ import annotations

from polybot.polymarket.markets import (
    Market,
)
from polybot.polymarket.normalization.values import validate_optional_text

from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketEvent,
    MarketLastTradePriceEvent,
    MarketPriceChangeEvent,
    MarketResolvedEvent,
    MarketTickSizeChangeEvent,
)


def _identifier(value: object) -> str | None:
    return validate_optional_text(value, "market stream identifier")


def _market_for_event(
    event: MarketEvent,
    *,
    subscribed_token_ids: frozenset[str],
    market_by_token: dict[str, Market],
    market_by_condition: dict[str, Market],
) -> Market | None:
    payload = getattr(event, "payload", None)
    if isinstance(event, (MarketPriceChangeEvent, MarketResolvedEvent)):
        condition_id = _identifier(getattr(payload, "market", None))
        return None if condition_id is None else market_by_condition.get(condition_id)
    if isinstance(
        event,
        (MarketBookEvent, MarketLastTradePriceEvent, MarketTickSizeChangeEvent),
    ):
        token_id = _identifier(getattr(payload, "token_id", None))
        if token_id is None or token_id not in subscribed_token_ids:
            return None
        return market_by_token.get(token_id)
    return None
