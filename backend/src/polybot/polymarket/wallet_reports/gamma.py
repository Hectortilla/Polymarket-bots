"""Exact market discovery and JSON-safe metadata via official Gamma methods."""

from collections.abc import Callable
from http import HTTPStatus

from polybot.polymarket.errors import MarketDataError
from polybot.polymarket.pagination import sdk_page_items
from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_SLUG_FIELD,
    CONDITION_ID_FIELD,
)

from polymarket import PolymarketError, PublicClient, RequestRejectedError

from .errors import WalletReadError, WalletReadReason
from .market_contracts import MARKET_CLOSED_FIELD, GammaMarketPayload
from .market_payloads import market_payload
from .query_contracts import SDK_PAGE_SIZE


def gamma_condition_id(
    slug: str, *, client_factory: Callable[[], PublicClient] = PublicClient
) -> tuple[str | None, bool | None]:
    try:
        with client_factory() as client:
            model = client.get_market(slug=slug)
        payload = market_payload(model)
        if payload[ACTIVITY_SLUG_FIELD] != slug:
            raise WalletReadError(WalletReadReason.INVALID_RESPONSE)
        return payload[CONDITION_ID_FIELD], payload[MARKET_CLOSED_FIELD]
    except RequestRejectedError as error:
        if error.status == HTTPStatus.NOT_FOUND:
            return None, None
        raise WalletReadError(WalletReadReason.UNAVAILABLE) from error
    except PolymarketError as error:
        raise WalletReadError(WalletReadReason.UNAVAILABLE) from error
    except MarketDataError as error:
        raise WalletReadError(WalletReadReason.INVALID_RESPONSE) from error


def fetch_gamma_market(
    condition_id: str, *, client_factory: Callable[[], PublicClient] = PublicClient
) -> GammaMarketPayload | None:
    try:
        with client_factory() as client:
            page = client.list_markets(
                condition_ids=condition_id, page_size=SDK_PAGE_SIZE
            ).first_page()
        models = sdk_page_items(
            page, malformed_error=WalletReadError(WalletReadReason.INVALID_RESPONSE)
        )
        if not models:
            return None
        payloads = [market_payload(model) for model in models]
        if any(
            payload[CONDITION_ID_FIELD] != condition_id or payload != payloads[0]
            for payload in payloads
        ):
            raise WalletReadError(WalletReadReason.INVALID_RESPONSE)
        return payloads[0]
    except PolymarketError as error:
        raise WalletReadError(WalletReadReason.UNAVAILABLE) from error
    except MarketDataError as error:
        raise WalletReadError(WalletReadReason.INVALID_RESPONSE) from error
