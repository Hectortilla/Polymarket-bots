"""Dependency-light stream classifications used by runtime projections."""

from enum import StrEnum


class StreamKind(StrEnum):
    BOOK = "book"
    BOOK_GAP = "book_gap"
    WALLET = "wallet"
    MARKET_HINT = "market_hint"
    RESOLUTION = "resolution"
