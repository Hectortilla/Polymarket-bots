import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from polybot.async_io import run_blocking
from polybot.cli.config import load_dotenv, parse_overrides
from polybot.cli.dashboard.state import DashboardState
from polybot.framework.streams import StreamPlan, StreamRelation, StreamRule
from polybot.cli.entrypoint import (
    INTERACTIVE_TERMINAL_REQUIRED_MESSAGE,
    TERM_ENV_KEY,
    _dashboard_enabled,
    main,
)
from polybot.cli.factories import load_bot
from polybot.cli.markets import resolve_plan_markets
from polybot.cli.runner.service import run_bot
from polybot.cli.runner.dispatch import dispatch_stream_event
from polybot.cli.runner.streams import wait_for_stream_plan_change
from polybot.cli.streams.contracts import ResolutionStreamEvent, StreamKind, WalletStreamEvent
from polybot.cli.streams.merger import merge_streams
from polybot.cli.streams.telemetry import StreamTelemetry
from polybot.cli.observability.events import (
    BootstrapPhase,
    BootstrapProgress,
    RuntimeState,
    RuntimeStateChanged,
    RuntimeFailed,
    MarketSettled,
)
from polybot.cli.observability.observer import RuntimeObserver
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig, BotMode
from polybot.framework.context import BotContext
from polybot.framework.events import Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent, YES_OUTCOME
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.markets import MarketPlan, MarketSubscription
from polybot.framework.runner import BotRunner
from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.polymarket.types import Market, MarketOutcome
from polybot.polymarket.types import MarketTradeHint
from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason
from polybot.cli.streams.contracts import BookStreamEvent


def test_load_dotenv_does_not_override_environment(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        'FROM_FILE=value\nexport QUOTED="hello world"\nMULTILINE="first line\nsecond line"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FROM_FILE", "existing")
    load_dotenv(dotenv)

    assert os.environ["FROM_FILE"] == "existing"
    assert os.environ["QUOTED"] == "hello world"
    assert os.environ["MULTILINE"] == "first line\nsecond line"


def test_parse_overrides_converts_config_types() -> None:
    overrides = parse_overrides(
        ["paper_latency_ms=25", "max_order_size=2.5", "live_enabled=false"]
    )

    assert overrides == {
        "paper_latency_ms": 25,
        "max_order_size": Decimal("2.5"),
        "live_enabled": False,
    }


@pytest.mark.parametrize(
    "value",
    ["unknown=value", "name=not-allowed", "malformed", "live_enabled=maybe"],
)
def test_parse_overrides_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_overrides([value])


def test_dashboard_defaults_to_enabled(monkeypatch) -> None:
    class Output:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("polybot.cli.entrypoint.sys.stdout", Output())
    monkeypatch.setenv(TERM_ENV_KEY, "xterm-256color")

    assert _dashboard_enabled(True) is True
    assert _dashboard_enabled(False) is False


def test_dashboard_rejects_explicit_non_tty_output(monkeypatch) -> None:
    class Output:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("polybot.cli.entrypoint.sys.stdout", Output())

    with pytest.raises(ValueError, match=INTERACTIVE_TERMINAL_REQUIRED_MESSAGE):
        _dashboard_enabled(True)


def test_main_treats_keyboard_interrupt_as_graceful_shutdown(monkeypatch) -> None:
    monkeypatch.setattr("polybot.cli.entrypoint.load_dotenv", lambda path: None)
    monkeypatch.setattr("polybot.cli.entrypoint.load_bot", lambda target, config: BaseBot())
    monkeypatch.setattr("polybot.cli.entrypoint._dashboard_enabled", lambda value: False)

    def raise_keyboard_interrupt(awaitable) -> None:
        awaitable.close()
        raise KeyboardInterrupt

    monkeypatch.setattr("polybot.cli.entrypoint.asyncio.run", raise_keyboard_interrupt)

    assert main(["--bot", "polybot.my_bot:create", "--no-dashboard"]) == 0


def test_merge_streams_preserves_typed_stream_kind() -> None:
    async def source(values) -> AsyncIterator[object]:
        for value in values:
            yield value

    first = _book("token", 1)
    newest = _book("token", 2)
    wallet = _wallet("wallet-1")

    async def run() -> list[tuple[StreamKind, object]]:
        return [
            (item.kind, item.event)
            async for item in merge_streams(
                (
                    (StreamKind.BOOK, source((first, newest))),
                    (StreamKind.WALLET, source((wallet,))),
                )
            )
        ]

    assert asyncio.run(run()) == [
        (StreamKind.BOOK, newest),
        (StreamKind.WALLET, wallet),
    ]


def test_rejected_books_do_not_mark_followed_wallet_baselines() -> None:
    class Runner:
        def __init__(self, outcome: DispatchOutcome) -> None:
            self.outcome = outcome

        async def dispatch_book(self, event) -> DispatchOutcome:
            return self.outcome

    class FollowedWallets:
        def __init__(self) -> None:
            self.calls = []

        def mark_baseline(self, token_id, price) -> None:
            self.calls.append((token_id, price))

    async def run(outcome: DispatchOutcome, followed_wallets: FollowedWallets):
        await dispatch_stream_event(
            Runner(outcome),
            BookStreamEvent(StreamKind.BOOK, _book("token", 1)),
            object(),
            gamma=object(),
            clob=object(),
            followed_wallets=followed_wallets,
        )

    rejected = FollowedWallets()
    asyncio.run(run(DispatchOutcome.skipped(DispatchSkipReason.BOOK_STALE), rejected))
    assert rejected.calls == []

    accepted = FollowedWallets()
    asyncio.run(run(DispatchOutcome.accepted_event(), accepted))
    assert accepted.calls == [("token", Decimal("0.4"))]


def test_wallet_trade_identity_is_validated_before_bot_or_follow_state() -> None:
    class Runner:
        def __init__(self) -> None:
            self.calls = 0

        async def dispatch_wallet_trade(self, event) -> DispatchOutcome:
            self.calls += 1
            return DispatchOutcome.accepted_event()

    class Gamma:
        async def find_by_slug(self, slug: str):
            return _market(slug)

    class Clob:
        def has_market_slug(self, slug: str) -> bool:
            return False

        def add_market(self, market) -> None:
            return None

    class FollowedWallets:
        def __init__(self) -> None:
            self.calls = []

        def record_trade(self, event) -> None:
            self.calls.append(event)

    async def run() -> tuple[DispatchOutcome, DispatchOutcome, int, int]:
        runner = Runner()
        followed = FollowedWallets()
        matching = replace(
            _wallet("matching"),
            condition_id="condition-market",
            token_id="yes-market",
            market_slug="market",
        )
        mismatched = replace(matching, token_id="wrong-token")
        matching_outcome = await dispatch_stream_event(
            runner,
            WalletStreamEvent(StreamKind.WALLET, matching),
            object(),
            gamma=Gamma(),
            clob=Clob(),
            followed_wallets=followed,
        )
        mismatched_outcome = await dispatch_stream_event(
            runner,
            WalletStreamEvent(StreamKind.WALLET, mismatched),
            object(),
            gamma=Gamma(),
            clob=Clob(),
            followed_wallets=followed,
        )
        return matching_outcome, mismatched_outcome, runner.calls, len(followed.calls)

    matching_outcome, mismatched_outcome, runner_calls, recorded_count = asyncio.run(run())

    assert matching_outcome is not None and matching_outcome.accepted
    assert mismatched_outcome is not None
    assert mismatched_outcome.skip_reason is DispatchSkipReason.MARKET_METADATA_MISSING
    assert runner_calls == 1
    assert recorded_count == 1


def test_run_blocking_propagates_worker_exception() -> None:
    def fail() -> None:
        raise RuntimeError("worker failed")

    async def run() -> None:
        await run_blocking(fail)

    with pytest.raises(RuntimeError, match="worker failed"):
        asyncio.run(run())


def test_stream_telemetry_tracks_current_and_peak_queue_depth() -> None:
    telemetry = StreamTelemetry()
    telemetry.enqueued()
    telemetry.enqueued()
    telemetry.dequeued()
    telemetry.dequeued()
    telemetry.dequeued()

    assert telemetry.queue_depth == 0
    assert telemetry.peak_queue_depth == 2
    assert telemetry.book_drop_ratio == 0.0


def test_merge_streams_coalesces_books_independently_by_token() -> None:
    telemetry = StreamTelemetry()

    async def source() -> AsyncIterator[BookSnapshot]:
        yield _book("one", 1)
        yield _book("two", 2)
        yield _book("one", 3)
        yield _book("two", 4)

    async def run() -> list[BookSnapshot]:
        return [
            item.event
            async for item in merge_streams(
                ((StreamKind.BOOK, source()),), telemetry=telemetry
            )
        ]

    assert asyncio.run(run()) == [_book("one", 3), _book("two", 4)]
    assert telemetry.book_received_count == 4
    assert telemetry.book_dropped_count == 2
    assert telemetry.book_drop_ratio == 0.5
    assert telemetry.peak_queue_depth == 2
    assert telemetry.queue_depth == 0


def test_merge_streams_preserves_wallet_trades_and_coalesces_hints() -> None:
    first_wallet = _wallet("wallet-1")
    second_wallet = _wallet("wallet-2")
    old_book = _book("token-a", 1)
    new_book = _book("token-a", 2)
    old_hint = MarketTradeHint("condition-a", "token-a", "market", 1)
    new_hint = MarketTradeHint("condition-a", "token-a", "market", 2)
    other_hint = MarketTradeHint("condition-b", "token-b", "market", 3)

    async def source(values) -> AsyncIterator[object]:
        for value in values:
            yield value

    async def run():
        return [
            item
            async for item in merge_streams(
                (
                    (
                        StreamKind.BOOK,
                        source(
                            (
                                old_book,
                                old_hint,
                                new_book,
                                new_hint,
                                other_hint,
                            )
                        ),
                    ),
                    (StreamKind.WALLET, source((first_wallet, second_wallet))),
                )
            )
        ]

    events = asyncio.run(run())
    assert [(item.kind, item.event) for item in events] == [
        (StreamKind.BOOK, new_book),
        (StreamKind.MARKET_HINT, new_hint),
        (StreamKind.MARKET_HINT, other_hint),
        (StreamKind.WALLET, first_wallet),
        (StreamKind.WALLET, second_wallet),
    ]


def test_merge_streams_keeps_lifetime_counters_across_generations() -> None:
    telemetry = StreamTelemetry()

    async def source(token_id: str) -> AsyncIterator[BookSnapshot]:
        yield _book(token_id, 1)
        yield _book(token_id, 2)

    async def consume(token_id: str) -> None:
        async for _ in merge_streams(
            ((StreamKind.BOOK, source(token_id)),), telemetry=telemetry
        ):
            pass

    async def run() -> None:
        await consume("first")
        await consume("second")

    asyncio.run(run())
    assert telemetry.book_received_count == 4
    assert telemetry.book_dropped_count == 2
    assert telemetry.peak_queue_depth == 1
    assert telemetry.queue_depth == 0


def test_slow_book_consumer_receives_latest_snapshot_without_stale_cascade() -> None:
    entered_handler = asyncio.Event()
    producer_finished = asyncio.Event()
    release_handler = asyncio.Event()
    now_ms = 0
    telemetry = StreamTelemetry()

    class SlowBot(BaseBot):
        def __init__(self) -> None:
            self.received_at_ms: list[int] = []

        async def on_book(self, ctx, book) -> None:
            self.received_at_ms.append(book.received_at_ms)
            if len(self.received_at_ms) == 1:
                entered_handler.set()
                await release_handler.wait()

    async def source() -> AsyncIterator[BookSnapshot]:
        yield _book("token", 0)
        await entered_handler.wait()
        yield _book("token", 1_000)
        yield _book("token", 2_000)
        yield _book("token", 7_000)
        producer_finished.set()

    async def run() -> tuple[list[bool], list[int]]:
        nonlocal now_ms
        bot = SlowBot()
        ctx = BotContext(
            config=BotConfig(name="slow", event_max_age_ms=5_000),
            broker=SimpleNamespace(),
            markets=SimpleNamespace(),
            books=SimpleNamespace(),
            wallet_activity=SimpleNamespace(),
        )
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: now_ms)

        async def release() -> None:
            nonlocal now_ms
            await producer_finished.wait()
            now_ms = 7_000
            release_handler.set()

        release_task = asyncio.create_task(release())
        outcomes = []
        async for item in merge_streams(
            ((StreamKind.BOOK, source()),), telemetry=telemetry
        ):
            outcomes.append(await runner.dispatch_book(item.event))
        await release_task
        return [outcome.accepted for outcome in outcomes], bot.received_at_ms

    accepted, received_at_ms = asyncio.run(run())
    assert accepted == [True, True]
    assert received_at_ms == [0, 7_000]
    assert telemetry.book_received_count == 4
    assert telemetry.book_dropped_count == 2


def test_merge_streams_routes_market_trade_hints_separately() -> None:
    async def source() -> AsyncIterator[object]:
        yield MarketTradeHint("condition", "token", "market", 123)

    async def run() -> list[tuple[StreamKind, object]]:
        return [
            (item.kind, item.event)
            async for item in merge_streams(((StreamKind.BOOK, source()),))
        ]

    assert asyncio.run(run()) == [
        (
            StreamKind.MARKET_HINT,
            MarketTradeHint("condition", "token", "market", 123),
        )
    ]


def test_merge_streams_consumes_resolution_only_source_until_completion() -> None:
    event = _resolution_event()

    async def source() -> AsyncIterator[object]:
        yield event

    async def run():
        return [
            item
            async for item in merge_streams(((StreamKind.RESOLUTION, source()),))
        ]

    items = asyncio.run(run())
    assert items == [ResolutionStreamEvent(StreamKind.RESOLUTION, event)]


def test_merge_streams_propagates_failure_and_cancels_sibling() -> None:
    cancelled = False

    async def failing() -> AsyncIterator[int]:
        raise RuntimeError("source failed")
        yield 0

    async def waiting() -> AsyncIterator[int]:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
            yield 0
        finally:
            cancelled = True

    async def run() -> None:
        with pytest.raises(RuntimeError, match="source failed"):
            async for _ in merge_streams(
                (
                    (StreamKind.BOOK, failing()),
                    (StreamKind.WALLET, waiting()),
                )
            ):
                pass

    asyncio.run(run())
    assert cancelled is True


def test_resolve_plan_markets_requires_current_and_tolerates_next() -> None:
    class FakeGamma:
        async def find_many(self, slugs: tuple[str, ...]) -> tuple[Market | None, ...]:
            return tuple(_market(slug) if slug == "current" else None for slug in slugs)

    async def run():
        return await resolve_plan_markets(
            MarketPlan(
                current=(MarketSubscription("current"),),
                next=(MarketSubscription("future"),),
            ),
            FakeGamma(),  # type: ignore[arg-type]
        )

    resolved = asyncio.run(run())
    assert tuple(market.slug for market in resolved.current) == ("current",)
    assert resolved.next == ()


def test_resolve_plan_markets_rejects_missing_current() -> None:
    class FakeGamma:
        async def find_many(self, slugs: tuple[str, ...]) -> tuple[None, ...]:
            return tuple(None for _ in slugs)

    async def run():
        await resolve_plan_markets(
            MarketPlan(current=(MarketSubscription("missing"),)),
            FakeGamma(),  # type: ignore[arg-type]
        )

    with pytest.raises(RuntimeError, match="configured markets could not be resolved"):
        asyncio.run(run())


def test_config_rejects_non_finite_decimals() -> None:
    with pytest.raises(ValueError, match="finite"):
        BotConfig(name="test", max_order_size=Decimal("Infinity"))


def test_load_bot_supports_config_and_zero_argument_factories(monkeypatch) -> None:
    class ConfigBot(BaseBot):
        def __init__(self, config: BotConfig) -> None:
            self.config = config

    class EmptyBot(BaseBot):
        pass

    module = SimpleNamespace(
        with_config=lambda config: ConfigBot(config),
        without_config=lambda: EmptyBot(),
    )
    monkeypatch.setitem(__import__("sys").modules, "test_cli_factories", module)
    config = BotConfig(name="factory")

    assert isinstance(load_bot("test_cli_factories:without_config", config), EmptyBot)
    loaded = load_bot("test_cli_factories:with_config", config)
    assert isinstance(loaded, ConfigBot)
    assert loaded.config is config


def test_load_bot_rejects_invalid_factory() -> None:
    with pytest.raises(ValueError, match="invalid bot factory"):
        load_bot("missing_module:bot", BotConfig(name="factory"))


def test_run_bot_runs_lifecycle_and_closes_owned_client(monkeypatch) -> None:
    class FakeClient:
        closed = False

        async def close(self) -> None:
            self.closed = True

    class FakeGamma:
        def __init__(self, client) -> None:
            self.client = client

        async def find_many(self, slugs):
            return tuple(_market(slug) for slug in slugs)

    class FakeAdapter:
        def __init__(self, client) -> None:
            self.client = client
            self.markets = ()

        def set_markets(self, markets) -> None:
            self.markets = tuple(markets)

        async def books(self, token_ids):
            yield _book("token", 0)

    class FakeBotRunner:
        def __init__(self, bot, ctx) -> None:
            self.bot = bot
            self.market_plan = MarketPlan(current=())
            self.wallet_plan = SimpleNamespace(active_addresses=frozenset())
            self.dispatched = 0

        def set_runtime_market_slugs(self, market_slugs) -> None:
            self.market_slugs = market_slugs

        async def refresh_markets(self):
            self.market_plan = MarketPlan(
                current=(MarketSubscription("current"),)
            )

        async def refresh_wallets(self):
            return self.wallet_plan

        async def dispatch_book(self, event) -> DispatchOutcome:
            self.dispatched += 1
            return DispatchOutcome.accepted_event()

    class LifecycleBot(BaseBot):
        started = 0
        stopped = 0

        async def on_start(self, ctx) -> None:
            self.started += 1

        async def on_stop(self, ctx) -> None:
            self.stopped += 1

    class FakeBroker:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class RecordingObserver(RuntimeObserver):
        def __init__(self) -> None:
            self.events = []

        async def start(self, config) -> None:
            return None

        def emit(self, event) -> None:
            self.events.append(event)

        async def stop(self) -> None:
            return None

    monkeypatch.setattr("polybot.cli.runner.factory.GammaClient", FakeGamma)
    monkeypatch.setattr("polybot.cli.runner.factory.ClobClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.MarketStream", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.WalletActivityClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.PaperBroker", FakeBroker)
    monkeypatch.setattr("polybot.cli.runner.service.BotRunner", FakeBotRunner)

    async def run() -> tuple[int, int, bool, RecordingObserver]:
        client = FakeClient()
        monkeypatch.setattr("polybot.cli.runner.factory.AsyncPublicClient", lambda: client)
        bot = LifecycleBot()
        observer = RecordingObserver()
        await run_bot(
            bot,
            BotConfig(name="runner", market_slugs=("current",)),
            observer=observer,
        )
        return bot.started, bot.stopped, client.closed, observer

    started, stopped, closed, observer = asyncio.run(run())
    assert (started, stopped, closed) == (1, 1, True)
    assert [
        (event.phase, event.completed, event.total)
        for event in observer.events
        if isinstance(event, BootstrapProgress)
    ] == [
        (BootstrapPhase.MARKETS, 0, 0),
        (BootstrapPhase.MARKETS, 0, 1),
        (BootstrapPhase.MARKETS, 1, 1),
        (BootstrapPhase.WALLETS, 0, 0),
    ]


def test_run_bot_rejects_live_before_opening_client() -> None:
    async def run() -> None:
        await run_bot(BaseBot(), BotConfig(name="live", mode=BotMode.LIVE))

    with pytest.raises(RuntimeError, match="live mode"):
        asyncio.run(run())


def test_stream_plan_change_waiter_detects_dynamic_market_rollover(monkeypatch) -> None:
    initial = StreamPlan(
        current=(StreamRule(StreamRelation.INDEPENDENT, ("bucket-0",)),),
    )
    rolled = StreamPlan(
        current=(StreamRule(StreamRelation.INDEPENDENT, ("bucket-300",)),),
    )

    class DynamicRunner:
        def __init__(self) -> None:
            self.calls = 0

        async def refresh_stream_plan(self):
            self.calls += 1
            return initial if self.calls == 1 else rolled

    async def run() -> StreamPlan:
        return await wait_for_stream_plan_change(DynamicRunner(), initial)

    monkeypatch.setattr("polybot.cli.runner.streams.STREAM_PLAN_REFRESH_INTERVAL_SECONDS", 0)
    assert asyncio.run(run()) == rolled


def test_run_bot_rebuilds_union_stream_and_retains_unresolved_rollover_market(monkeypatch) -> None:
    initial = StreamPlan(
        current=(StreamRule(StreamRelation.INDEPENDENT, ("bucket-0",)),),
    )
    rolled = StreamPlan(
        current=(StreamRule(StreamRelation.INDEPENDENT, ("bucket-300",)),),
    )

    class FakeGamma:
        def __init__(self, client) -> None:
            pass

        async def find_many(self, slugs):
            return tuple(_market(slug) for slug in slugs)

    class FakeAdapter:
        market_sets: list[tuple[str, ...]] = []

        def __init__(self, client) -> None:
            pass

        def set_markets(self, markets) -> None:
            self.market_sets.append(tuple(market.slug for market in markets))

        async def events(self, token_ids):
            if "yes-bucket-0" in token_ids and "yes-bucket-300" not in token_ids:
                await asyncio.Event().wait()
            yield _book("token", 0)

    class DynamicRunner:
        def __init__(self, bot, ctx) -> None:
            self.calls = 0
            self.dispatched = 0

        def set_runtime_market_slugs(self, market_slugs) -> None:
            self.market_slugs = market_slugs

        async def refresh_stream_plan(self):
            self.calls += 1
            return initial if self.calls < 3 else rolled

        async def dispatch_book(self, event) -> DispatchOutcome:
            self.dispatched += 1
            return DispatchOutcome.accepted_event()

    class FakeBroker:
        def __init__(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr("polybot.cli.runner.factory.GammaClient", FakeGamma)
    monkeypatch.setattr("polybot.cli.runner.factory.ClobClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.MarketStream", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.WalletActivityClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.PaperBroker", FakeBroker)
    monkeypatch.setattr("polybot.cli.runner.service.BotRunner", DynamicRunner)
    monkeypatch.setattr("polybot.cli.runner.streams.STREAM_PLAN_REFRESH_INTERVAL_SECONDS", 0)

    asyncio.run(run_bot(BaseBot(), BotConfig(name="dynamic"), client=object()))

    assert FakeAdapter.market_sets == [
        ("bucket-0",),
        ("bucket-0",),
        ("bucket-0", "bucket-300"),
        ("bucket-0", "bucket-300"),
    ]


def test_resolution_closes_old_stream_and_rebuilds_without_resolved_tokens(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = StreamPlan(
        current=(StreamRule(StreamRelation.INDEPENDENT, ("first", "second")),),
    )
    markets = {slug: _market(slug) for slug in ("first", "second")}

    class FakeGamma:
        def __init__(self, client) -> None:
            pass

        async def find_many(self, slugs):
            return tuple(markets[slug] for slug in slugs)

    class FakeClob:
        def __init__(self, client) -> None:
            self.market_sets: list[tuple[str, ...]] = []

        def set_markets(self, candidates) -> None:
            self.market_sets.append(tuple(market.slug for market in candidates))

    class FakeMarketStream:
        token_sets: list[frozenset[str]] = []
        closed_token_sets: list[frozenset[str]] = []

        def __init__(self, client) -> None:
            pass

        def set_markets(self, candidates) -> None:
            return None

        async def events(self, token_ids):
            subscribed = frozenset(token_ids)
            self.token_sets.append(subscribed)
            try:
                if len(self.token_sets) == 1:
                    yield MarketResolutionEvent(
                        condition_id=markets["first"].condition_id,
                        market_slug="first",
                        token_ids=("yes-first", "no-first"),
                        winning_token_id="yes-first",
                        winning_outcome=YES_OUTCOME,
                        resolved_at_ms=1,
                        source="test",
                    )
                    yield replace(
                        _book("yes-first", 1),
                        condition_id=markets["first"].condition_id,
                        market_slug="first",
                    )
                    await asyncio.Event().wait()
                else:
                    yield replace(
                        _book("yes-second", 2),
                        condition_id=markets["second"].condition_id,
                        market_slug="second",
                    )
            finally:
                self.closed_token_sets.append(subscribed)

    class FakeWalletClient:
        def __init__(self, client) -> None:
            pass

    class FakePaperBroker:
        def __init__(self, *args, **kwargs) -> None:
            self.portfolio = PaperPortfolio(Decimal("100"))
            self.position_market_refs = {}

        def settle_market(self, event):
            return self.portfolio.settle_market(event)

    class FakeRunner:
        books: list[str] = []
        resolutions: list[str] = []

        def __init__(self, bot, ctx) -> None:
            pass

        def set_runtime_market_slugs(self, market_slugs) -> None:
            return None

        async def refresh_stream_plan(self):
            return plan

        async def dispatch_book(self, event) -> DispatchOutcome:
            self.books.append(event.token_id)
            return DispatchOutcome.accepted_event()

        async def dispatch_market_resolution(self, event) -> None:
            self.resolutions.append(event.condition_id)

    monkeypatch.setattr("polybot.cli.runner.factory.GammaClient", FakeGamma)
    monkeypatch.setattr("polybot.cli.runner.factory.ClobClient", FakeClob)
    monkeypatch.setattr("polybot.cli.runner.factory.MarketStream", FakeMarketStream)
    monkeypatch.setattr(
        "polybot.cli.runner.factory.WalletActivityClient", FakeWalletClient
    )
    monkeypatch.setattr("polybot.cli.runner.factory.PaperBroker", FakePaperBroker)
    monkeypatch.setattr("polybot.cli.runner.service.BotRunner", FakeRunner)

    class RecordingObserver:
        def __init__(self) -> None:
            self.events = []

        async def start(self, config: BotConfig) -> None:
            return None

        def emit(self, event) -> None:
            self.events.append(event)

        async def stop(self) -> None:
            return None

    observer = RecordingObserver()
    asyncio.run(
        run_bot(
            BaseBot(),
            BotConfig(name="resolution-rebuild"),
            client=object(),
            observer=observer,
        )
    )

    first_tokens = frozenset(("yes-first", "no-first", "yes-second", "no-second"))
    assert FakeMarketStream.token_sets == [
        first_tokens,
        frozenset(("yes-second", "no-second")),
    ]
    assert FakeMarketStream.closed_token_sets == FakeMarketStream.token_sets
    assert FakeRunner.books == ["yes-second"]
    assert FakeRunner.resolutions == [markets["first"].condition_id]
    assert any(isinstance(event, MarketSettled) for event in observer.events)

    dashboard = DashboardState()
    for event in observer.events:
        dashboard.apply(event)
    assert dashboard.resolved_market_count == 1


def test_gamma_resolved_market_is_settled_before_stream_creation(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    market = replace(
        _market("resolved"),
        resolved=True,
        winning_token_id="yes-resolved",
        winning_outcome=YES_OUTCOME,
    )
    plan = StreamPlan(
        current=(StreamRule(StreamRelation.INDEPENDENT, (market.slug,)),),
    )

    class FakeGamma:
        def __init__(self, client) -> None:
            pass

        async def find_many(self, slugs):
            return tuple(market for _ in slugs)

    class FakeClob:
        def __init__(self, client) -> None:
            pass

        def set_markets(self, candidates) -> None:
            assert tuple(candidates) == ()

    class FakeMarketStream:
        opened = False

        def __init__(self, client) -> None:
            pass

        def set_markets(self, candidates) -> None:
            return None

        async def events(self, token_ids):
            type(self).opened = True
            raise AssertionError("resolved Gamma market must not open a stream")
            yield  # pragma: no cover

    class FakeWalletClient:
        def __init__(self, client) -> None:
            pass

    class FakePaperBroker:
        def __init__(self, *args, **kwargs) -> None:
            self.portfolio = PaperPortfolio(Decimal("100"))
            self.position_market_refs = {}

        def settle_market(self, event):
            return self.portfolio.settle_market(event)

    class FakeRunner:
        settled: list[str] = []

        def __init__(self, bot, ctx) -> None:
            pass

        def set_runtime_market_slugs(self, market_slugs) -> None:
            assert market_slugs == frozenset()

        async def refresh_stream_plan(self):
            return plan

        async def dispatch_market_resolution(self, event) -> None:
            self.settled.append(event.condition_id)

    monkeypatch.setattr("polybot.cli.runner.factory.GammaClient", FakeGamma)
    monkeypatch.setattr("polybot.cli.runner.factory.ClobClient", FakeClob)
    monkeypatch.setattr("polybot.cli.runner.factory.MarketStream", FakeMarketStream)
    monkeypatch.setattr(
        "polybot.cli.runner.factory.WalletActivityClient", FakeWalletClient
    )
    monkeypatch.setattr("polybot.cli.runner.factory.PaperBroker", FakePaperBroker)
    monkeypatch.setattr("polybot.cli.runner.service.BotRunner", FakeRunner)

    asyncio.run(run_bot(BaseBot(), BotConfig(name="gamma-resolved"), client=object()))

    assert not FakeMarketStream.opened
    assert FakeRunner.settled == [market.condition_id]


def test_run_bot_reports_failed_shutdown_and_stops_observer(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class FakeGamma:
        def __init__(self, client) -> None:
            self.client = client

        async def find_many(self, slugs):
            return tuple(_market(slug) for slug in slugs)

    class FakeAdapter:
        def __init__(self, client) -> None:
            self.client = client

        def set_markets(self, markets) -> None:
            return None

        async def books(self, token_ids):
            yield object()

    class FakeBotRunner:
        def __init__(self, bot, ctx) -> None:
            self.market_plan = MarketPlan(current=(MarketSubscription("current"),))
            self.wallet_plan = SimpleNamespace(active_addresses=frozenset())

        def set_runtime_market_slugs(self, market_slugs) -> None:
            self.market_slugs = market_slugs

        async def refresh_markets(self) -> None:
            return None

        async def refresh_wallets(self) -> None:
            return None

        async def dispatch_book(self, event) -> DispatchOutcome:
            return DispatchOutcome.accepted_event()

    class FakeBroker:
        def __init__(self, *args, **kwargs) -> None:
            return None

    class FailingStopBot(BaseBot):
        async def on_stop(self, ctx) -> None:
            raise RuntimeError("stop failed")

    class RecordingObserver(RuntimeObserver):
        def __init__(self) -> None:
            self.events = []
            self.stopped = False

        async def start(self, config) -> None:
            return None

        def emit(self, event) -> None:
            self.events.append(event)

        async def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr("polybot.cli.runner.factory.GammaClient", FakeGamma)
    monkeypatch.setattr("polybot.cli.runner.factory.ClobClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.MarketStream", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.WalletActivityClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.factory.PaperBroker", FakeBroker)
    monkeypatch.setattr("polybot.cli.runner.service.BotRunner", FakeBotRunner)

    async def run() -> tuple[FakeClient, RecordingObserver]:
        client = FakeClient()
        monkeypatch.setattr("polybot.cli.runner.factory.AsyncPublicClient", lambda: client)
        observer = RecordingObserver()
        with pytest.raises(RuntimeError, match="stop failed"):
            await run_bot(
                FailingStopBot(),
                BotConfig(name="shutdown", market_slugs=("current",)),
                observer=observer,
            )
        return client, observer

    client, observer = asyncio.run(run())
    assert client.closed
    assert observer.stopped
    assert any(isinstance(event, RuntimeFailed) for event in observer.events)
    assert not any(
        isinstance(event, RuntimeStateChanged) and event.state is RuntimeState.STOPPED
        for event in observer.events
    )


def _market(slug: str) -> Market:
    return Market(
        condition_id=f"condition-{slug}",
        slug=slug,
        question=slug,
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0"),
        outcomes=(
            MarketOutcome(YES_OUTCOME, f"yes-{slug}"),
            MarketOutcome("No", f"no-{slug}"),
        ),
    )


def _book(token_id: str, received_at_ms: int) -> BookSnapshot:
    return BookSnapshot(
        token_id=token_id,
        bids=(BookLevel(Decimal("0.4"), Decimal("1")),),
        asks=(BookLevel(Decimal("0.6"), Decimal("1")),),
        received_at_ms=received_at_ms,
        market_slug="market",
        condition_id="condition",
    )


def _resolution_event() -> MarketResolutionEvent:
    return MarketResolutionEvent(
        condition_id="condition",
        market_slug="market",
        token_ids=("token", "no-token"),
        winning_token_id="token",
        winning_outcome=YES_OUTCOME,
        resolved_at_ms=1_000,
        source="test",
    )


def _wallet(source_id: str) -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet="0x0000000000000000000000000000000000000001",
        condition_id="condition",
        token_id="token",
        side=Side.BUY,
        size=Decimal("1"),
        price=Decimal("0.5"),
        source_id=source_id,
        trade_timestamp_ms=1,
        observed_at_ms=1,
    )
