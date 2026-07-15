from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from polybot.framework.events.book_validation import BookValidationIssue


class DispatchSkipReason(StrEnum):
    MARKET_METADATA_MISSING = BookValidationIssue.MISSING_MARKET_IDENTITY.value
    MARKET_NOT_TRACKED = "market_not_tracked"
    MARKET_RESOLVED = "market_resolved"
    WALLET_NOT_TRACKED = "wallet_not_tracked"
    BOOK_STALE = BookValidationIssue.STALE.value
    BOOK_FUTURE_DATED = BookValidationIssue.FUTURE_DATED.value
    BAD_BOOK_LEVEL = BookValidationIssue.BAD_LEVEL.value
    BOOK_CROSSED = BookValidationIssue.CROSSED.value
    WALLET_TRADE_INVALID = "wallet_trade_invalid"
    WALLET_TRADE_FUTURE_DATED = "wallet_trade_future_dated"
    WALLET_TRADE_STALE = "wallet_trade_stale"
    DUPLICATE_SOURCE_EVENT = "duplicate_source_event"


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    accepted: bool
    skip_reason: DispatchSkipReason | None = None

    def __post_init__(self) -> None:
        if self.accepted and self.skip_reason is not None:
            raise ValueError("accepted dispatch outcomes cannot have a skip reason")
        if not self.accepted and self.skip_reason is None:
            raise ValueError("skipped dispatch outcomes require a skip reason")

    @classmethod
    def accepted_event(cls) -> DispatchOutcome:
        return cls(accepted=True)

    @classmethod
    def skipped(cls, reason: DispatchSkipReason) -> DispatchOutcome:
        return cls(accepted=False, skip_reason=reason)

    def __bool__(self) -> bool:
        return self.accepted
