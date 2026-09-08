from __future__ import annotations

from polybot.polymarket.errors import (
    MarketDataTransportError,
)
from polybot.polymarket.markets import Market
from polybot.polymarket.normalization.recording_events import (
    normalize_recording_event,
)
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.stream_diagnostics import (
    sdk_dropped_count,
)

from polymarket import PolymarketError


class CaptureSource:
    def __init__(self, handle: object, market: Market) -> None:
        self._handle = handle
        self._events = handle.__aiter__()  # type: ignore[attr-defined]
        self._market = market

    @property
    def dropped_count(self) -> int:
        return sdk_dropped_count(self._handle)

    async def close(self) -> None:
        try:
            await self._handle.close()  # type: ignore[attr-defined]
        except PolymarketError as error:
            raise MarketDataTransportError(
                "recording market capture shutdown failed"
            ) from error

    async def next_captured(self) -> CapturedMarketEvent | None:
        try:
            event = await anext(self._events)
        except PolymarketError as error:
            raise MarketDataTransportError("recording market capture failed") from error
        return normalize_recording_event(event, market=self._market)
