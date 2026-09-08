"""Public adapter assembly for one market recording."""

from __future__ import annotations

from dataclasses import dataclass

from polymarket import AsyncPublicClient

from polybot.polymarket.clob import ClobClient
from polybot.polymarket.client_lifecycle import PublicClientLease
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.recording_feed.feed import MarketRecordingFeed
from polybot.polymarket.recording_metadata.resolver import RecordingMarketResolver


@dataclass(slots=True)
class RecordingPublicData:
    """Normalized public-data adapters used by one market recording."""

    resolver: RecordingMarketResolver
    feed: MarketRecordingFeed
    gamma: GammaClient
    clob: ClobClient
    _client_lease: PublicClientLease

    @classmethod
    def create(
        cls,
        client: AsyncPublicClient | None = None,
    ) -> RecordingPublicData:
        lease = PublicClientLease.acquire(client)
        public_client = lease.client
        return cls(
            resolver=RecordingMarketResolver(public_client),
            feed=MarketRecordingFeed(public_client),
            gamma=GammaClient(public_client),
            clob=ClobClient(public_client),
            _client_lease=lease,
        )

    async def close(self) -> None:
        for close_child in (self.feed.close, self.resolver.close):
            try:
                await close_child()
            except BaseException:
                pass
        await self._client_lease.close()
