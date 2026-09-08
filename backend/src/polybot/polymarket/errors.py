from __future__ import annotations

from enum import StrEnum


class MarketDataIssue(StrEnum):
    EMPTY_IDENTIFIER = "empty_identifier"
    MISSING_CONDITION_ID = "missing_condition_id"
    MISSING_MARKET_SLUG = "missing_market_slug"
    MISSING_QUESTION = "missing_question"
    MISSING_TOKEN_ID = "missing_token_id"
    INVALID_MARKET_PARAMETERS = "invalid_market_parameters"
    INVALID_BOOK_LEVEL = "invalid_book_level"
    BOOK_UNAVAILABLE = "book_unavailable"
    INVALID_BOOK_SIDE = "invalid_book_side"
    MISSING_BOOK_BASELINE = "missing_book_baseline"
    BOOK_IDENTITY_MISMATCH = "book_identity_mismatch"
    BOOK_STREAM_GAP = "book_stream_gap"
    INVALID_STREAM_DIAGNOSTICS = "invalid_stream_diagnostics"
    CROSSED_BOOK = "crossed_book"
    AMBIGUOUS_MARKET_METADATA = "ambiguous_market_metadata"
    INVALID_POSITION = "invalid_position"
    INVALID_RESOLUTION = "invalid_resolution"


class MarketDataError(ValueError):
    def __init__(self, issue: MarketDataIssue, detail: str) -> None:
        super().__init__(detail)
        self.issue = issue


class MarketDataTransportError(RuntimeError):
    """An official-client failure normalized at the public market-data boundary."""
