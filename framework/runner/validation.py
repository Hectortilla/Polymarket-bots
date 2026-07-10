from __future__ import annotations

from bots.framework.dispatch import DispatchSkipReason
from bots.framework.events.book_validation import BookValidationIssue
from bots.framework.events.books import BookSnapshot
from bots.framework.events.wallet_trades import WalletTradeEvent

BOOK_DISPATCH_REASONS = {
    BookValidationIssue.FUTURE_DATED: DispatchSkipReason.BOOK_FUTURE_DATED,
    BookValidationIssue.STALE: DispatchSkipReason.BOOK_STALE,
    BookValidationIssue.BAD_LEVEL: DispatchSkipReason.BAD_BOOK_LEVEL,
    BookValidationIssue.CROSSED: DispatchSkipReason.BOOK_CROSSED,
}


def book_skip_reason(
    book: BookSnapshot,
    *,
    now_ms: int,
    max_age_ms: int,
) -> DispatchSkipReason | None:
    return BOOK_DISPATCH_REASONS.get(book.validation_issue(now_ms, max_age_ms))


def wallet_trade_skip_reason(
    trade: WalletTradeEvent,
    *,
    now_ms: int,
    max_age_ms: int,
) -> DispatchSkipReason | None:
    if not trade.is_valid():
        return DispatchSkipReason.WALLET_TRADE_INVALID
    if trade.observed_at_ms > now_ms:
        return DispatchSkipReason.WALLET_TRADE_FUTURE_DATED
    if now_ms - trade.observed_at_ms > max_age_ms:
        return DispatchSkipReason.WALLET_TRADE_STALE
    if trade.observed_at_ms - trade.trade_timestamp_ms > max_age_ms:
        return DispatchSkipReason.WALLET_TRADE_STALE
    return None
