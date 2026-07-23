import asyncio
from decimal import Decimal

import pytest

from polybot.examples.winner_trading_bot import (
    BREAKOUT_ENTRY_REASON,
    ENTRY_QUOTE_MAX_AGE_MS,
    ENTRY_QUOTE_MAX_SKEW_MS,
    MAXIMUM_ENTRY_ASK,
    MINIMUM_LEADER_BID,
    MINIMUM_PRICE_IMPROVEMENT,
    Quote,
    WinnerTradingBot,
)
from polybot.framework.context import BotContext
from polybot.polymarket.markets import Market, MarketOutcome


NOW_MS = 240_000
LEADER_TOKEN_ID = "up-token"
OPPOSITE_TOKEN_ID = "down-token"


@pytest.mark.parametrize(
    ("leader_observed_at_ms", "opposite_observed_at_ms"),
    (
        (NOW_MS, NOW_MS - ENTRY_QUOTE_MAX_AGE_MS - 1),
        (NOW_MS, NOW_MS - ENTRY_QUOTE_MAX_SKEW_MS - 1),
        (NOW_MS, NOW_MS + 1),
    ),
    ids=("stale-opposing-book", "excessive-pair-skew", "future-opposing-book"),
)
def test_winner_bot_never_enters_with_unsafe_quote_pair(
    dummy_context: BotContext,
    leader_observed_at_ms: int,
    opposite_observed_at_ms: int,
) -> None:
    bot = _ready_bot(
        leader_observed_at_ms=leader_observed_at_ms,
        opposite_observed_at_ms=opposite_observed_at_ms,
    )

    asyncio.run(bot._maybe_enter(dummy_context, NOW_MS))

    assert dummy_context.broker.submitted == []


def test_winner_bot_enters_with_current_paired_quotes(
    dummy_context: BotContext,
) -> None:
    bot = _ready_bot(
        leader_observed_at_ms=NOW_MS,
        opposite_observed_at_ms=NOW_MS,
    )

    asyncio.run(bot._maybe_enter(dummy_context, NOW_MS))

    assert len(dummy_context.broker.submitted) == 1
    assert dummy_context.broker.submitted[0].reason == BREAKOUT_ENTRY_REASON
    assert dummy_context.broker.submitted[0].token_id == OPPOSITE_TOKEN_ID


def _ready_bot(
    *,
    leader_observed_at_ms: int,
    opposite_observed_at_ms: int,
) -> WinnerTradingBot:
    bot = WinnerTradingBot()
    bot._market = _market()
    bot._books = {
        LEADER_TOKEN_ID: Quote(
            bid=MINIMUM_LEADER_BID + MINIMUM_PRICE_IMPROVEMENT,
            ask=Decimal("0.95"),
            observed_at_ms=leader_observed_at_ms,
        ),
        OPPOSITE_TOKEN_ID: Quote(
            bid=Decimal("0.10"),
            ask=MAXIMUM_ENTRY_ASK,
            observed_at_ms=opposite_observed_at_ms,
        ),
    }
    bot._prior_bids = {
        LEADER_TOKEN_ID: Quote(
            bid=MINIMUM_LEADER_BID,
            ask=Decimal("0.90"),
            observed_at_ms=NOW_MS - ENTRY_QUOTE_MAX_AGE_MS,
        )
    }
    return bot


def _market() -> Market:
    return Market(
        condition_id="condition",
        slug="btc-updown-5m-0",
        question="BTC Up or Down",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0"),
        outcomes=(
            MarketOutcome("Up", LEADER_TOKEN_ID),
            MarketOutcome("Down", OPPOSITE_TOKEN_ID),
        ),
    )
