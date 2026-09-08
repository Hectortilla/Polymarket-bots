from enum import StrEnum


class BookValidationIssue(StrEnum):
    MISSING_MARKET_IDENTITY = "market_metadata_missing"
    IDENTITY_MISMATCH = "book_identity_mismatch"
    BAD_TIMESTAMP = "bad_book_timestamp"
    FUTURE_DATED = "book_future_dated"
    STALE = "book_stale"
    BAD_LEVEL = "bad_book_level"
    CROSSED = "book_crossed"
