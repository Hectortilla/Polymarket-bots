"""Normalized market and recording metadata pair."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.polymarket.markets import Market
from polybot.recording.contracts.market import MarketMetadataPayload


@dataclass(frozen=True, slots=True)
class RecordingMarket:
    market: Market
    metadata: MarketMetadataPayload

    def assert_compatible_revision(self, refreshed: RecordingMarket) -> None:
        """Reject metadata refreshes that change immutable market identity."""
        if self.metadata.revision_identity != refreshed.metadata.revision_identity:
            raise ValueError("market metadata revision changed immutable identity")
