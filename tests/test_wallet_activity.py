from __future__ import annotations

import asyncio
from decimal import Decimal

from polybot.framework.events import Side
from polybot.framework.events.wallet_trades import WalletTradeEvent, WalletTradeKind
from polybot.polymarket.wallet_activity.client import WalletActivityClient
from polybot.polymarket.wallet_activity.constants import TRADE_ACTIVITY_TYPE
from polybot.polymarket.wallet_activity.contracts import (
    WalletActivityError,
    WalletActivityIssue,
    WalletTradeSelector,
)
from polybot.polymarket.wallet_activity.normalization import normalize_wallet_trade
from polybot.polymarket.wallet_activity.stream import WalletActivityStream


class Page:
    def __init__(self, *items: object) -> None:
        self.items = items


class FakePaginator:
    def __init__(self, pages: tuple[Page, ...]) -> None:
        self.pages = pages

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for page in self.pages:
            yield page


class FakeClient:
    def __init__(
        self, rows: tuple[object, ...], failing: set[str] | None = None
    ) -> None:
        self.rows = rows
        self.failing = failing or set()
        self.activity_calls: list[tuple[str, tuple[str, ...]]] = []

    def list_trades(self, *, user: str, page_size: int) -> FakePaginator:
        if user in self.failing:
            raise RuntimeError("read failed")
        return FakePaginator((Page(*self.rows),))

    def list_activity(
        self,
        *,
        user: str,
        activity_types: tuple[str, ...],
        page_size: int,
    ) -> FakePaginator:
        self.activity_calls.append((user, activity_types))
        return FakePaginator((Page(*self.rows),))


class FakeStreamSource:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self.rows = rows
        self.wallets: frozenset[str] | None = None

    def trades(self, wallets: frozenset[str]):
        self.wallets = wallets
        return self._iterate()

    async def _iterate(self):
        for row in self.rows:
            yield row


class PollingClient:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def list_trades(self, **kwargs: object) -> FakePaginator:
        self.calls.append(kwargs)
        return FakePaginator((Page(*self.rows),))


class ConcurrentClient(FakeClient):
    def __init__(self, rows_by_wallet: dict[str, tuple[object, ...]]) -> None:
        super().__init__(())
        self.rows_by_wallet = rows_by_wallet
        self.active = 0
        self.peak_active = 0

    def list_trades(self, *, user: str, page_size: int) -> FakePaginator:
        return self._paginator(user)

    def _paginator(self, user: str) -> FakePaginator:
        async def pages():
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            await asyncio.sleep(0)
            self.active -= 1
            yield Page(*self.rows_by_wallet[user])

        paginator = FakePaginator(())
        paginator._iterate = pages  # type: ignore[method-assign]
        return paginator


def _row(wallet: str, tx: str, timestamp: int = 1_700_000_000) -> dict[str, object]:
    return {
        "proxyWallet": wallet,
        "conditionId": "condition",
        "asset": "token",
        "side": "BUY",
        "size": "2.5",
        "price": "0.42",
        "timestamp": timestamp,
        "transactionHash": tx,
        "slug": "market",
    }


def test_normalize_trade_converts_public_row_and_preserves_latency() -> None:
    trade = normalize_wallet_trade(
        _row("0xLeader", "tx-1"), observed_at_ms=1_700_000_001_250
    )
    assert trade is not None
    assert trade.wallet == "0xleader"
    assert trade.side is Side.BUY
    assert trade.size == Decimal("2.5")
    assert trade.trade_timestamp_ms == 1_700_000_000_000
    assert trade.observed_at_ms - trade.trade_timestamp_ms == 1_250


def test_missing_required_trade_fields_are_rejected() -> None:
    assert normalize_wallet_trade(_row("0xleader", ""), observed_at_ms=1) is None
    assert (
        normalize_wallet_trade(
            {**_row("0xleader", "tx-1"), "asset": None}, observed_at_ms=1
        )
        is None
    )


def test_many_wallet_reads_are_sorted_and_report_failures() -> None:
    async def run():
        client = FakeClient((_row("0xfirst", "tx-1"),), {"0xfailing"})
        return await WalletActivityClient(client).latest_trades_many(
            ("0xfirst", "0xfailing")
        )

    result = asyncio.run(run())
    assert [trade.transaction_hash for trade in result.trades] == ["tx-1"]
    assert result.failures[0].wallet == "0xfailing"
    assert result.failures[0].issue is WalletActivityIssue.WALLET_READ_FAILED


def test_latest_activity_filters_trade_rows_and_marks_reconciliation() -> None:
    async def run():
        client = FakeClient((_row("0xleader", "tx-1"),))
        trades = await WalletActivityClient(
            client, now_ms=lambda: 1_700_000_001_000
        ).latest_activity(
            "0xLEADER",
            limit=1,
        )
        return client, trades

    client, trades = asyncio.run(run())
    assert client.activity_calls == [("0xleader", (TRADE_ACTIVITY_TYPE,))]
    assert len(trades) == 1
    assert trades[0].kind is WalletTradeKind.RECONCILIATION


def test_many_wallet_reads_dedupe_per_wallet_but_not_across_wallets() -> None:
    async def run():
        rows = (_row("0xfirst", "same"), _row("0xsecond", "same"))
        return await WalletActivityClient(FakeClient(rows)).latest_trades_many(
            ("0xfirst", "0xsecond"),
        )

    result = asyncio.run(run())
    assert len(result.trades) == 2
    assert {trade.wallet for trade in result.trades} == {"0xfirst", "0xsecond"}


def test_many_wallet_reads_bound_concurrency_and_sort_results() -> None:
    async def run():
        client = ConcurrentClient(
            {
                "0xfirst": (_row("0xfirst", "late", 1_700_000_002),),
                "0xsecond": (_row("0xsecond", "early", 1_700_000_001),),
                "0xthird": (_row("0xthird", "middle", 1_700_000_001),),
            }
        )
        result = await WalletActivityClient(client).latest_trades_many(
            ("0xfirst", "0xsecond", "0xthird"), max_concurrency=2
        )
        return client, result

    client, result = asyncio.run(run())
    assert client.peak_active == 2
    assert [trade.transaction_hash for trade in result.trades] == [
        "early",
        "middle",
        "late",
    ]


def test_boundaries_reject_invalid_limits_and_concurrency() -> None:
    async def run():
        client = FakeClient(())
        assert await WalletActivityClient(client).latest_trades("0xleader", 0) == ()
        assert await WalletActivityClient(client).latest_activity("0xleader", -1) == ()
        try:
            await WalletActivityClient(client).latest_trades_many((), max_concurrency=0)
        except ValueError:
            return
        raise AssertionError("invalid concurrency should be rejected")

    asyncio.run(run())


def test_stream_normalizes_filters_and_validates_events() -> None:
    invalid = {**_row("0xleader", "bad"), "price": "2"}

    async def run():
        source = FakeStreamSource(
            (_row("0xLEADER", "tx-1"), _row("0xother", "tx-2"), invalid)
        )
        stream = WalletActivityStream(source, now_ms=lambda: 1_700_000_001_000)
        trades = [trade async for trade in stream.trades({"0xLeAdEr"})]
        return source, trades

    source, trades = asyncio.run(run())
    assert source.wallets == frozenset({"0xleader"})
    assert [trade.transaction_hash for trade in trades] == ["tx-1"]


def test_stream_accepts_valid_typed_events_and_rejects_invalid_typed_events() -> None:
    valid = WalletTradeEvent(
        wallet="0xLeAdEr",
        condition_id="condition",
        token_id="token",
        side=Side.BUY,
        size=Decimal("1"),
        price=Decimal("0.4"),
        source_id="typed",
        trade_timestamp_ms=1_000,
        observed_at_ms=1_100,
    )
    invalid = WalletTradeEvent(
        wallet="0xleader",
        condition_id="condition",
        token_id="token",
        side=Side.BUY,
        size=Decimal("0"),
        price=Decimal("0.4"),
        source_id="invalid",
        trade_timestamp_ms=1_000,
        observed_at_ms=1_100,
    )

    async def run():
        source = FakeStreamSource((valid, invalid))
        return [
            trade async for trade in WalletActivityStream(source).trades({"0xleader"})
        ]

    trades = asyncio.run(run())
    assert len(trades) == 1
    assert len(trades[0].source_id) == 64
    assert trades[0].wallet == "0xleader"


def test_stream_requires_an_explicit_supported_source() -> None:
    async def run():
        async for _ in WalletActivityStream().trades({"0xleader"}):
            pass

    try:
        asyncio.run(run())
    except WalletActivityError as error:
        assert error.issue is WalletActivityIssue.STREAM_UNAVAILABLE
    else:
        raise AssertionError("stream should fail closed when no source is configured")


def test_polling_starts_at_the_freshness_window_and_discards_stale_rows() -> None:
    now_ms = 1_700_000_010_000

    async def run() -> tuple[PollingClient, WalletTradeEvent]:
        client = PollingClient(
            (
                _row("0xleader", "stale", 1_700_000_000),
                _row("0xleader", "fresh", 1_700_000_009),
            )
        )
        stream = WalletActivityStream(
            WalletActivityClient(client, now_ms=lambda: now_ms),
            max_trade_age_ms=5_000,
            now_ms=lambda: now_ms,
        )
        queue: asyncio.Queue[WalletTradeEvent] = asyncio.Queue()
        task = asyncio.create_task(
            stream._poll(WalletTradeSelector(wallet="0xleader"), queue)
        )
        try:
            return client, await asyncio.wait_for(queue.get(), timeout=0.1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    client, trade = asyncio.run(run())

    assert client.calls[0]["start"] == 1_700_000_004
    assert client.calls[0]["end"] == 1_700_000_010
    assert trade.transaction_hash == "fresh"
