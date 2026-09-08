"""Event safety checks shared by stateful nodes and broker actions."""

from polybot.framework.context import BotContext
from polybot.framework.events.books import BookGapEvent, BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot_control_plane.catalog.node_based.evaluator.contracts import (
    GraphActionSkipReason,
)


def event_skip_reason(ctx: BotContext, payload: object | None) -> str | None:
    if isinstance(payload, BookGapEvent):
        return GraphActionSkipReason.BOOK_GAP
    if isinstance(payload, BookSnapshot):
        issue = payload.validation_issue(
            ctx.clock.now_ms(), ctx.config.event_max_age_ms
        )
        return issue.value if issue is not None else None
    if isinstance(payload, WalletTradeEvent):
        issue = payload.freshness_issue(ctx.clock.now_ms(), ctx.config.event_max_age_ms)
        return issue.value if issue is not None else None
    return None
