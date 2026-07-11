from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from importlib.metadata import version
from http import HTTPStatus

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

from bots.polymarket.clob import ClobClient
from bots.polymarket.errors import MarketDataError, MarketDataIssue
from bots.polymarket.gamma import GammaClient
from bots.polymarket.types import Market, index_markets_by_token
from bots.polymarket.ws_market import MarketStream


def test_selected_polymarket_sdk_version_is_pinned() -> None:
    assert version("polymarket-client") == "0.1.0b17"


def test_index_markets_rejects_ambiguous_token_metadata() -> None:
    with pytest.raises(MarketDataError) as error:
        index_markets_by_token(
            (_market("first"), replace(_market("second"), yes_token_id="yes-first"))
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


class FakePublicClient:
    def __init__(
        self,
        *,
        markets: dict[str, list[SdkMarket | None]] | None = None,
        book: OrderBook | None = None,
        events: tuple[object, ...] = (),
        market_error: RequestRejectedError | None = None,
        book_error: RequestRejectedError | None = None,
    ) -> None:
        self.markets = markets or {}
        self.book = book
        self.events = events
        self.market_error = market_error
        self.book_error = book_error
        self.requested_slugs: list[str] = []
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
    async def run() -> tuple[tuple[Market | None, ...], Market, list[float]]:
        fake = FakePublicClient(
            markets={
                "alpha": [_sdk_market("alpha")],
                "missing": [None],
                "future": [None, _sdk_market("future")],
            }
        )
        client = GammaClient(fake)  # type: ignore[arg-type]
        resolved = await client.find_many(("alpha", "missing"))
        sleeps: list[float] = []

        async def no_wait(delay: float) -> None:
            sleeps.append(delay)

        future = await client.wait_for_slug(
            "future",
            retry_delay_s=0.25,
            sleep=no_wait,
        )
        return resolved, future, sleeps

    resolved, future, sleeps = asyncio.run(run())

    assert resolved[0] == _market("alpha")
    assert resolved[1] is None
    assert future == _market("future")
    assert sleeps == [0.25]


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
    assert book.received_at_ms == 1_234


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


def _sdk_market(slug: str, *, no_token_id: str | None = "no-token") -> SdkMarket:
    return SdkMarket.model_construct(
        id=f"id-{slug}",
        slug=slug,
        condition_id=f"condition-{slug}",
        question=f"Question {slug}?",
        state=MarketState(negRisk=False),
        outcomes=MarketOutcomes(
            yes=MarketOutcome(label="Yes", tokenId=f"yes-{slug}"),
            no=MarketOutcome(label="No", tokenId=no_token_id),
        ),
        trading=MarketTrading(
            minimumOrderSize="1",
            minimumTickSize="0.01",
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
        yes_token_id=f"yes-{slug}",
        no_token_id="no-token",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0.05"),
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
