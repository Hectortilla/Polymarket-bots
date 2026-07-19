"""Typed event contracts for CLI streams."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.market_hints import MarketTradeHint


class StreamKind(StrEnum):
    BOOK = "book"
    WALLET = "wallet"
    MARKET_HINT = "market_hint"
    RESOLUTION = "resolution"


@dataclass(frozen=True, slots=True)
class BookStreamEvent:
    kind: Literal[StreamKind.BOOK]
    event: BookSnapshot


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
    BookStreamEvent | WalletStreamEvent | MarketHintStreamEvent | ResolutionStreamEvent
)
StreamPayload = (
    BookSnapshot | WalletTradeEvent | MarketTradeHint | MarketResolutionEvent
)
StreamSource = AsyncIterator[StreamPayload]


@dataclass(frozen=True, slots=True)
class StreamFailure:
    error: BaseException


@dataclass(frozen=True, slots=True)
class StreamCompleted:
    kind: StreamKind
