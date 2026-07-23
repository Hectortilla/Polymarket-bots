"""Package-owned values emitted by the Polymarket recording adapter."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
    TickSizeChangePayload,
)
from polybot.recording.contracts.market import MarketIdentity
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)


type CapturedMarketPayload = (
    BookBaselinePayload
    | BookDeltaPayload
    | PublicTradePayload
    | TickSizeChangePayload
    | ResolutionPayload
)


@dataclass(frozen=True, slots=True)
class CapturedMarketEvent:
    source_timestamp_ms: int | None
    identity: MarketIdentity
    payload: CapturedMarketPayload
