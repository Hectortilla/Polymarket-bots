"""Public adapter assembly for one paper runtime."""

from __future__ import annotations

from dataclasses import dataclass

from polymarket import AsyncPublicClient

from polybot.polymarket.clob import ClobClient
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.positions.client import PositionClient
from polybot.polymarket.wallet_activity.client import PolymarketWalletActivityClient
from polybot.polymarket.ws_market import MarketStream

from .client import _PublicClientOwner, _acquire_public_client


@dataclass(slots=True)
class RuntimePublicData(_PublicClientOwner):
    """Normalized public-data adapters used by one paper runtime."""

    gamma: GammaClient
    clob: ClobClient
    market_stream: MarketStream
    wallet_activity_client: PolymarketWalletActivityClient
    position_client: PositionClient


def create_runtime_public_data(
    client: AsyncPublicClient | None = None,
) -> RuntimePublicData:
    """Create the shared public adapters required by a paper runtime."""
    public_client, owns_client = _acquire_public_client(client)
    return RuntimePublicData(
        gamma=GammaClient(public_client),
        clob=ClobClient(public_client),
        market_stream=MarketStream(public_client),
        wallet_activity_client=PolymarketWalletActivityClient(public_client),
        position_client=PositionClient(public_client),
        _owned_client=public_client if owns_client else None,
    )
