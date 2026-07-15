import asyncio
from dataclasses import dataclass
from decimal import Decimal

import pytest

from polybot.execution.paper import PaperBroker
from polybot.framework.config.models import BotConfig
from polybot.framework.events import FillRejectReason, OrderRequest, Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.polymarket.types import Market, MarketOutcome


@dataclass
class CountingBooks:
    snapshot: BookSnapshot | None = None
    error: Exception | None = None
    calls: int = 0

    async def latest(self, token_id: str) -> BookSnapshot | None:
        self.calls += 1
        if self.error:
            raise self.error
        return self.snapshot


@dataclass
class MarketSource:
    market: object | None = None
    error: Exception | None = None

    async def find_by_slug(self, slug: str) -> object | None:
        if self.error:
            raise self.error
        return self.market


@pytest.mark.parametrize(
    ("order", "reason"),
    (
        (OrderRequest("", Side.BUY, Decimal("0.5"), Decimal("1")), FillRejectReason.MISSING_TOKEN_ID),
        (OrderRequest("token", "HOLD", Decimal("0.5"), Decimal("1")), FillRejectReason.BAD_SIDE),  # type: ignore[arg-type]
        (OrderRequest("token", Side.BUY, Decimal("0"), Decimal("1")), FillRejectReason.BAD_PRICE),
        (OrderRequest("token", Side.BUY, Decimal("NaN"), Decimal("1")), FillRejectReason.BAD_PRICE),
        (OrderRequest("token", Side.BUY, Decimal("0.5"), Decimal("0")), FillRejectReason.BAD_SIZE),
        (OrderRequest("token", Side.BUY, Decimal("0.5"), Decimal("Infinity")), FillRejectReason.BAD_SIZE),
    ),
)
def test_invalid_orders_reject_before_book_lookup(
    order: OrderRequest,
    reason: FillRejectReason,
) -> None:
    books = CountingBooks()
    broker = _broker(books)
    fill = asyncio.run(broker.submit(order))
    assert fill.reject_reason is reason
    assert books.calls == 0
    assert broker.portfolio.positions == {}


@pytest.mark.parametrize("book_error", (None, RuntimeError("offline")))
def test_unavailable_book_rejects_without_mutation(book_error: Exception | None) -> None:
    books = CountingBooks(error=book_error)
    broker = _broker(books)
    fill = asyncio.run(broker.submit(_order()))
    assert fill.reject_reason is FillRejectReason.BOOK_UNAVAILABLE
    assert broker.portfolio.positions == {}


@pytest.mark.parametrize(
    ("book_kwargs", "reason"),
    (
        ({"received_at_ms": 1_001}, FillRejectReason.BOOK_FUTURE_DATED),
        ({"bid": Decimal("0.7"), "ask": Decimal("0.6")}, FillRejectReason.BOOK_CROSSED),
    ),
)
def test_unsafe_books_reject(
    book_kwargs: dict[str, object],
    reason: FillRejectReason,
) -> None:
    broker = _broker(CountingBooks(snapshot=_book(**book_kwargs)))  # type: ignore[arg-type]
    fill = asyncio.run(broker.submit(_order()))
    assert fill.reject_reason is reason
    assert broker.portfolio.positions == {}


def test_book_freshness_uses_actual_post_lookup_clock() -> None:
    times = iter((1_000, 2_000))
    broker = PaperBroker(
        BotConfig(
            name="actual-clock",
            paper_latency_ms=0,
            paper_latency_jitter_ms=0,
            event_max_age_ms=100,
        ),
        CountingBooks(snapshot=_book(received_at_ms=1_000)),
        MarketSource(None),
        sleep_fn=_noop_sleep,
        now_ms_fn=lambda: next(times),
    )
    fill = asyncio.run(broker.submit(_order()))
    assert fill.reject_reason is FillRejectReason.BOOK_STALE


def test_concurrent_source_claim_applies_one_fill() -> None:
    async def run() -> tuple[object, object, Decimal]:
        gate = asyncio.Event()

        async def sleep(_: float) -> None:
            await gate.wait()

        broker = _broker(CountingBooks(snapshot=_book()), sleep_fn=sleep)
        first = asyncio.create_task(broker.submit(_order(source_id="leader\0tx")))
        second = asyncio.create_task(broker.submit(_order(source_id="leader\0tx")))
        await asyncio.sleep(0)
        gate.set()
        first_fill, second_fill = await asyncio.gather(first, second)
        return first_fill, second_fill, broker.portfolio.position("token").size

    first, second, size = asyncio.run(run())
    assert first is second
    assert size == Decimal("1")


def test_failed_source_claim_propagates_and_can_retry() -> None:
    async def run() -> tuple[list[type[BaseException]], Decimal]:
        broker = _broker(CountingBooks(snapshot=_book()))
        original_submit_once = broker._submit_once
        release_failure = asyncio.Event()
        attempts = 0

        async def flaky_submit(order: OrderRequest):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                await release_failure.wait()
                raise RuntimeError("simulated failure")
            return await original_submit_once(order)

        broker._submit_once = flaky_submit  # type: ignore[method-assign]
        order = _order(source_id="leader\0retry")
        owner = asyncio.create_task(broker.submit(order))
        waiter = asyncio.create_task(broker.submit(order))
        await asyncio.sleep(0)
        release_failure.set()
        results = await asyncio.gather(owner, waiter, return_exceptions=True)
        retry = await broker.submit(order)
        return [type(result) for result in results], retry.filled_size

    failures, retry_size = asyncio.run(run())
    assert failures == [RuntimeError, RuntimeError]
    assert retry_size == Decimal("1")


@pytest.mark.parametrize(
    ("markets", "reason"),
    (
        (MarketSource(None), FillRejectReason.MARKET_UNAVAILABLE),
        (MarketSource(error=RuntimeError("offline")), FillRejectReason.MARKET_UNAVAILABLE),
        (MarketSource(type("BadFee", (), {"fee_rate": "0.1"})()), FillRejectReason.MARKET_FEE_INVALID),
    ),
)
def test_market_lookup_failures_reject_without_mutation(
    markets: MarketSource,
    reason: FillRejectReason,
) -> None:
    broker = _broker(CountingBooks(snapshot=_book()), markets=markets)
    fill = asyncio.run(broker.submit(_order()))
    assert fill.reject_reason is reason
    assert broker.portfolio.positions == {}


def _broker(
    books: CountingBooks,
    *,
    sleep_fn=None,
    markets: MarketSource | None = None,
) -> PaperBroker:
    market = Market(
        condition_id="condition",
        slug="market",
        question="Question?",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0"),
        outcomes=(MarketOutcome("Up", "token"), MarketOutcome("Down", "no")),
    )
    return PaperBroker(
        BotConfig(name="paper", paper_latency_ms=0, paper_latency_jitter_ms=0),
        books,
        markets or MarketSource(market),
        sleep_fn=sleep_fn or _noop_sleep,
        now_ms_fn=lambda: 1_000,
    )


async def _noop_sleep(_: float) -> None:
    return None


def _order(source_id: str | None = None) -> OrderRequest:
    return OrderRequest(
        "token",
        Side.BUY,
        Decimal("0.6"),
        Decimal("1"),
        market_slug="market",
        source_id=source_id,
    )


def _book(
    *,
    received_at_ms: int = 1_000,
    bid: Decimal = Decimal("0.4"),
    ask: Decimal = Decimal("0.5"),
) -> BookSnapshot:
    return BookSnapshot(
        "token",
        bids=(BookLevel(bid, Decimal("1")),),
        asks=(BookLevel(ask, Decimal("1")),),
        received_at_ms=received_at_ms,
        market_slug="market",
        condition_id="condition",
    )
