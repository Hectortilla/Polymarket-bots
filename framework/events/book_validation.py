from enum import StrEnum


class BookValidationIssue(StrEnum):
    FUTURE_DATED = "book_future_dated"
    STALE = "book_stale"
    BAD_LEVEL = "bad_book_level"
    CROSSED = "book_crossed"
