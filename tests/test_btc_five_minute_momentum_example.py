import asyncio
from dataclasses import replace
from decimal import Decimal

from polybot.examples.btc_five_minute_strategy import (
    BTC_FIVE_MINUTE_SLUG_PREFIX,
    EXPIRY_EXIT_REASON,
    MOMENTUM_ENTRY_REASON,
    STOP_EXIT_REASON,
    TARGET_EXIT_REASON,
    MomentumSettings,
    ProbabilitySampleTransition,
    ProbabilityTrend,
)
from polybot.examples.example_btc_five_minute_momentum import (
    BtcFiveMinuteMomentumBot,
)
from polybot.framework.context import BotContext
from polybot.framework.events import Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.polymarket.markets import Market, MarketOutcome

UP_TOKEN_ID = "up-token"
DOWN_TOKEN_ID = "down-token"
CONDITION_ID = "btc-condition"


def test_bot_tracks_the_current_and_next_five_minute_buckets(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[str, str]:
        bot = BtcFiveMinuteMomentumBot()
        current = await bot.current_stream_rules(dummy_context, 1783549320000)
        following = await bot.next_stream_rules(dummy_context, 1783549320000)
        return current[0].market_slugs[0], following[0].market_slugs[0]

    current_slug, next_slug = asyncio.run(run())

    assert current_slug == f"{BTC_FIVE_MINUTE_SLUG_PREFIX}-1783549200"
    assert next_slug == f"{BTC_FIVE_MINUTE_SLUG_PREFIX}-1783549500"


def test_probability_trend_rejects_directionless_whipsaw() -> None:
    trend = ProbabilityTrend(_test_settings())
    metrics = None
    for value in ("0.50", "0.54", "0.50", "0.54"):
        observation = trend.after_observation(Decimal(value))
        trend = observation.trend
        metrics = observation.metrics

    assert metrics is not None
    assert trend.settings.direction(metrics) is None


def test_probability_sample_transition_rejects_unsynchronized_books() -> None:
    settings = _test_settings()
    transition = ProbabilitySampleTransition.from_book_pair(
        settings=settings,
        trend=ProbabilityTrend(settings),
        prior_sample_at_ms=None,
        now_ms=1_001,
        up_book=_book(
            UP_TOKEN_ID,
            midpoint=Decimal("0.55"),
            timestamp_ms=1_000,
            positive_imbalance=True,
        ),
        down_book=_book(
            DOWN_TOKEN_ID,
            midpoint=Decimal("0.45"),
            timestamp_ms=1_001,
            positive_imbalance=False,
        ),
    )

    assert transition is None


def test_bot_buys_up_after_confirmed_probability_momentum(
    dummy_context: BotContext,
) -> None:
    asyncio.run(
        _feed_probabilities(
            dummy_context,
            probabilities=("0.44", "0.46", "0.49", "0.54"),
            favored_outcome="Up",
        )
    )

    assert len(dummy_context.broker.submitted) == 1
    order = dummy_context.broker.submitted[0]
    assert order.token_id == UP_TOKEN_ID
    assert order.side is Side.BUY
    assert order.reason == MOMENTUM_ENTRY_REASON
    assert order.market_slug == _slug(0)
    assert order.condition_id == CONDITION_ID


def test_bot_buys_down_after_confirmed_probability_momentum(
    dummy_context: BotContext,
) -> None:
    asyncio.run(
        _feed_probabilities(
            dummy_context,
            probabilities=("0.56", "0.54", "0.51", "0.46"),
            favored_outcome="Down",
        )
    )

    assert len(dummy_context.broker.submitted) == 1
    order = dummy_context.broker.submitted[0]
    assert order.token_id == DOWN_TOKEN_ID
    assert order.side is Side.BUY


def test_bot_requires_order_book_confirmation(
    dummy_context: BotContext,
) -> None:
    asyncio.run(
        _feed_probabilities(
            dummy_context,
            probabilities=("0.44", "0.46", "0.49", "0.54"),
            favored_outcome="Down",
        )
    )

    assert dummy_context.broker.submitted == []


def test_bot_rejects_a_wide_entry_spread(dummy_context: BotContext) -> None:
    asyncio.run(
        _feed_probabilities(
            dummy_context,
            probabilities=("0.44", "0.46", "0.49", "0.54"),
            favored_outcome="Up",
            half_spread=Decimal("0.03"),
        )
    )

    assert dummy_context.broker.submitted == []


def test_bot_rejects_an_equally_timestamped_stale_book_pair(
    dummy_context: BotContext,
) -> None:
    settings = _test_settings()
    asyncio.run(
        _feed_probabilities(
            dummy_context,
            probabilities=("0.44", "0.46", "0.49", "0.54"),
            favored_outcome="Up",
            clock_lag_ms=settings.paired_book_max_age_ms + 1,
        )
    )

    assert dummy_context.broker.submitted == []


def test_bot_sells_at_the_stop_and_does_not_short(
    dummy_context: BotContext,
) -> None:
    async def run() -> None:
        bot = await _feed_probabilities(
            dummy_context,
            probabilities=("0.44", "0.46", "0.49", "0.54"),
            favored_outcome="Up",
        )
        await bot.on_book(
            dummy_context,
            _book(
                UP_TOKEN_ID,
                midpoint=Decimal("0.48"),
                timestamp_ms=104_000,
                positive_imbalance=True,
            ),
        )

    asyncio.run(run())

    assert [order.side for order in dummy_context.broker.submitted] == [
        Side.BUY,
        Side.SELL,
    ]
    assert dummy_context.broker.submitted[1].reason == STOP_EXIT_REASON
    assert dummy_context.broker.submitted[1].size == dummy_context.broker.submitted[0].size


def test_bot_sells_at_the_profit_target(dummy_context: BotContext) -> None:
    async def run() -> None:
        bot = await _feed_probabilities(
            dummy_context,
            probabilities=("0.44", "0.46", "0.49", "0.54"),
            favored_outcome="Up",
        )
        await bot.on_book(
            dummy_context,
            _book(
                UP_TOKEN_ID,
                midpoint=Decimal("0.64"),
                timestamp_ms=104_000,
                positive_imbalance=True,
            ),
        )

    asyncio.run(run())

    assert [order.side for order in dummy_context.broker.submitted] == [
        Side.BUY,
        Side.SELL,
    ]
    assert dummy_context.broker.submitted[1].reason == TARGET_EXIT_REASON


def test_bot_forces_an_exit_before_bucket_expiry(dummy_context: BotContext) -> None:
    async def run() -> None:
        bot = await _feed_probabilities(
            dummy_context,
            probabilities=("0.44", "0.46", "0.49", "0.54"),
            favored_outcome="Up",
        )
        await bot.on_book(
            dummy_context,
            _book(
                UP_TOKEN_ID,
                midpoint=Decimal("0.54"),
                timestamp_ms=299_500,
                positive_imbalance=True,
            ),
        )

    asyncio.run(run())

    assert dummy_context.broker.submitted[1].reason == EXPIRY_EXIT_REASON


def test_bot_does_not_open_inside_the_expiry_buffer(
    dummy_context: BotContext,
) -> None:
    asyncio.run(
        _feed_probabilities(
            dummy_context,
            probabilities=("0.44", "0.46", "0.49", "0.54"),
            favored_outcome="Up",
            start_ms=296_000,
        )
    )

    assert dummy_context.broker.submitted == []


async def _feed_probabilities(
    context: BotContext,
    *,
    probabilities: tuple[str, ...],
    favored_outcome: str,
    start_ms: int = 100_000,
    half_spread: Decimal = Decimal("0.01"),
    clock_lag_ms: int = 0,
) -> BtcFiveMinuteMomentumBot:
    clock = _TestClock(start_ms)
    market_context = replace(context, markets=_Markets(), clock=clock)
    bot = BtcFiveMinuteMomentumBot(_test_settings())
    for index, raw_probability in enumerate(probabilities):
        timestamp_ms = start_ms + index * 1_000
        clock.current_ms = timestamp_ms + clock_lag_ms
        up_probability = Decimal(raw_probability)
        await bot.on_book(
            market_context,
            _book(
                UP_TOKEN_ID,
                midpoint=up_probability,
                timestamp_ms=timestamp_ms,
                positive_imbalance=favored_outcome == "Up",
                half_spread=half_spread,
            ),
        )
        await bot.on_book(
            market_context,
            _book(
                DOWN_TOKEN_ID,
                midpoint=Decimal("1") - up_probability,
                timestamp_ms=timestamp_ms,
                positive_imbalance=favored_outcome == "Down",
                half_spread=half_spread,
            ),
        )
    return bot


def _test_settings() -> MomentumSettings:
    return MomentumSettings(
        sample_interval_ms=1,
        paired_book_max_skew_ms=0,
        momentum_lookback=2,
        warmup_samples=4,
        minimum_trend=Decimal("0.001"),
        minimum_momentum=Decimal("0.005"),
        noise_trend_multiple=Decimal("0.1"),
        noise_momentum_multiple=Decimal("0.1"),
        entry_delay_ms=0,
        entry_cutoff_ms=5_000,
        force_exit_ms=1_000,
    )


def _book(
    token_id: str,
    *,
    midpoint: Decimal,
    timestamp_ms: int,
    positive_imbalance: bool,
    half_spread: Decimal = Decimal("0.01"),
) -> BookSnapshot:
    bid_size, ask_size = (
        (Decimal("30"), Decimal("10"))
        if positive_imbalance
        else (Decimal("10"), Decimal("30"))
    )
    return BookSnapshot(
        token_id=token_id,
        bids=(BookLevel(midpoint - half_spread, bid_size),),
        asks=(BookLevel(midpoint + half_spread, ask_size),),
        received_at_ms=timestamp_ms,
        market_slug=_slug(timestamp_ms),
        condition_id=CONDITION_ID,
        outcome="Up" if token_id == UP_TOKEN_ID else "Down",
    )


def _slug(timestamp_ms: int) -> str:
    bucket_start = timestamp_ms // 1_000 // 300 * 300
    return f"{BTC_FIVE_MINUTE_SLUG_PREFIX}-{bucket_start}"


class _Markets:
    async def find_by_slug(self, slug: str) -> Market | None:
        return Market(
            condition_id=CONDITION_ID,
            slug=slug,
            question="Bitcoin Up or Down - 5 Minutes",
            minimum_tick_size=Decimal("0.01"),
            minimum_order_size=Decimal("1"),
            neg_risk=False,
            fee_rate=Decimal("0"),
            outcomes=(
                MarketOutcome("Up", UP_TOKEN_ID),
                MarketOutcome("Down", DOWN_TOKEN_ID),
            ),
        )


class _TestClock:
    def __init__(self, current_ms: int) -> None:
        self.current_ms = current_ms

    def now_ms(self) -> int:
        return self.current_ms

    async def sleep(self, seconds: float) -> None:
        self.current_ms += int(seconds * 1_000)
