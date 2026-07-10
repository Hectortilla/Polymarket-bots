import asyncio
from dataclasses import dataclass
from decimal import Decimal

from bots.execution.paper import PaperBroker
from bots.execution.orders import taker_fee_usdc
from bots.execution.paper import (
    MARKET_UNAVAILABLE_MESSAGE,
    NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE,
)
from bots.framework.config import (
    BotConfig,
    DEFAULT_MAX_SLIPPAGE_PCT,
    DEFAULT_PAPER_PORTFOLIO_USDC,
)
from bots.framework.events import (
    BookLevel,
    BookSnapshot,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
    Side,
)
from bots.polymarket.types import Market

DEFAULT_MARKET_SLUG = "btc-up"
DEFAULT_CONDITION_ID = "0xcondition"


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


def _market(
    *,
    slug: str = DEFAULT_MARKET_SLUG,
    condition_id: str = DEFAULT_CONDITION_ID,
    fee_rate: Decimal = Decimal("0"),
) -> Market:
    return Market(
        condition_id=condition_id,
        slug=slug,
        question="Will BTC go up?",
        yes_token_id="123",
        no_token_id="456",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=fee_rate,
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
        return fill.fee_usdc, broker.portfolio.cumulative_fees_usdc, broker.portfolio.cash_usdc

    fill_fee, cumulative_fee, cash_usdc = asyncio.run(run())

    expected_fee = taker_fee_usdc(Decimal("1"), Decimal("0.05"), Decimal("0.40")) + taker_fee_usdc(
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
                    bid_prices=(Decimal("0.70"),),
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
                price=Decimal("0.60"),
                size=Decimal("3"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        position = broker.portfolio.position("123")
        return broker.portfolio.cash_usdc, position.size, position.average_entry_price

    cash_usdc, size, average_entry_price = asyncio.run(run())

    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC - Decimal("0.80") + Decimal("2.10")
    assert size == Decimal("-1")
    assert average_entry_price == Decimal("0.70")


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


def test_portfolio_state_tracks_partial_close() -> None:
    async def run() -> tuple[Decimal, Decimal, Decimal | None]:
        broker = PaperBroker(
            BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
            StaticBooks(
                _book(
                    token_id="123",
                    ask_prices=(Decimal("0.40"),),
                    bid_prices=(Decimal("0.70"),),
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
                price=Decimal("0.60"),
                size=Decimal("1"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        position = broker.portfolio.position("123")
        return broker.portfolio.cash_usdc, position.size, position.average_entry_price

    cash_usdc, size, average_entry_price = asyncio.run(run())

    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC - Decimal("0.80") + Decimal("0.70")
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
                    bid_prices=(Decimal("0.70"),),
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
                price=Decimal("0.60"),
                size=Decimal("2"),
                market_slug=DEFAULT_MARKET_SLUG,
            )
        )
        position = broker.portfolio.position("123")
        return broker.portfolio.cash_usdc, broker.portfolio.positions, position.average_entry_price

    cash_usdc, positions, average_entry_price = asyncio.run(run())

    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC - Decimal("0.80") + Decimal("1.40")
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
                    bid_prices=(Decimal("0.70"),),
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
                price=Decimal("0.60"),
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
        return broker.portfolio.cash_usdc, broker.portfolio.positions, position.average_entry_price

    cash_usdc, positions, average_entry_price = asyncio.run(run())

    assert cash_usdc == DEFAULT_PAPER_PORTFOLIO_USDC + Decimal("1.40") - Decimal("0.80")
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


def _levels(prices: tuple[Decimal, ...], sizes: tuple[Decimal, ...] | None) -> tuple[BookLevel, ...]:
    sizes = sizes or tuple(Decimal("1") for _ in prices)
    return tuple(BookLevel(price=price, size=size) for price, size in zip(prices, sizes, strict=True))


async def _noop_sleep(_: float) -> None:
    return None
