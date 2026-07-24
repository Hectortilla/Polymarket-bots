import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from polybot.examples.meh_trading_bot import (
    BREAKOUT_ENTRY_REASON,
    ENTRY_QUOTE_MAX_AGE_MS,
    ENTRY_QUOTE_MAX_SKEW_MS,
    MAXIMUM_TRADES_PER_RUN,
    MAXIMUM_ENTRY_ASK,
    MINIMUM_LEADER_BID,
    MINIMUM_PRICE_IMPROVEMENT,
    MOMENTUM_LOOKBACK_MS,
    PAPER_MAX_ORDER_SIZE,
    Quote,
    OpenPosition,
    TAKE_PROFIT,
    TAKE_PROFIT_EXIT_REASON,
    WinnerTradingBot,
)
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events import FillEvent, OrderStatus, Side
from polybot.framework.events.books import (
    BookGapEvent,
    BookGapReason,
    BookLevel,
    BookSnapshot,
)
from polybot.framework.events.resolutions import MarketResolutionEvent
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


def test_winner_bot_take_profit_closes_a_fully_filled_position(
    dummy_context: BotContext,
) -> None:
    bot = WinnerTradingBot()
    bot._position = OpenPosition(
        OPPOSITE_TOKEN_ID,
        Decimal("2"),
        Decimal("0.16"),
    )

    asyncio.run(
        bot._maybe_take_profit(
            dummy_context,
            _market(),
            OPPOSITE_TOKEN_ID,
            Quote(
                bid=Decimal("0.16") + TAKE_PROFIT,
                ask=Decimal("0.50"),
                observed_at_ms=NOW_MS,
            ),
        )
    )

    assert dummy_context.broker.submitted[0].reason == TAKE_PROFIT_EXIT_REASON
    assert bot._position is None


def test_winner_bot_take_profit_retains_a_partial_position(
    dummy_context: BotContext,
) -> None:
    class PartialBroker:
        async def submit(self, order):
            return FillEvent(
                order_id="partial",
                token_id=order.token_id,
                side=Side.SELL,
                status=OrderStatus.PARTIAL,
                requested_size=order.size,
                filled_size=Decimal("0.5"),
                average_price=order.price,
                fee_usdc=Decimal("0"),
                received_at_ms=NOW_MS,
            )

        async def cancel_all(self) -> None:
            return None

    bot = WinnerTradingBot()
    bot._position = OpenPosition(
        OPPOSITE_TOKEN_ID,
        Decimal("2"),
        Decimal("0.16"),
    )
    context = replace(dummy_context, broker=PartialBroker())

    asyncio.run(
        bot._maybe_take_profit(
            context,
            _market(),
            OPPOSITE_TOKEN_ID,
            Quote(
                bid=Decimal("0.16") + TAKE_PROFIT,
                ask=Decimal("0.50"),
                observed_at_ms=NOW_MS,
            ),
        )
    )

    assert bot._position == OpenPosition(
        OPPOSITE_TOKEN_ID,
        Decimal("1.5"),
        Decimal("0.16"),
    )


def test_winner_bot_applies_configured_size_and_market_minimum(
    dummy_context: BotContext,
) -> None:
    assert WinnerTradingBot._effective_order_size(Decimal("2")) == Decimal("2")
    assert (
        WinnerTradingBot._effective_order_size(PAPER_MAX_ORDER_SIZE + 1)
        == PAPER_MAX_ORDER_SIZE
    )
    bot = _ready_bot(
        leader_observed_at_ms=NOW_MS,
        opposite_observed_at_ms=NOW_MS,
    )
    bot._market = replace(_market(), minimum_order_size=Decimal("3"))
    context = replace(
        dummy_context,
        config=replace(dummy_context.config, max_order_size=Decimal("2")),
    )

    asyncio.run(bot._maybe_enter(context, NOW_MS))

    assert dummy_context.broker.submitted == []


def test_winner_bot_stops_entering_at_the_run_trade_cap(
    dummy_context: BotContext,
) -> None:
    bot = _ready_bot(
        leader_observed_at_ms=NOW_MS,
        opposite_observed_at_ms=NOW_MS,
    )
    bot._entry_count = MAXIMUM_TRADES_PER_RUN

    asyncio.run(bot._maybe_enter(dummy_context, NOW_MS))

    assert dummy_context.broker.submitted == []
    assert bot.backtest_is_quiescent(dummy_context)


def test_winner_bot_public_callbacks_enter_and_clear_resolved_position(
    dummy_context: BotContext,
) -> None:
    async def run() -> WinnerTradingBot:
        bot = WinnerTradingBot()
        context = replace(
            dummy_context,
            config=replace(dummy_context.config, event_max_age_ms=20_000),
            markets=_Markets(),
            clock=_Clock(),
        )
        await bot.on_book(
            context,
            _book(OPPOSITE_TOKEN_ID, bid="0.10", ask="0.16", observed_at_ms=NOW_MS),
        )
        await bot.on_book(
            context,
            _book(
                LEADER_TOKEN_ID,
                bid="0.85",
                ask="0.95",
                observed_at_ms=NOW_MS - MOMENTUM_LOOKBACK_MS,
            ),
        )
        await bot.on_book(
            context,
            _book(LEADER_TOKEN_ID, bid="0.89", ask="0.95", observed_at_ms=NOW_MS),
        )
        await bot.on_market_resolved(
            context,
            MarketResolutionEvent(
                condition_id="condition",
                market_slug=_market().slug,
                token_ids=(LEADER_TOKEN_ID, OPPOSITE_TOKEN_ID),
                winning_token_id=LEADER_TOKEN_ID,
                winning_outcome="Up",
                resolved_at_ms=NOW_MS,
                source="test",
            ),
        )
        return bot

    bot = asyncio.run(run())

    assert len(dummy_context.broker.submitted) == 1
    assert dummy_context.broker.submitted[0].reason == BREAKOUT_ENTRY_REASON
    assert bot._position is None
    assert bot._entered_condition_id is None


def test_winner_bot_rechecks_freshness_after_market_lookup(
    dummy_context: BotContext,
) -> None:
    context = replace(
        dummy_context,
        config=replace(dummy_context.config, event_max_age_ms=0),
        markets=_Markets(),
        clock=_Clock(),
    )
    bot = WinnerTradingBot()

    result = asyncio.run(
        bot.on_book(
            context,
            _book(
                OPPOSITE_TOKEN_ID,
                bid="0.10",
                ask="0.16",
                observed_at_ms=NOW_MS - 1,
            ),
        )
    )

    assert result is DispatchSkipReason.BOOK_STALE
    assert dummy_context.broker.submitted == []


def test_winner_bot_gap_clears_quotes_but_preserves_an_open_position(
    dummy_context: BotContext,
) -> None:
    bot = _ready_bot(
        leader_observed_at_ms=NOW_MS,
        opposite_observed_at_ms=NOW_MS,
    )
    position = OpenPosition(
        OPPOSITE_TOKEN_ID,
        Decimal("2"),
        Decimal("0.16"),
    )
    bot._position = position

    asyncio.run(
        bot.on_book_gap(
            dummy_context,
            BookGapEvent(
                condition_id="condition",
                observed_at_ms=NOW_MS,
                reason=BookGapReason.BOOK_STREAM_GAP,
            ),
        )
    )

    assert bot._books == {}
    assert bot._prior_bids == {}
    assert bot._position is position


def _book(
    token_id: str,
    *,
    bid: str,
    ask: str,
    observed_at_ms: int,
) -> BookSnapshot:
    return BookSnapshot(
        token_id=token_id,
        bids=(BookLevel(Decimal(bid), Decimal("100")),),
        asks=(BookLevel(Decimal(ask), Decimal("100")),),
        received_at_ms=observed_at_ms,
        market_slug=_market().slug,
        condition_id="condition",
    )


class _Markets:
    async def find_by_slug(self, slug: str) -> Market | None:
        market = _market()
        return market if slug == market.slug else None


class _Clock:
    def now_ms(self) -> int:
        return NOW_MS

    async def sleep(self, seconds: float) -> None:
        return None


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
