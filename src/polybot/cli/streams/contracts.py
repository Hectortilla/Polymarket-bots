"""Typed event contracts for CLI streams."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from polybot.framework.events.books import BookGapEvent, BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.market_hints import MarketTradeHint
from .kinds import StreamKind

@dataclass(frozen=True, slots=True)
class BookStreamEvent:
    kind: Literal[StreamKind.BOOK]
    event: BookSnapshot


@dataclass(frozen=True, slots=True)
class BookGapStreamEvent:
    kind: Literal[StreamKind.BOOK_GAP]
    event: BookGapEvent


@dataclass(frozen=True, slots=True)
class WalletStreamEvent:
    kind: Literal[StreamKind.WALLET]
    event: WalletTradeEvent


@dataclass(frozen=True, slots=True)
class MarketHintStreamEvent:
    kind: Literal[StreamKind.MARKET_HINT]
    event: MarketTradeHint


@dataclass(frozen=True, slots=True)
class ResolutionStreamEvent:
    kind: Literal[StreamKind.RESOLUTION]
    event: MarketResolutionEvent


StreamEvent = (
    BookStreamEvent
    | BookGapStreamEvent
    | WalletStreamEvent
    | MarketHintStreamEvent
    | ResolutionStreamEvent
)
StreamSource = AsyncIterator[StreamEvent]


class StreamCompletionRole(StrEnum):
    PRIMARY = "primary"
    AUXILIARY = "auxiliary"


@dataclass(frozen=True, slots=True)
class StreamSourceSpec:
    source: StreamSource
    completion_role: StreamCompletionRole

    @classmethod
    def primary(cls, source: StreamSource) -> StreamSourceSpec:
        return cls(source, StreamCompletionRole.PRIMARY)

    @classmethod
    def auxiliary(cls, source: StreamSource) -> StreamSourceSpec:
        return cls(source, StreamCompletionRole.AUXILIARY)


@dataclass(frozen=True, slots=True)
class StreamFailure:
    error: BaseException


@dataclass(frozen=True, slots=True)
class StreamCompleted:
    completion_role: StreamCompletionRole
