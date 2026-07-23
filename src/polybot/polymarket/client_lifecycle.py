"""Official public-client ownership and shutdown normalization."""

from __future__ import annotations

from polymarket import AsyncPublicClient, PolymarketError

from .errors import MarketDataTransportError


async def close_owned_public_client(client: AsyncPublicClient) -> None:
    """Close one adapter-owned SDK client without leaking vendor failures."""
    try:
        await client.close()
    except PolymarketError as error:
        raise MarketDataTransportError(
            "public market-data client shutdown failed"
        ) from error
