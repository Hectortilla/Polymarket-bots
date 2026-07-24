"""Official public-client ownership and shutdown normalization."""

from __future__ import annotations

from dataclasses import dataclass

from polymarket import AsyncPublicClient, PolymarketError

from .errors import MarketDataTransportError


@dataclass(slots=True)
class PublicClientLease:
    """One public SDK client plus explicit, idempotent lifecycle ownership."""

    client: AsyncPublicClient
    _owned: bool

    @classmethod
    def acquire(
        cls,
        client: AsyncPublicClient | None = None,
    ) -> PublicClientLease:
        return cls(
            AsyncPublicClient() if client is None else client,
            client is None,
        )

    async def close(self) -> None:
        if not self._owned:
            return
        try:
            await self.client.close()
        except PolymarketError as error:
            raise MarketDataTransportError(
                "public market-data client shutdown failed"
            ) from error
        self._owned = False
