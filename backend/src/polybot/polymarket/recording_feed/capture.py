"""Per-condition package-owned captures over the official market stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Self

from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
)
from polybot.polymarket.markets import Market
from polybot.polymarket.recording_events import CapturedMarketEvent

from .capture_depth import CaptureDepth
from .capture_source import CaptureSource
from .revision_recovery import SplitRevisionRecovery

SPLIT_REVISION_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class MarketCaptureDiagnostics:
    generation: int
    condition_id: str
    dropped_count: int
    has_complete_book_baselines: bool
    baseline_token_ids: frozenset[str]


class MarketCapture(AsyncIterator[CapturedMarketEvent]):
    def __init__(
        self,
        handle: object,
        *,
        market: Market,
        generation: int,
        split_revision_timeout_seconds: float = SPLIT_REVISION_TIMEOUT_SECONDS,
    ) -> None:
        if split_revision_timeout_seconds <= 0:
            raise ValueError("split revision timeout must be positive")
        self._source = CaptureSource(handle, market)
        self._market = market
        self._generation = generation
        self._depth = CaptureDepth(market)
        self._recovery = SplitRevisionRecovery(
            self._source, self._depth, split_revision_timeout_seconds
        )

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def condition_id(self) -> str:
        return self._market.condition_id

    @property
    def dropped_count(self) -> int:
        return self._source.dropped_count

    @property
    def has_complete_book_baselines(self) -> bool:
        return self._depth.has_complete_book_baselines

    def diagnostics(self) -> MarketCaptureDiagnostics:
        return MarketCaptureDiagnostics(
            generation=self.generation,
            condition_id=self.condition_id,
            dropped_count=self.dropped_count,
            has_complete_book_baselines=self.has_complete_book_baselines,
            baseline_token_ids=self._depth.baseline_token_ids,
        )

    def projected_books(self, observed_at_ms: int) -> tuple[BookSnapshot, ...]:
        return self._depth.projected_books(observed_at_ms)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> CapturedMarketEvent:
        while True:
            dropped_count_before = self.dropped_count
            captured = await self._source.next_captured()
            if captured is None:
                continue
            try:
                self._depth.apply(captured)
            except MarketDataError as error:
                if error.issue is not MarketDataIssue.CROSSED_BOOK:
                    raise
                return await self._recovery.complete(
                    captured,
                    error,
                    dropped_count_before=dropped_count_before,
                )
            else:
                return captured

    async def close(self) -> None:
        await self._source.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
