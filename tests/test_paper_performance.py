from __future__ import annotations

import asyncio
import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from polybot.cli.observability.events import DispatchCompleted, StreamReceived
from polybot.cli.observability.observer import NullRuntimeObserver
from polybot.cli.runner.service import run_bot
from polybot.cli.streams.contracts import BookStreamEvent, StreamKind
from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.config.models import BotConfig
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
    Side,
)
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.performance.artifacts import PerformanceArtifacts
from polybot.performance.contracts import (
    PerformanceRunKind,
    RunProvenance,
    RunSelection,
)
from polybot.performance.paper import (
    PaperPerformanceBroker,
    PaperPerformanceObserver,
    PaperPerformanceRecorder,
    PaperPerformanceWarning,
)


class ManualClock:
    def __init__(self, now_ms: int) -> None:
        self.value = now_ms
        self._blocked = asyncio.Event()

    def now_ms(self) -> int:
        return self.value

    async def sleep(self, seconds: float) -> None:
        del seconds
        await self._blocked.wait()


def test_paper_performance_records_books_orders_fills_and_summary(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        clock = ManualClock(1_000)
        portfolio = PaperPortfolio(Decimal("100"))
        artifacts = _artifacts(tmp_path / "results")
        recorder = PaperPerformanceRecorder(
            artifacts,
            portfolio=portfolio,
            clock=clock,
        )
        observer = PaperPerformanceObserver(recorder)

        class FillingBroker:
            async def submit(self, order: OrderRequest) -> FillEvent:
                clock.value = 1_100
                portfolio.apply_fill(
                    token_id=order.token_id,
                    side=order.side,
                    filled_size=order.size,
                    average_price=order.price,
                    fee_usdc=Decimal("0"),
                )
                return FillEvent(
                    order_id="paper-1",
                    token_id=order.token_id,
                    side=order.side,
                    status=OrderStatus.FILLED,
                    requested_size=order.size,
                    filled_size=order.size,
                    average_price=order.price,
                    fee_usdc=Decimal("0"),
                    received_at_ms=clock.now_ms(),
                )

            async def cancel_all(self) -> None:
                return None

        broker = PaperPerformanceBroker(
            FillingBroker(),
            recorder=recorder,
            clock=clock,
        )
        await observer.start(BotConfig(name="paper"))
        stream_event = BookStreamEvent(StreamKind.BOOK, _book())
        observer.emit(StreamReceived(stream_event, 0.0))
        observer.emit(
            DispatchCompleted(
                stream_event,
                DispatchOutcome.accepted_event(),
                0.0,
            )
        )
        await broker.submit(
            OrderRequest(
                token_id="token",
                side=Side.BUY,
                price=Decimal("0.60"),
                size=Decimal("2"),
                market_slug="market",
                condition_id="condition",
                reason="entry",
            )
        )
        clock.value = 2_100
        await observer.stop()

    asyncio.run(run())

    summary = json.loads((tmp_path / "results" / "summary.json").read_text())
    with (tmp_path / "results" / "orders.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        orders = list(csv.DictReader(source))

    assert summary["status"] == "completed"
    assert summary["provenance"]["kind"] == "paper"
    assert summary["metrics"]["event_count"] == 1
    assert summary["metrics"]["accepted_dispatch_count"] == 1
    assert summary["metrics"]["order_count"] == 1
    assert summary["metrics"]["fill_count"] == 1
    assert orders[0]["strategy_reason"] == "entry"


def test_paper_performance_failure_warns_and_does_not_block_broker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run() -> FillEvent:
        clock = ManualClock(1_000)
        portfolio = PaperPortfolio(Decimal("100"))
        artifacts = _artifacts(tmp_path / "results")
        recorder = PaperPerformanceRecorder(
            artifacts,
            portfolio=portfolio,
            clock=clock,
        )
        observer = PaperPerformanceObserver(recorder)

        class Broker:
            async def submit(self, order: OrderRequest) -> FillEvent:
                return FillEvent.rejected(
                    order_id="paper-1",
                    token_id=order.token_id,
                        side=order.side,
                        requested_size=order.size,
                        received_at_ms=clock.now_ms(),
                        reject_reason=FillRejectReason.BOOK_UNAVAILABLE,
                        reject_message="no book",
                    )

            async def cancel_all(self) -> None:
                return None

        await observer.start(BotConfig(name="paper"))
        monkeypatch.setattr(
            artifacts,
            "record_events",
            lambda: (_ for _ in ()).throw(OSError("disk unavailable")),
        )
        with pytest.warns(PaperPerformanceWarning, match="recording disabled"):
            observer.emit(
                StreamReceived(BookStreamEvent(StreamKind.BOOK, _book()), 0.0)
            )
        fill = await PaperPerformanceBroker(
            Broker(), recorder=recorder, clock=clock
        ).submit(
            OrderRequest(
                token_id="token",
                side=Side.BUY,
                price=Decimal("0.60"),
                size=Decimal("1"),
            )
        )
        await observer.stop()
        return fill

    assert asyncio.run(run()).status is OrderStatus.REJECTED


def test_paper_artifact_startup_failure_warns_and_still_invokes_bot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class StopRun(RuntimeError):
        pass

    class Bot(BaseBot):
        started = False

        async def on_start(self, ctx: BotContext) -> None:
            self.started = True
            raise StopRun("stop after startup")

    class Broker:
        portfolio = PaperPortfolio(Decimal("100"))

        async def submit(self, order: OrderRequest) -> FillEvent:
            raise AssertionError("not called")

        async def cancel_all(self) -> None:
            return None

    class Client:
        async def find_by_slug(self, slug: str):
            return None

        async def latest(self, token_id: str):
            return None

        async def latest_trades(self, wallet: str, limit: int):
            return ()

    config = BotConfig(name="paper")
    broker = Broker()
    client = Client()
    ctx = BotContext(
        config=config,
        broker=broker,
        markets=client,
        books=client,
        wallet_activity=client,
    )
    runtime = type(
        "Runtime",
        (),
        {
            "public_client": object(),
            "owned_client": False,
            "gamma": client,
            "clob": client,
            "market_stream": object(),
            "wallet_client": client,
            "position_client": client,
            "followed_wallets": object(),
            "resolution_ledger": object(),
            "registry": object(),
            "paper_broker": broker,
            "broker": broker,
            "ctx": ctx,
        },
    )()

    async def fake_create_runtime(config, observer, *, client):
        return runtime

    monkeypatch.setattr(
        "polybot.cli.runner.service.create_runtime", fake_create_runtime
    )
    monkeypatch.setattr(
        "polybot.cli.runner.service.PerformanceArtifacts",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read only")),
    )
    bot = Bot()

    with pytest.warns(PaperPerformanceWarning, match="could not start"):
        with pytest.raises(StopRun, match="stop after startup"):
            asyncio.run(
                run_bot(
                    bot,
                    config,
                    observer=NullRuntimeObserver(),
                    results_dir=tmp_path / "results",
                    bot_spec="tests:create",
                )
            )

    assert bot.started


def _artifacts(results_dir: Path) -> PerformanceArtifacts:
    return PerformanceArtifacts(
        results_dir,
        provenance=RunProvenance(
            kind=PerformanceRunKind.PAPER,
            bot_spec="tests:create",
            configuration=BotConfig(name="paper"),
        ),
        selection=RunSelection(
            session_id=None,
            start_ms=1_000,
            end_ms=None,
            market_slugs=("market",),
        ),
        initial_cash_usdc=Decimal("100"),
        report_interval_ms=1_000,
        max_book_age_ms=5_000,
    )


def _book() -> BookSnapshot:
    return BookSnapshot(
        token_id="token",
        bids=(BookLevel(Decimal("0.40"), Decimal("10")),),
        asks=(BookLevel(Decimal("0.60"), Decimal("10")),),
        received_at_ms=1_000,
        market_slug="market",
        condition_id="condition",
        outcome="Yes",
    )
