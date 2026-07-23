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
        if (
            self.market.condition_id != refreshed.market.condition_id
            or self.market.slug != refreshed.market.slug
            or self.market.token_ids != refreshed.market.token_ids
            or tuple(outcome.label for outcome in self.market.outcomes)
            != tuple(outcome.label for outcome in refreshed.market.outcomes)
        ):
            raise ValueError("market metadata revision changed immutable identity")
