"""Public adapter assembly for one market recording."""

from __future__ import annotations

from dataclasses import dataclass

from polymarket import AsyncPublicClient

from polybot.polymarket.clob import ClobClient
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.recording_feed.feed import MarketRecordingFeed
from polybot.polymarket.recording_metadata.resolver import RecordingMarketResolver

from .client import _PublicClientOwner, _acquire_public_client


@dataclass(slots=True)
class RecordingPublicData(_PublicClientOwner):
    """Normalized public-data adapters used by one market recording."""

    resolver: RecordingMarketResolver
    feed: MarketRecordingFeed
    gamma: GammaClient
    clob: ClobClient


def create_recording_public_data(
    client: AsyncPublicClient | None = None,
) -> RecordingPublicData:
    """Create the shared public adapters required by a market recording."""
    public_client, owns_client = _acquire_public_client(client)
    return RecordingPublicData(
        resolver=RecordingMarketResolver(public_client),
        feed=MarketRecordingFeed(public_client),
        gamma=GammaClient(public_client),
        clob=ClobClient(public_client),
        _owned_client=public_client if owns_client else None,
    )
