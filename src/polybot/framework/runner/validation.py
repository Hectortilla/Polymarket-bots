from __future__ import annotations

from typing import TYPE_CHECKING

from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent

if TYPE_CHECKING:
    from polybot.polymarket.markets import Market

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
    issue = trade.validation_issue(now_ms, max_age_ms)
    return None if issue is None else DispatchSkipReason(issue.value)


def book_market_identity_skip_reason(
    book: BookSnapshot,
    market: Market | None,
) -> DispatchSkipReason | None:
    if (
        market is None
        or market.slug != book.market_slug
        or market.condition_id != book.condition_id
        or book.token_id not in market.token_ids
    ):
        return DispatchSkipReason.BOOK_IDENTITY_MISMATCH
    return None


def _has_market_identity(book: BookSnapshot) -> bool:
    return all(
        isinstance(identity, str) and bool(identity.strip())
        for identity in (book.token_id, book.market_slug, book.condition_id)
    )
