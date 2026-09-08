"""Public adapter assembly for one paper runtime."""

from __future__ import annotations

from dataclasses import dataclass

from polymarket import AsyncPublicClient

from polybot.polymarket.clob import ClobClient
from polybot.polymarket.client_lifecycle import PublicClientLease
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.positions.client import PositionClient
from polybot.polymarket.wallet_activity.client import PolymarketWalletActivityClient
from polybot.polymarket.ws_market import MarketStream

@dataclass(slots=True)
class RuntimePublicData:
    """Normalized public-data adapters used by one paper runtime."""

    gamma: GammaClient
    clob: ClobClient
    market_stream: MarketStream
    wallet_activity_client: PolymarketWalletActivityClient
    position_client: PositionClient
    _client_lease: PublicClientLease

    @classmethod
    def create(
        cls,
        client: AsyncPublicClient | None = None,
    ) -> RuntimePublicData:
        lease = PublicClientLease.acquire(client)
        public_client = lease.client
        return cls(
            gamma=GammaClient(public_client),
            clob=ClobClient(public_client),
            market_stream=MarketStream(public_client),
            wallet_activity_client=PolymarketWalletActivityClient(public_client),
            position_client=PositionClient(public_client),
            _client_lease=lease,
        )

    async def close(self) -> None:
        await self._client_lease.close()
