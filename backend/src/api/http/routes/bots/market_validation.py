"""Resolve newly selected markets at the saved-bot HTTP boundary."""

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from polybot.framework.streams import STREAM_RULE_MARKET_SLUGS_FIELD
from polybot.polymarket.discovery import MarketDiscovery
from polybot.polymarket.errors import MarketDataError, MarketDataTransportError

from api.http.market_contracts import (
    MARKET_DISCOVERY_UNAVAILABLE_DETAIL,
)
from api.http.routes.bots.validation import (
    BOT_INPUTS_FIELD,
    REQUEST_BODY_LOCATION,
)
from api.runs.contracts import PaperRunConfig

MARKET_SELECTION_UNAVAILABLE_DETAIL = (
    "Select an available market from the search results."
)


async def validate_new_market_selections(
    config: PaperRunConfig,
    discovery: MarketDiscovery,
    *,
    previous_config: PaperRunConfig | None = None,
) -> None:
    slugs = config.new_market_slugs(previous_config)
    if not slugs:
        return
    try:
        resolved = await discovery.resolve(slugs)
    except (MarketDataError, MarketDataTransportError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, MARKET_DISCOVERY_UNAVAILABLE_DETAIL
        ) from error
    available = {market.slug for market in resolved if market.is_open_for_trading}
    if set(slugs) - available:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": (
                        REQUEST_BODY_LOCATION,
                        BOT_INPUTS_FIELD,
                        STREAM_RULE_MARKET_SLUGS_FIELD,
                    ),
                    "msg": MARKET_SELECTION_UNAVAILABLE_DETAIL,
                }
            ]
        )
