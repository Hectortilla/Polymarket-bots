import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace

import pytest

from polybot.cli.config import load_dotenv, parse_overrides
from polybot.cli.entrypoint import (
    INTERACTIVE_TERMINAL_REQUIRED_MESSAGE,
    _dashboard_enabled,
    main,
)
from polybot.cli.factories import load_bot
from polybot.cli.markets import resolve_plan_markets
from polybot.cli.runner import _wait_for_stream_plan_change, run_bot
from polybot.cli.streams import StreamKind, StreamTelemetry, merge_streams
from polybot.cli.observability.events import RuntimeFailed, RuntimeState, RuntimeStateChanged
from polybot.cli.observability.observer import RuntimeObserver
from polybot.framework.base import BaseBot
from polybot.framework.config import BotConfig, BotMode
from polybot.framework.markets import MarketPlan, MarketSubscription
from polybot.polymarket.types import Market
from polybot.polymarket.types import MarketTradeHint


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
    monkeypatch.setenv("TERM", "xterm-256color")

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
    async def source(values: tuple[int, ...]) -> AsyncIterator[int]:
        for value in values:
            yield value

    async def run() -> list[tuple[StreamKind, int]]:
        return [
            (item.kind, item.event)
            async for item in merge_streams(
                (
                    (StreamKind.BOOK, source((1, 2))),
                    (StreamKind.WALLET, source((3,))),
                )
            )
        ]

    assert sorted(asyncio.run(run())) == [
        (StreamKind.BOOK, 1),
        (StreamKind.BOOK, 2),
        (StreamKind.WALLET, 3),
    ]


def test_stream_telemetry_tracks_current_and_peak_queue_depth() -> None:
    telemetry = StreamTelemetry()
    telemetry.enqueued()
    telemetry.enqueued()
    telemetry.dequeued()
    telemetry.dequeued()
    telemetry.dequeued()

    assert telemetry.queue_depth == 0
    assert telemetry.peak_queue_depth == 2


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
            yield object()

    class FakeBotRunner:
        def __init__(self, bot, ctx) -> None:
            self.bot = bot
            self.market_plan = MarketPlan(current=())
            self.wallet_plan = SimpleNamespace(active_addresses=frozenset())
            self.dispatched = 0

        async def refresh_markets(self):
            self.market_plan = MarketPlan(
                current=(MarketSubscription("current"),)
            )

        async def refresh_wallets(self):
            return self.wallet_plan

        async def dispatch_book(self, event) -> None:
            self.dispatched += 1

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

    monkeypatch.setattr("polybot.cli.runner.GammaClient", FakeGamma)
    monkeypatch.setattr("polybot.cli.runner.ClobClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.MarketStream", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.WalletActivityClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.PaperBroker", FakeBroker)
    monkeypatch.setattr("polybot.cli.runner.BotRunner", FakeBotRunner)

    async def run() -> tuple[int, int, bool]:
        client = FakeClient()
        monkeypatch.setattr("polybot.cli.runner.AsyncPublicClient", lambda: client)
        bot = LifecycleBot()
        await run_bot(bot, BotConfig(name="runner", market_slugs=("current",)))
        return bot.started, bot.stopped, client.closed

    assert asyncio.run(run()) == (1, 1, True)


def test_run_bot_rejects_live_before_opening_client() -> None:
    async def run() -> None:
        await run_bot(BaseBot(), BotConfig(name="live", mode=BotMode.LIVE))

    with pytest.raises(RuntimeError, match="live mode"):
        asyncio.run(run())


def test_stream_plan_change_waiter_detects_dynamic_market_rollover(monkeypatch) -> None:
    from polybot.framework.streams import StreamPlan, StreamRelation, StreamRule

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
        return await _wait_for_stream_plan_change(DynamicRunner(), initial)

    monkeypatch.setattr("polybot.cli.runner.STREAM_PLAN_REFRESH_INTERVAL_SECONDS", 0)
    assert asyncio.run(run()) == rolled


def test_run_bot_rebuilds_market_stream_when_dynamic_plan_rolls_over(monkeypatch) -> None:
    from polybot.framework.streams import StreamPlan, StreamRelation, StreamRule

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
            if "yes-bucket-0" in token_ids:
                await asyncio.Event().wait()
            yield object()

    class DynamicRunner:
        def __init__(self, bot, ctx) -> None:
            self.calls = 0
            self.dispatched = 0

        async def refresh_stream_plan(self):
            self.calls += 1
            return initial if self.calls < 3 else rolled

        async def dispatch_book(self, event):
            self.dispatched += 1

    class FakeBroker:
        def __init__(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr("polybot.cli.runner.GammaClient", FakeGamma)
    monkeypatch.setattr("polybot.cli.runner.ClobClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.MarketStream", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.WalletActivityClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.PaperBroker", FakeBroker)
    monkeypatch.setattr("polybot.cli.runner.BotRunner", DynamicRunner)
    monkeypatch.setattr("polybot.cli.runner.STREAM_PLAN_REFRESH_INTERVAL_SECONDS", 0)

    asyncio.run(run_bot(BaseBot(), BotConfig(name="dynamic"), client=object()))

    assert FakeAdapter.market_sets == [
        ("bucket-0",),
        ("bucket-0",),
        ("bucket-300",),
        ("bucket-300",),
    ]


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

        async def refresh_markets(self) -> None:
            return None

        async def refresh_wallets(self) -> None:
            return None

        async def dispatch_book(self, event) -> None:
            return None

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

    monkeypatch.setattr("polybot.cli.runner.GammaClient", FakeGamma)
    monkeypatch.setattr("polybot.cli.runner.ClobClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.MarketStream", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.WalletActivityClient", FakeAdapter)
    monkeypatch.setattr("polybot.cli.runner.PaperBroker", FakeBroker)
    monkeypatch.setattr("polybot.cli.runner.BotRunner", FakeBotRunner)

    async def run() -> tuple[FakeClient, RecordingObserver]:
        client = FakeClient()
        monkeypatch.setattr("polybot.cli.runner.AsyncPublicClient", lambda: client)
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
        yes_token_id=f"yes-{slug}",
        no_token_id=f"no-{slug}",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0"),
    )
