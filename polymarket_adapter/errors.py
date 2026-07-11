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
    CROSSED_BOOK = "crossed_book"


class MarketDataError(ValueError):
    def __init__(self, issue: MarketDataIssue, detail: str) -> None:
        super().__init__(detail)
        self.issue = issue
