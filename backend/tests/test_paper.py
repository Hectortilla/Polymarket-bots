import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest
from polybot.execution.order_validation import validate_order
from polybot.execution.orders import MINIMUM_FEE_PRECISION, taker_fee_usdc
from polybot.execution.paper import (
    BACKTEST_COVERAGE_GAP_MESSAGE,
    BACKTEST_DATA_EXHAUSTED_MESSAGE,
    NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE,
    PaperBroker,
)
from polybot.execution.paper.continuity import BookContinuity
from polybot.execution.paper.latency import latency_ms
from polybot.execution.paper.market_data import (
    MARKET_CONSTRAINTS_UNAVAILABLE_MESSAGE,
    MARKET_NOT_TRADABLE_MESSAGE,
    MARKET_UNAVAILABLE_MESSAGE,
)
from polybot.framework.clock import ClockDataExhaustedError
from polybot.framework.config.constants import (
    DEFAULT_MAX_SLIPPAGE_PCT,
    DEFAULT_PAPER_PORTFOLIO_USDC,
)
from polybot.framework.config.models import BotConfig
from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
    Side,
)
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.markets import Market, MarketOutcome

DEFAULT_MARKET_SLUG = "btc-up"
DEFAULT_CONDITION_ID = "0xcondition"


@pytest.mark.parametrize("source_id", ("", "line\nbreak", "line\rbreak"))
def test_order_validation_rejects_non_line_safe_source_ids(source_id: str) -> None:
    rejection = validate_order(
        OrderRequest(
            token_id="token",
            side=Side.BUY,
            price=Decimal("0.5"),
            size=Decimal("1"),
            source_id=source_id,
        )
    )

    assert rejection is not None
    assert rejection[0] is FillRejectReason.INVALID_SOURCE_ID


@pytest.mark.parametrize(
    "changes",
    (
        {
            "status": OrderStatus.FILLED,
            "filled_size": Decimal("0"),
            "average_price": None,
        },
        {
            "status": OrderStatus.PARTIAL,
            "filled_size": Decimal("1"),
            "average_price": Decimal("0.5"),
            "requested_size": Decimal("1"),
        },
        {
            "status": OrderStatus.REJECTED,
            "filled_size": Decimal("1"),
            "average_price": Decimal("0.5"),
            "reject_reason": FillRejectReason.BAD_SIZE,
            "reject_message": "bad",
        },
    ),
)
def test_fill_event_owns_status_and_execution_invariants(
    changes: dict[str, object],
) -> None:
    values = {
        "order_id": "order",
        "token_id": "token",
        "side": Side.BUY,
        "status": OrderStatus.FILLED,
        "requested_size": Decimal("1"),
        "filled_size": Decimal("1"),
        "average_price": Decimal("0.5"),
        "fee_usdc": Decimal("0"),
        "received_at_ms": 1,
    }
    values.update(changes)

    with pytest.raises(ValueError):
        FillEvent(**values)  # type: ignore[arg-type]


@dataclass(slots=True)
class StaticBooks:
    snapshot: BookSnapshot | None

    async def latest(self, token_id: str) -> BookSnapshot | None:
        return self.snapshot


@dataclass(slots=True)
class SwitchingBooks:
    decision_snapshot: BookSnapshot
    fill_snapshot: BookSnapshot
    slept: bool = False

    async def latest(self, token_id: str) -> BookSnapshot | None:
        return self.fill_snapshot if self.slept else self.decision_snapshot


@dataclass(slots=True)
class StaticMarkets:
    market: Market | None

    async def find_by_slug(self, slug: str) -> Market | None:
        return self.market


@dataclass(slots=True)
class SwitchingMarkets:
    initial_market: Market
    final_market: Market
    calls: int = 0

    async def find_by_slug(self, slug: str) -> Market | None:
        self.calls += 1
        return self.initial_market if self.calls == 1 else self.final_market


@dataclass(slots=True)
class RecordingClock:
    current_ms: int
    exhausted_at_ms: int | None = None
    sleeps: list[float] | None = None

    def now_ms(self) -> int:
        return self.current_ms

    async def sleep(self, seconds: float) -> None:
        if self.sleeps is not None:
            self.sleeps.append(seconds)
        requested_ms = self.current_ms + round(seconds * 1000)
        if self.exhausted_at_ms is not None and requested_ms > self.exhausted_at_ms:
            self.current_ms = self.exhausted_at_ms
            raise ClockDataExhaustedError
        self.current_ms = requested_ms


class UnexpectedBooks:
    async def latest(self, token_id: str) -> BookSnapshot | None:
        raise AssertionError("book lookup must not run after clock exhaustion")


@dataclass(slots=True)
class MutableContinuity:
    value: BookContinuity

    def book_continuity(self, token_id: str) -> BookContinuity | None:
        return self.value if token_id == "123" else None


def _market(
    *,
    slug: str = DEFAULT_MARKET_SLUG,
    condition_id: str = DEFAULT_CONDITION_ID,
    yes_token_id: str = "123",
    no_token_id: str = "456",
    fee_rate: Decimal = Decimal("0"),
) -> Market:
    return Market(
        condition_id=condition_id,
        slug=slug,
        question="Will BTC go up?",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=fee_rate,
        outcomes=(
            MarketOutcome("Up", yes_token_id),
            MarketOutcome("Down", no_token_id),
        ),
        active=True,
        closed=False,
        order_book_enabled=True,
        accepting_orders=True,
    )


def test_paper_broker_uses_fill_time_book_not_decision_time_book() -> None:
    async def run() -> tuple[Decimal, int]:
        books = SwitchingBooks(
            decision_snapshot=_book(
                token_id="123",
                ask_prices=(Decimal("0.30"),),
                received_at_ms=900,
                market_slug=DEFAULT_MARKET_SLUG,
            ),
            fill_snapshot=_book(
                token_id="123",
                ask_prices=(Decimal("0.70"),),
                received_at_ms=1_100,
                market_slug=DEFAULT_MARKET_SLUG,
            ),
        )

        async def sleep_fn(_: float) -> None:
            books.slept = True

        broker = PaperBroker(
            BotConfig(
                name="paper",
                paper_latency_ms=100,
                paper_latency_jitter_ms=0,
            ),
            books,
            StaticMarkets(_market()),
            sleep_fn=sleep_fn,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.75"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.average_price or Decimal("0"), fill.received_at_ms

    average_price, received_at_ms = asyncio.run(run())

    assert average_price == Decimal("0.70")
    assert received_at_ms == 1_100


def test_paper_broker_uses_supplied_clock_for_latency_and_fill_time() -> None:
    async def run() -> tuple[Decimal | None, int, list[float]]:
        sleeps: list[float] = []
        clock = RecordingClock(1_000, sleeps=sleeps)
        broker = PaperBroker(
            BotConfig(
                name="paper",
                paper_latency_ms=100,
                paper_latency_jitter_ms=0,
            ),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_100,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            clock=clock,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.average_price, fill.received_at_ms, sleeps

    average_price, received_at_ms, sleeps = asyncio.run(run())

    assert average_price == Decimal("0.40")
    assert received_at_ms == 1_100
    assert sleeps == [0.1]


def test_paper_broker_maps_clock_exhaustion_to_stable_rejection() -> None:
    async def run():
        broker = PaperBroker(
            BotConfig(
                name="paper",
                paper_latency_ms=100,
                paper_latency_jitter_ms=0,
            ),
            UnexpectedBooks(),
            StaticMarkets(_market()),
            clock=RecordingClock(1_000, exhausted_at_ms=1_050),
        )
        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill, broker.portfolio.cash_usdc

    fill, cash_usdc = asyncio.run(run())

    assert fill.status is OrderStatus.REJECTED
    assert fill.reject_reason is FillRejectReason.BACKTEST_DATA_EXHAUSTED
    assert fill.reject_message == BACKTEST_DATA_EXHAUSTED_MESSAGE
    assert fill.received_at_ms == 1_050
    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC


def test_paper_broker_rejects_latency_that_crosses_a_book_blackout() -> None:
    async def run():
        continuity = MutableContinuity(BookContinuity(revision=0, blackout=False))

        async def sleep_fn(_: float) -> None:
            continuity.value = BookContinuity(revision=1, blackout=False)

        broker = PaperBroker(
            BotConfig(
                name="paper",
                paper_latency_ms=100,
                paper_latency_jitter_ms=0,
            ),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_100,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=sleep_fn,
            now_ms_fn=lambda: 1_100,
            continuity_source=continuity,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill, broker.portfolio.cash_usdc

    fill, cash_usdc = asyncio.run(run())

    assert fill.status is OrderStatus.REJECTED
    assert fill.reject_reason is FillRejectReason.BACKTEST_COVERAGE_GAP
    assert fill.reject_message == BACKTEST_COVERAGE_GAP_MESSAGE
    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC


def test_blackout_rejection_precedes_data_exhaustion_for_affected_order() -> None:
    async def run():
        clock = RecordingClock(1_000, exhausted_at_ms=1_050)
        broker = PaperBroker(
            BotConfig(
                name="paper",
                paper_latency_ms=100,
                paper_latency_jitter_ms=0,
            ),
            UnexpectedBooks(),
            StaticMarkets(_market()),
            clock=clock,
            continuity_source=MutableContinuity(
                BookContinuity(revision=1, blackout=True)
            ),
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill, broker.portfolio.cash_usdc

    fill, cash_usdc = asyncio.run(run())

    assert fill.status is OrderStatus.REJECTED
    assert fill.reject_reason is FillRejectReason.BACKTEST_COVERAGE_GAP
    assert fill.reject_message == BACKTEST_COVERAGE_GAP_MESSAGE
    assert fill.received_at_ms == 1_050
    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC


def test_paper_broker_rejects_ambiguous_clock_overrides() -> None:
    with pytest.raises(ValueError, match="clock cannot be combined"):
        PaperBroker(
            BotConfig(name="paper"),
            StaticBooks(None),
            StaticMarkets(None),
            clock=RecordingClock(1_000),
            sleep_fn=_noop_sleep,
        )


def test_larger_order_has_equal_or_worse_average_price() -> None:
    async def run() -> tuple[Decimal, Decimal]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(
                        Decimal("0.40"),
                        Decimal("0.60"),
                        Decimal("0.80"),
                    ),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        small = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.85"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        large = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.85"),
                size=Decimal("3"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return small.average_price or Decimal("0"), large.average_price or Decimal("0")

    small_average, large_average = asyncio.run(run())

    assert large_average >= small_average


def test_partial_fill_never_exceeds_available_depth() -> None:
    async def run() -> tuple[Decimal, OrderStatus]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"), Decimal("0.50")),
                    ask_sizes=(Decimal("2"), Decimal("1")),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.60"),
                size=Decimal("5"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.filled_size, fill.status

    filled_size, status = asyncio.run(run())

    assert filled_size == Decimal("3")
    assert status is OrderStatus.PARTIAL


def test_slippage_cap_rejects_bad_levels() -> None:
    async def run() -> tuple[Decimal, OrderStatus, FillRejectReason | None, str | None]:
        broker = PaperBroker(
            BotConfig(
                name="paper",
                paper_latency_ms=0,
                paper_latency_jitter_ms=0,
                max_slippage_pct=DEFAULT_MAX_SLIPPAGE_PCT,
            ),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.52"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.filled_size, fill.status, fill.reject_reason, fill.reject_message

    filled_size, status, reject_reason, reject_message = asyncio.run(run())

    assert filled_size == Decimal("0")
    assert status is OrderStatus.REJECTED
    assert reject_reason is FillRejectReason.NO_DEPTH_WITHIN_SLIPPAGE
    assert reject_message == NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE


def test_fee_is_accumulated_across_multiple_levels() -> None:
    async def run() -> tuple[Decimal, Decimal, Decimal]:
        markets = StaticMarkets(_market(fee_rate=Decimal("0.05")))
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"), Decimal("0.60")),
                    ask_sizes=(Decimal("1"), Decimal("1")),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            markets,
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.80"),
                size=Decimal("2"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return (
            fill.fee_usdc,
            broker.portfolio.cumulative_fees_usdc,
            broker.portfolio.cash_usdc,
        )

    fill_fee, cumulative_fee, cash_usdc = asyncio.run(run())

    expected_fee = taker_fee_usdc(
        Decimal("1"), Decimal("0.05"), Decimal("0.40")
    ) + taker_fee_usdc(
        Decimal("1"),
        Decimal("0.05"),
        Decimal("0.60"),
    )
    assert fill_fee == expected_fee
    assert cumulative_fee == expected_fee
    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC - Decimal("1.00") - expected_fee


def test_portfolio_state_tracks_buy_then_sell_flip() -> None:
    async def run() -> tuple[Decimal, Decimal, Decimal | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    bid_prices=(Decimal("0.30"),),
                    ask_sizes=(Decimal("2"),),
                    bid_sizes=(Decimal("3"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("2"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.SELL,
                price=Decimal("0.30"),
                size=Decimal("3"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        position = broker.portfolio.position("123")
        return broker.portfolio.cash_usdc, position.size, position.average_entry_price

    cash_usdc, size, average_entry_price = asyncio.run(run())

    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC - Decimal("0.80") + Decimal("0.90")
    assert size == Decimal("-1")
    assert average_entry_price == Decimal("0.30")


def test_paper_broker_rejects_book_token_mismatch() -> None:
    async def run() -> tuple[OrderStatus, FillRejectReason | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="456",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.status, fill.reject_reason

    status, reject_reason = asyncio.run(run())

    assert status is OrderStatus.REJECTED
    assert reject_reason is FillRejectReason.BOOK_MISMATCH


def test_paper_broker_rejects_book_missing_market_identity() -> None:
    async def run() -> tuple[OrderStatus, FillRejectReason | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                    condition_id=None,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.status, fill.reject_reason

    status, reject_reason = asyncio.run(run())

    assert status is OrderStatus.REJECTED
    assert reject_reason is FillRejectReason.BOOK_MISMATCH


def test_paper_broker_rejects_non_finite_book_level() -> None:
    async def run() -> tuple[OrderStatus, FillRejectReason | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    ask_sizes=(Decimal("Infinity"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.status, fill.reject_reason

    status, reject_reason = asyncio.run(run())

    assert status is OrderStatus.REJECTED
    assert reject_reason is FillRejectReason.BAD_BOOK_LEVEL


def test_paper_broker_rejects_duplicate_book_prices() -> None:
    async def run() -> tuple[OrderStatus, FillRejectReason | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"), Decimal("0.40")),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )
        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.status, fill.reject_reason

    status, reject_reason = asyncio.run(run())

    assert status is OrderStatus.REJECTED
    assert reject_reason is FillRejectReason.BAD_BOOK_LEVEL


def test_paper_broker_rejects_missing_market_metadata() -> None:
    async def run() -> tuple[OrderStatus, FillRejectReason | None, str | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(None),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.status, fill.reject_reason, fill.reject_message

    status, reject_reason, reject_message = asyncio.run(run())

    assert status is OrderStatus.REJECTED
    assert reject_reason is FillRejectReason.MARKET_UNAVAILABLE
    assert reject_message == MARKET_UNAVAILABLE_MESSAGE


def test_paper_broker_rejects_fill_time_market_metadata_mismatch_without_mutation() -> (
    None
):
    async def run() -> tuple[
        OrderStatus, FillRejectReason | None, Decimal, dict[str, object]
    ]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market(condition_id="different-condition")),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )
        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
                condition_id=DEFAULT_CONDITION_ID,
            )
        )
        return (
            fill.status,
            fill.reject_reason,
            broker.portfolio.cash_usdc,
            broker.portfolio.positions,
        )

    status, reject_reason, cash_usdc, positions = asyncio.run(run())

    assert status is OrderStatus.REJECTED
    assert reject_reason is FillRejectReason.MARKET_METADATA_MISMATCH
    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC
    assert positions == {}


def test_latency_uses_an_explicit_jitter_offset() -> None:
    assert latency_ms(100, 5, 4) == 104
    with pytest.raises(ValueError, match="outside the configured range"):
        latency_ms(100, 5, 6)


def test_paper_broker_rejects_invalid_market_fee_rate() -> None:
    async def run() -> tuple[OrderStatus, FillRejectReason | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market(fee_rate=Decimal("-0.01"))),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.status, fill.reject_reason

    status, reject_reason = asyncio.run(run())

    assert status is OrderStatus.REJECTED
    assert reject_reason is FillRejectReason.MARKET_FEE_INVALID


def test_paper_broker_revalidates_market_after_final_book_lookup() -> None:
    async def run() -> tuple[FillRejectReason | None, int]:
        initial_market = _market()
        final_market = replace(
            initial_market,
            resolved=True,
            winning_token_id="123",
            winning_outcome="Up",
        )
        markets = SwitchingMarkets(initial_market, final_market)
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            markets,
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )
        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.reject_reason, markets.calls

    reject_reason, calls = asyncio.run(run())

    assert reject_reason is FillRejectReason.MARKET_RESOLVED
    assert calls == 2


def test_paper_broker_rechecks_book_after_delayed_final_market_lookup() -> None:
    async def run() -> FillRejectReason | None:
        clock = {"now_ms": 1_000}

        class DelayedSecondLookupMarkets:
            calls = 0

            async def find_by_slug(self, slug: str) -> Market:
                self.calls += 1
                if self.calls == 2:
                    clock["now_ms"] = 1_200
                return _market()

        broker = PaperBroker(
            BotConfig(
                name="paper",
                paper_latency_ms=0,
                paper_latency_jitter_ms=0,
                event_max_age_ms=100,
            ),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            DelayedSecondLookupMarkets(),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: clock["now_ms"],
        )
        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.reject_reason

    assert asyncio.run(run()) is FillRejectReason.BOOK_STALE


@pytest.mark.parametrize(
    ("market", "reason", "message"),
    (
        (
            replace(_market(), closed=True),
            FillRejectReason.MARKET_UNAVAILABLE,
            MARKET_NOT_TRADABLE_MESSAGE,
        ),
        (
            replace(_market(), accepting_orders=None),
            FillRejectReason.MARKET_UNAVAILABLE,
            MARKET_NOT_TRADABLE_MESSAGE,
        ),
        (
            replace(_market(), minimum_tick_size=None),
            FillRejectReason.MARKET_UNAVAILABLE,
            MARKET_CONSTRAINTS_UNAVAILABLE_MESSAGE,
        ),
    ),
)
def test_paper_broker_rejects_unavailable_market_state_and_limits(
    market: Market,
    reason: FillRejectReason,
    message: str,
) -> None:
    async def run() -> tuple[FillRejectReason | None, str | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(market),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )
        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.reject_reason, fill.reject_message

    reject_reason, reject_message = asyncio.run(run())

    assert reject_reason is reason
    assert reject_message == message


@pytest.mark.parametrize(
    ("price", "size", "reason"),
    (
        (Decimal("0.421"), Decimal("1"), FillRejectReason.BAD_PRICE),
        (Decimal("0.42"), Decimal("0.5"), FillRejectReason.BAD_SIZE),
    ),
)
def test_paper_broker_enforces_market_order_limits(
    price: Decimal,
    size: Decimal,
    reason: FillRejectReason,
) -> None:
    async def run() -> FillRejectReason | None:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )
        fill = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=price,
                size=size,
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        return fill.reject_reason

    assert asyncio.run(run()) is reason


def test_paper_broker_dedupes_source_id() -> None:
    async def run() -> tuple[Decimal, Decimal, str, str]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        order = OrderRequest(
            token_id="123",
            side=Side.BUY,
            price=Decimal("0.50"),
            size=Decimal("1"),
            market_slug=DEFAULT_MARKET_SLUG,
            source_id="leader-trade-1",
        )
        first_fill = await broker.submit(order)
        first_cash = broker.portfolio.cash_usdc
        second_fill = await broker.submit(order)
        second_cash = broker.portfolio.cash_usdc
        return first_cash, second_cash, first_fill.order_id, second_fill.order_id

    first_cash, second_cash, first_order_id, second_order_id = asyncio.run(run())

    assert first_cash == DEFAULT_PAPER_PORTFOLIO_USDC - Decimal("0.40")
    assert second_cash == first_cash
    assert first_order_id == second_order_id


def test_invalid_source_order_does_not_claim_source_id() -> None:
    async def run() -> tuple[FillRejectReason | None, OrderStatus, Decimal]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )
        invalid = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("0"),
                market_slug=DEFAULT_MARKET_SLUG,
                source_id="retryable-source",
            )
        )
        valid = await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
                source_id="retryable-source",
            )
        )
        return invalid.reject_reason, valid.status, valid.filled_size

    reject_reason, status, filled_size = asyncio.run(run())

    assert reject_reason is FillRejectReason.BAD_SIZE
    assert status is OrderStatus.FILLED
    assert filled_size == Decimal("1")


def test_portfolio_state_tracks_partial_close() -> None:
    async def run() -> tuple[Decimal, Decimal, Decimal | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    bid_prices=(Decimal("0.30"),),
                    ask_sizes=(Decimal("2"),),
                    bid_sizes=(Decimal("3"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("2"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.SELL,
                price=Decimal("0.30"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        position = broker.portfolio.position("123")
        return broker.portfolio.cash_usdc, position.size, position.average_entry_price

    cash_usdc, size, average_entry_price = asyncio.run(run())

    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC - Decimal("0.80") + Decimal("0.30")
    assert size == Decimal("1")
    assert average_entry_price == Decimal("0.40")


def test_portfolio_state_tracks_exact_close() -> None:
    async def run() -> tuple[Decimal, dict[str, object], Decimal | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    bid_prices=(Decimal("0.30"),),
                    ask_sizes=(Decimal("2"),),
                    bid_sizes=(Decimal("3"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("2"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.SELL,
                price=Decimal("0.30"),
                size=Decimal("2"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        position = broker.portfolio.position("123")
        return (
            broker.portfolio.cash_usdc,
            broker.portfolio.positions,
            position.average_entry_price,
        )

    cash_usdc, positions, average_entry_price = asyncio.run(run())

    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC - Decimal("0.80") + Decimal("0.60")
    assert "123" not in positions
    assert average_entry_price is None


def test_portfolio_state_tracks_short_then_buy_close() -> None:
    async def run() -> tuple[Decimal, dict[str, object], Decimal | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    bid_prices=(Decimal("0.30"),),
                    ask_sizes=(Decimal("2"),),
                    bid_sizes=(Decimal("3"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
        )

        await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.SELL,
                price=Decimal("0.30"),
                size=Decimal("2"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        await broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("2"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        position = broker.portfolio.position("123")
        return (
            broker.portfolio.cash_usdc,
            broker.portfolio.positions,
            position.average_entry_price,
        )

    cash_usdc, positions, average_entry_price = asyncio.run(run())

    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC + Decimal("0.60") - Decimal("0.80")
    assert "123" not in positions
    assert average_entry_price is None


def _book(
    *,
    token_id: str,
    ask_prices: tuple[Decimal, ...] = (),
    bid_prices: tuple[Decimal, ...] = (),
    ask_sizes: tuple[Decimal, ...] | None = None,
    bid_sizes: tuple[Decimal, ...] | None = None,
    received_at_ms: int,
    market_slug: str | None = DEFAULT_MARKET_SLUG,
    condition_id: str | None = DEFAULT_CONDITION_ID,
) -> BookSnapshot:
    return BookSnapshot(
        token_id=token_id,
        bids=_levels(bid_prices, bid_sizes),
        asks=_levels(ask_prices, ask_sizes),
        received_at_ms=received_at_ms,
        market_slug=market_slug,
        condition_id=condition_id,
    )


def _levels(
    prices: tuple[Decimal, ...],
    sizes: tuple[Decimal, ...] | None,
) -> tuple[BookLevel, ...]:
    sizes = sizes or tuple(Decimal("1") for _ in prices)
    return tuple(
        BookLevel(price=price, size=size)
        for price, size in zip(prices, sizes, strict=True)
    )


async def _noop_sleep(_: float) -> None:
    return None


def test_resolution_during_final_book_read_cannot_reopen_position():
    market = _market()
    book = _book(
        token_id="123",
        ask_prices=(Decimal("0.40"),),
        received_at_ms=1000,
        market_slug=market.slug,
    )
    resolution = MarketResolutionEvent(
        condition_id=market.condition_id,
        market_slug=market.slug,
        token_ids=market.token_ids,
        winning_token_id=market.token_ids[0],
        winning_outcome="Up",
        resolved_at_ms=1000,
        source="test-resolution",
    )

    class ResolvingBooks:
        calls = 0

        async def latest(self, token_id):
            self.calls += 1
            if self.calls == 2:
                broker.settle_market(resolution)
            return book

    class Markets:
        async def find_by_slug(self, slug):
            return market

    broker = PaperBroker(
        BotConfig(
            name="settlement-race", paper_latency_ms=0, paper_latency_jitter_ms=0
        ),
        ResolvingBooks(),
        Markets(),
        now_ms_fn=lambda: 1000,
    )
    fill = asyncio.run(
        broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=market.slug,
                condition_id=market.condition_id,
            )
        )
    )
    assert fill.reject_reason is FillRejectReason.MARKET_RESOLVED
    assert broker.position_market_refs == {}
    assert broker.settle_market(resolution) == ()


@pytest.mark.parametrize("precision", [2, 4, MINIMUM_FEE_PRECISION, 60])
def test_fee_has_explicit_precision_rounding_and_trap_policy(precision):
    with localcontext() as context:
        context.prec = precision
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert taker_fee_usdc(
            Decimal("1.23456789"), Decimal(".12345678"), Decimal(".87654321")
        ) == Decimal(".01649")


@pytest.mark.parametrize("blackout", [False, True])
def test_continuity_change_during_final_book_read_rejects_without_mutation(blackout):
    continuity = MutableContinuity(BookContinuity(revision=0, blackout=False))

    class ChangingBooks:
        calls = 0

        async def latest(self, token_id):
            self.calls += 1
            if self.calls == 2:
                continuity.value = BookContinuity(revision=1, blackout=blackout)
            return _book(
                token_id="123",
                ask_prices=(Decimal("0.40"),),
                received_at_ms=1000,
                market_slug=DEFAULT_MARKET_SLUG,
            )

    broker = PaperBroker(
        BotConfig(name="continuity", paper_latency_ms=0, paper_latency_jitter_ms=0),
        ChangingBooks(),
        StaticMarkets(_market()),
        now_ms_fn=lambda: 1000,
        continuity_source=continuity,
    )
    fill = asyncio.run(
        broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
    )
    assert fill.reject_reason is FillRejectReason.BACKTEST_COVERAGE_GAP
    assert broker.portfolio.cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC
    assert broker.position_market_refs == {}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            {"resolved": True, "winning_token_id": "123", "winning_outcome": "Up"},
            FillRejectReason.MARKET_RESOLVED,
        ),
        ({"closed": True}, FillRejectReason.MARKET_UNAVAILABLE),
        ({"fee_rate": Decimal("NaN")}, FillRejectReason.MARKET_FEE_INVALID),
    ],
)
def test_metadata_change_during_final_book_read_rejects_without_mutation(
    change, reason
):
    market = _market()

    class ChangingBooks:
        calls = 0

        async def latest(self, token_id):
            nonlocal market
            self.calls += 1
            if self.calls == 2:
                market = replace(market, **change)
            return _book(
                token_id="123",
                ask_prices=(Decimal("0.40"),),
                received_at_ms=1000,
                market_slug=DEFAULT_MARKET_SLUG,
            )

    class CurrentMarkets:
        async def find_by_slug(self, slug):
            return market

    broker = PaperBroker(
        BotConfig(name="metadata-race", paper_latency_ms=0, paper_latency_jitter_ms=0),
        ChangingBooks(),
        CurrentMarkets(),
        now_ms_fn=lambda: 1000,
    )
    fill = asyncio.run(
        broker.submit(
            OrderRequest(
                token_id="123",
                side=Side.BUY,
                price=Decimal("0.50"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
    )
    assert fill.reject_reason is reason
    assert broker.portfolio.cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC
    assert broker.position_market_refs == {}


def test_host_execution_fence_prevents_fill_after_latency():

    class LostOwnership(RuntimeError):
        pass

    checked = False

    @asynccontextmanager
    async def ownership():
        nonlocal checked
        checked = True
        raise LostOwnership("execution lease lost")
        yield

    async def scenario():
        broker = PaperBroker(
            BotConfig(name="fenced", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    received_at_ms=1_000,
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            ),
            StaticMarkets(_market()),
            sleep_fn=_noop_sleep,
            now_ms_fn=lambda: 1_000,
            execution_scope=ownership,
        )
        before = broker.snapshot()
        with pytest.raises(LostOwnership):
            await broker.submit(
                OrderRequest(
                    token_id="123",
                    side=Side.BUY,
                    price=Decimal("0.85"),
                    size=Decimal("1"),
                    market_slug=DEFAULT_MARKET_SLUG,
                )
            )
        assert checked
        assert broker.snapshot() == before

    asyncio.run(scenario())
