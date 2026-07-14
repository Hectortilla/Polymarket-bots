from __future__ import annotations

from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent

def book_skip_reason(
    book: BookSnapshot,
    *,
    now_ms: int,
    max_age_ms: int,
) -> DispatchSkipReason | None:
    if not _has_market_identity(book):
        return DispatchSkipReason.MARKET_METADATA_MISSING
    issue = book.validation_issue(now_ms, max_age_ms)
    return None if issue is None else DispatchSkipReason(issue.value)


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


def _has_market_identity(book: BookSnapshot) -> bool:
    return all(
        isinstance(identity, str) and bool(identity)
        for identity in (book.market_slug, book.condition_id)
    )
