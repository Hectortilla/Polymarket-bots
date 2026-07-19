from __future__ import annotations

import asyncio
import tomllib
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from importlib.metadata import version
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlencode

import pytest
from polymarket import RequestRejectedError
from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketBookPayload,
    MarketPriceChangeEvent,
    MarketPriceChangePayload,
    PriceChange,
)
from polymarket.models.clob.order_book import OrderBook, OrderBookLevel
from polymarket.models.gamma.market import (
    FeeSchedule,
    Market as SdkMarket,
    MarketOutcome,
    MarketOutcomes,
    MarketState,
    MarketTrading,
)

from polybot.polymarket.clob import ClobClient
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.gamma import (
    GAMMA_MARKETS_MAX_SLUGS_PER_REQUEST,
    GAMMA_MARKETS_PAGE_SIZE,
    GAMMA_MARKETS_QUERY_BUDGET,
    GammaClient,
)
from polybot.polymarket.markets import (
    Market,
    MarketOutcome as NormalizedMarketOutcome,
    index_markets_by_token,
)
from polybot.polymarket.ws_market import MarketStream
from polybot.framework.events.resolutions import NO_OUTCOME, YES_OUTCOME


def test_selected_polymarket_sdk_version_matches_project_pin() -> None:
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text()
    )
    dependency = next(
        dependency
        for dependency in project["project"]["dependencies"]
        if dependency.startswith("polymarket-client==")
    )
    assert version("polymarket-client") == dependency.removeprefix("polymarket-client==")


def test_index_markets_rejects_ambiguous_token_metadata() -> None:
    with pytest.raises(MarketDataError) as error:
        second = _market("second")
        index_markets_by_token(
            (
                _market("first"),
                replace(
                    second,
                    outcomes=(
                        replace(second.outcomes[0], token_id="yes-first"),
                        second.outcomes[1],
                    ),
                ),
            )
        )

    assert error.value.issue is MarketDataIssue.AMBIGUOUS_MARKET_METADATA


def test_clob_set_markets_replaces_token_metadata() -> None:
    client = ClobClient(FakePublicClient(), markets=(_market("old"),))  # type: ignore[arg-type]
    client.set_markets((_market("new"),))

    assert client._market_by_token == {
        "yes-new": _market("new"),
        "no-token": _market("new"),
    }


def test_market_stream_set_markets_replaces_token_metadata() -> None:
    stream = MarketStream(FakePublicClient(), markets=(_market("old"),))  # type: ignore[arg-type]
    stream.set_markets((_market("new"),))

    assert stream._market_by_token == {
        "yes-new": _market("new"),
        "no-token": _market("new"),
    }


def test_market_stream_keeps_generation_metadata_during_market_switch() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    old_book = MarketBookEvent(
        type="book",
        payload=MarketBookPayload(
            market="condition-old",
            asset_id="yes-old",
            bids=(_level("0.40", "2"),),
            asks=(_level("0.60", "3"),),
        ),
    )

    class DelayedStream:
        async def __aenter__(self) -> DelayedStream:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def __aiter__(self) -> AsyncIterator[object]:
            return self._iterate()

        async def _iterate(self) -> AsyncIterator[object]:
            started.set()
            await release.wait()
            yield old_book

    class DelayedClient(FakePublicClient):
        async def subscribe(self, spec: object) -> DelayedStream:
            return DelayedStream()

    async def run() -> object:
        stream = MarketStream(
            DelayedClient(),  # type: ignore[arg-type]
            markets=(_market("old"),),
            now_ms=lambda: 2_000,
        )
        books = stream.books({"yes-old"})
        next_book = asyncio.create_task(anext(books))
        await started.wait()
        stream.set_markets((_market("new"),))
        release.set()
        return await next_book

    book = asyncio.run(run())

    assert book.market_slug == "old"
    assert book.condition_id == "condition-old"


class FakeStream:
    def __init__(self, events: tuple[object, ...]) -> None:
        self._events = events

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[object]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[object]:
        for event in self._events:
            yield event


class FakePaginator:
    def __init__(self, items: tuple[SdkMarket, ...]) -> None:
        self._items = items

    def iter_items(self) -> AsyncIterator[SdkMarket]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[SdkMarket]:
        for item in self._items:
            yield item


class FakePublicClient:
    def __init__(
        self,
        *,
        markets: dict[str, list[SdkMarket | None]] | None = None,
        book: OrderBook | None = None,
        events: tuple[object, ...] = (),
        market_error: RequestRejectedError | None = None,
        book_error: RequestRejectedError | None = None,
        closed_markets: frozenset[str] = frozenset(),
    ) -> None:
        self.markets = markets or {}
        self.book = book
        self.events = events
        self.market_error = market_error
        self.book_error = book_error
        self.closed_markets = closed_markets
        self.requested_slugs: list[str] = []
        self.requested_slug_batches: list[tuple[str, ...]] = []
        self.requested_closed: list[bool | None] = []
        self.subscribed_token_ids: tuple[str, ...] = ()

    async def get_market(self, *, slug: str) -> SdkMarket:
        self.requested_slugs.append(slug)
        if self.market_error is not None:
            raise self.market_error
        results = self.markets.get(slug, [None])
        result = results.pop(0) if len(results) > 1 else results[0]
        if result is None:
            raise RequestRejectedError("not found", status=HTTPStatus.NOT_FOUND)
        return result

    def list_markets(
        self,
        *,
        slug: tuple[str, ...],
        page_size: int,
        closed: bool | None = None,
    ) -> FakePaginator:
        assert page_size == GAMMA_MARKETS_PAGE_SIZE
        self.requested_slug_batches.append(slug)
        self.requested_closed.append(closed)
        items = tuple(
            result
            for requested_slug in slug
            if requested_slug not in self.closed_markets or closed is True
            for result in self.markets.get(requested_slug, [None])[:1]
            if result is not None
        )
        return FakePaginator(items)

    async def get_order_book(self, *, token_id: str) -> OrderBook:
        if self.book_error is not None:
            raise self.book_error
        if self.book is None:
            raise RequestRejectedError("not found", status=HTTPStatus.NOT_FOUND)
        return self.book

    async def subscribe(self, spec: object) -> FakeStream:
        self.subscribed_token_ids = tuple(spec.token_ids)  # type: ignore[attr-defined]
        return FakeStream(self.events)


def test_gamma_normalizes_sdk_market_and_rejects_missing_token_id() -> None:
    async def run() -> tuple[Market, MarketDataIssue]:
        valid = _sdk_market("alpha")
        invalid = _sdk_market("broken", no_token_id=None)
        client = GammaClient(
            FakePublicClient(  # type: ignore[arg-type]
                markets={"alpha": [valid], "broken": [invalid]},
            )
        )
        market = await client.find_by_slug("alpha")
        assert market is not None
        with pytest.raises(MarketDataError) as caught:
            await client.find_by_slug("broken")
        return market, caught.value.issue

    market, issue = asyncio.run(run())

    assert market == _market("alpha")
    assert issue is MarketDataIssue.MISSING_TOKEN_ID


def test_gamma_preserves_external_outcome_labels() -> None:
    source = _sdk_market("up-down").model_copy(
        update={
            "outcomes": MarketOutcomes(
                yes=MarketOutcome(label="Up", tokenId="yes-up-down"),
                no=MarketOutcome(label="Down", tokenId="no-token"),
            )
        }
    )

    async def run() -> Market | None:
        return await GammaClient(
            FakePublicClient(markets={"up-down": [source]})  # type: ignore[arg-type]
        ).find_by_slug("up-down")

    market = asyncio.run(run())

    assert market is not None
    assert market.outcomes == (
        NormalizedMarketOutcome("Up", "yes-up-down"),
        NormalizedMarketOutcome("Down", "no-token"),
    )


def test_gamma_preserves_arbitrary_winning_outcome_label() -> None:
    source = _sdk_market("threshold").model_copy(
        update={
            "state": MarketState(negRisk=False, closed=True),
            "outcomes": MarketOutcomes(
                yes=MarketOutcome(
                    label="Above $100k",
                    tokenId="yes-threshold",
                    price=Decimal("1"),
                ),
                no=MarketOutcome(
                    label="At or below $100k",
                    tokenId="no-token",
                    price=Decimal("0"),
                ),
            ),
        }
    )

    async def run() -> Market | None:
        return await GammaClient(
            FakePublicClient(markets={"threshold": [source]})  # type: ignore[arg-type]
        ).find_by_slug("threshold")

    market = asyncio.run(run())

    assert market is not None and market.resolved
    assert market.winning_token_id == "yes-threshold"
    assert market.winning_outcome == "Above $100k"


def test_gamma_normalizes_missing_trading_limits_as_unknown() -> None:
    async def run() -> Market | None:
        client = GammaClient(
            FakePublicClient(  # type: ignore[arg-type]
                markets={
                    "alpha": [
                        _sdk_market(
                            "alpha",
                            minimum_order_size=None,
                            minimum_tick_size=None,
                        )
                    ]
                },
            )
        )
        return await client.find_by_slug("alpha")

    market = asyncio.run(run())

    assert market is not None
    assert (market.minimum_tick_size, market.minimum_order_size) == (None, None)


def test_gamma_rejects_malformed_nested_market_payload() -> None:
    malformed = _sdk_market("malformed").model_copy(update={"outcomes": None})

    async def run() -> MarketDataIssue:
        client = GammaClient(
            FakePublicClient(markets={"malformed": [malformed]}),  # type: ignore[arg-type]
        )
        with pytest.raises(MarketDataError) as caught:
            await client.find_by_slug("malformed")
        return caught.value.issue

    assert asyncio.run(run()) is MarketDataIssue.MISSING_TOKEN_ID


def test_gamma_propagates_non_not_found_rejection() -> None:
    async def run() -> None:
        client = GammaClient(
            FakePublicClient(
                market_error=RequestRejectedError(
                    "server error",
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            )
        )
        with pytest.raises(RequestRejectedError):
            await client.find_by_slug("alpha")

    asyncio.run(run())


def test_gamma_resolves_multiple_slugs_and_retries_future_market() -> None:
    async def run() -> tuple[
        tuple[Market | None, ...],
        Market,
        list[float],
        list[tuple[str, ...]],
        list[str],
    ]:
        fake = FakePublicClient(
            markets={
                "alpha": [_sdk_market("alpha")],
                "missing": [None],
                "future": [None, _sdk_market("future")],
            }
        )
        client = GammaClient(fake)  # type: ignore[arg-type]
        resolved = await client.find_many(("alpha", "missing", "alpha"))
        sleeps: list[float] = []

        async def no_wait(delay: float) -> None:
            sleeps.append(delay)

        future = await client.wait_for_slug(
            "future",
            retry_delay_s=0.25,
            sleep=no_wait,
        )
        return resolved, future, sleeps, fake.requested_slug_batches, fake.requested_slugs

    resolved, future, sleeps, requested_batches, requested_slugs = asyncio.run(run())

    assert resolved[0] == _market("alpha")
    assert resolved[1] is None
    assert resolved[2] == _market("alpha")
    assert requested_batches == [("alpha", "missing"), ("missing",)]
    assert requested_slugs == ["future", "future"]
    assert future == _market("future")
    assert sleeps == [0.25]


def test_gamma_splits_slug_batches_before_query_limit() -> None:
    slugs = tuple(f"{'x' * 1_000}-{index}" for index in range(70))

    async def run() -> tuple[list[tuple[str, ...]], list[bool | None]]:
        fake = FakePublicClient()
        await GammaClient(fake).find_many(slugs)  # type: ignore[arg-type]
        return fake.requested_slug_batches, fake.requested_closed

    requested_batches, requested_closed = asyncio.run(run())
    batches = [
        batch
        for batch, closed in zip(requested_batches, requested_closed)
        if closed is None
    ]

    assert len(batches) > 1
    assert tuple(slug for batch in batches for slug in batch) == slugs
    assert all(
        len(
            urlencode(
                [("slug", slug) for slug in batch]
                + [("limit", str(GAMMA_MARKETS_PAGE_SIZE))]
            )
        )
        <= GAMMA_MARKETS_QUERY_BUDGET
        for batch in batches
    )


def test_gamma_splits_slug_batches_at_api_array_limit() -> None:
    async def run() -> tuple[list[tuple[str, ...]], list[bool | None]]:
        slugs = tuple(f"market-{index}" for index in range(101))
        fake = FakePublicClient()
        await GammaClient(fake).find_many(slugs)  # type: ignore[arg-type]
        return fake.requested_slug_batches, fake.requested_closed

    requested_batches, requested_closed = asyncio.run(run())
    batches = [
        batch
        for batch, closed in zip(requested_batches, requested_closed)
        if closed is None
    ]

    assert [len(batch) for batch in batches] == [
        GAMMA_MARKETS_MAX_SLUGS_PER_REQUEST,
        1,
    ]


def test_gamma_retries_unresolved_slugs_as_closed_markets() -> None:
    async def run() -> tuple[Market | None, list[bool | None]]:
        fake = FakePublicClient(
            markets={"closed": [_sdk_market("closed")]},
            closed_markets=frozenset({"closed"}),
        )
        resolved = await GammaClient(fake).find_many(("closed",))  # type: ignore[arg-type]
        return resolved[0], fake.requested_closed

    market, requested_closed = asyncio.run(run())

    assert market == _market("closed")
    assert requested_closed == [None, True]


def test_clob_normalizes_and_sorts_order_book() -> None:
    source = _order_book(
        bids=(("0.30", "2"), ("0.40", "1")),
        asks=(("0.70", "4"), ("0.60", "3")),
    )

    async def run():
        return await ClobClient(
            FakePublicClient(book=source),  # type: ignore[arg-type]
            markets=(_market("alpha"),),
            now_ms=lambda: 1_234,
        ).latest("yes-alpha")

    book = asyncio.run(run())

    assert book is not None
    assert tuple(level.price for level in book.bids) == (
        Decimal("0.40"),
        Decimal("0.30"),
    )
    assert tuple(level.price for level in book.asks) == (
        Decimal("0.60"),
        Decimal("0.70"),
    )
    assert book.market_slug == "alpha"
    assert book.condition_id == "condition-alpha"
    assert book.outcome == YES_OUTCOME
    assert book.received_at_ms == 1_234


def test_clob_preserves_external_market_label_on_book() -> None:
    market = replace(
        _market("alpha"),
        outcomes=(
            NormalizedMarketOutcome("Up", "yes-alpha"),
            NormalizedMarketOutcome("Down", "no-token"),
        ),
    )

    async def run():
        return await ClobClient(
            FakePublicClient(book=_order_book(bids=(), asks=())),  # type: ignore[arg-type]
            markets=(market,),
        ).latest("yes-alpha")

    book = asyncio.run(run())

    assert book is not None
    assert book.outcome == "Up"


def test_clob_rejects_mismatched_market_identity() -> None:
    market = replace(_market("alpha"), condition_id="condition-other")

    async def run() -> MarketDataIssue:
        client = ClobClient(
            FakePublicClient(book=_order_book(bids=(), asks=())),  # type: ignore[arg-type]
            markets=(market,),
        )
        with pytest.raises(MarketDataError) as caught:
            await client.latest("yes-alpha")
        return caught.value.issue

    assert asyncio.run(run()) is MarketDataIssue.BOOK_IDENTITY_MISMATCH


def test_clob_propagates_non_not_found_rejection() -> None:
    async def run() -> None:
        client = ClobClient(
            FakePublicClient(
                book_error=RequestRejectedError(
                    "server error",
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            )
        )
        with pytest.raises(RequestRejectedError):
            await client.latest("yes-alpha")

    asyncio.run(run())


def test_market_stream_applies_price_changes_to_full_depth() -> None:
    events = (
        MarketBookEvent(
            type="book",
            payload=MarketBookPayload(
                market="condition-alpha",
                asset_id="yes-alpha",
                bids=(_level("0.40", "2"),),
                asks=(_level("0.60", "3"),),
            ),
        ),
        MarketPriceChangeEvent(
            type="price_change",
            payload=MarketPriceChangePayload(
                market="condition-alpha",
                price_changes=(
                    PriceChange(
                        asset_id="yes-alpha",
                        price="0.40",
                        size="0",
                        side="BUY",
                    ),
                    PriceChange(
                        asset_id="yes-alpha",
                        price="0.35",
                        size="5",
                        side="BUY",
                    ),
                ),
            ),
        ),
    )
    fake = FakePublicClient(events=events)

    async def run():
        stream = MarketStream(
            fake,  # type: ignore[arg-type]
            markets=(_market("alpha"),),
            now_ms=lambda: 2_000,
        )
        return [book async for book in stream.books({"yes-alpha"})]

    books = asyncio.run(run())

    assert fake.subscribed_token_ids == ("yes-alpha",)
    assert len(books) == 2
    assert tuple(level.price for level in books[0].bids) == (Decimal("0.40"),)
    assert tuple(level.price for level in books[1].bids) == (Decimal("0.35"),)
    assert all(book.market_slug == "alpha" for book in books)
    assert all(book.outcome == YES_OUTCOME for book in books)


def test_market_stream_keeps_last_valid_depth_after_crossed_update() -> None:
    events = (
        MarketBookEvent(
            type="book",
            payload=MarketBookPayload(
                market="condition-alpha",
                asset_id="yes-alpha",
                bids=(_level("0.40", "2"),),
                asks=(_level("0.60", "3"),),
            ),
        ),
        MarketPriceChangeEvent(
            type="price_change",
            payload=MarketPriceChangePayload(
                market="condition-alpha",
                price_changes=(
                    PriceChange(
                        asset_id="yes-alpha",
                        price="0.70",
                        size="5",
                        side="BUY",
                    ),
                ),
            ),
        ),
    )

    async def run() -> list[object]:
        stream = MarketStream(
            FakePublicClient(events=events),  # type: ignore[arg-type]
            markets=(_market("alpha"),),
            now_ms=lambda: 2_000,
        )
        return [book async for book in stream.books({"yes-alpha"})]

    books = asyncio.run(run())

    assert len(books) == 1
    assert tuple(level.price for level in books[0].bids) == (Decimal("0.40"),)


def test_market_stream_ignores_unknown_price_change_side() -> None:
    invalid_change = PriceChange.model_construct(
        asset_id="yes-alpha",
        price=Decimal("0.50"),
        size=Decimal("5"),
        side="UNKNOWN",
    )
    events = (
        MarketBookEvent(
            type="book",
            payload=MarketBookPayload(
                market="condition-alpha",
                asset_id="yes-alpha",
                bids=(_level("0.40", "2"),),
                asks=(_level("0.60", "3"),),
            ),
        ),
        MarketPriceChangeEvent(
            type="price_change",
            payload=MarketPriceChangePayload(
                market="condition-alpha",
                price_changes=(invalid_change,),
            ),
        ),
    )

    async def run() -> list[object]:
        stream = MarketStream(
            FakePublicClient(events=events),  # type: ignore[arg-type]
            markets=(_market("alpha"),),
            now_ms=lambda: 2_000,
        )
        return [book async for book in stream.books({"yes-alpha"})]

    assert len(asyncio.run(run())) == 1


def test_market_stream_rejects_mismatched_market_identity() -> None:
    events = (
        MarketBookEvent(
            type="book",
            payload=MarketBookPayload(
                market="condition-other",
                asset_id="yes-alpha",
                bids=(_level("0.40", "2"),),
                asks=(_level("0.60", "3"),),
            ),
        ),
    )

    async def run() -> list[object]:
        stream = MarketStream(
            FakePublicClient(events=events),  # type: ignore[arg-type]
            markets=(_market("alpha"),),
            now_ms=lambda: 2_000,
        )
        return [book async for book in stream.books({"yes-alpha"})]

    assert asyncio.run(run()) == []


def _sdk_market(
    slug: str,
    *,
    no_token_id: str | None = "no-token",
    minimum_order_size: str | None = "1",
    minimum_tick_size: str | None = "0.01",
) -> SdkMarket:
    return SdkMarket.model_construct(
        id=f"id-{slug}",
        slug=slug,
        condition_id=f"condition-{slug}",
        question=f"Question {slug}?",
        state=MarketState(negRisk=False),
        outcomes=MarketOutcomes(
            yes=MarketOutcome(label=YES_OUTCOME, tokenId=f"yes-{slug}"),
            no=MarketOutcome(label=NO_OUTCOME, tokenId=no_token_id),
        ),
        trading=MarketTrading(
            minimumOrderSize=minimum_order_size,
            minimumTickSize=minimum_tick_size,
            feesEnabled=True,
            feeSchedule=FeeSchedule(
                exponent=2,
                rate=Decimal("0.05"),
                takerOnly=True,
                rebateRate=Decimal("0"),
            ),
        ),
    )


def _market(slug: str) -> Market:
    return Market(
        condition_id=f"condition-{slug}",
        slug=slug,
        question=f"Question {slug}?",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0.05"),
        outcomes=(
            NormalizedMarketOutcome(YES_OUTCOME, f"yes-{slug}"),
            NormalizedMarketOutcome(NO_OUTCOME, "no-token"),
        ),
    )


def _order_book(
    *,
    bids: tuple[tuple[str, str], ...],
    asks: tuple[tuple[str, str], ...],
) -> OrderBook:
    return OrderBook(
        market="condition-alpha",
        asset_id="yes-alpha",
        bids=tuple(_level(*level) for level in bids),
        asks=tuple(_level(*level) for level in asks),
        min_order_size="1",
        tick_size="0.01",
        neg_risk=False,
        hash="hash",
    )


def _level(price: str, size: str) -> OrderBookLevel:
    return OrderBookLevel(price=price, size=size)
