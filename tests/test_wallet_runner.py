import asyncio
from dataclasses import dataclass
from decimal import Decimal

from bots.framework.base import BaseBot
from bots.framework.config import BotConfig
from bots.framework.context import BotContext
from bots.framework.events import Side, WalletTradeEvent
from bots.framework.runner import BotRunner


@dataclass(slots=True)
class RecordingBot(BaseBot):
    seen: list[str]
    started: int = 0
    stopped: int = 0

    async def on_start(self, ctx: BotContext) -> None:
        self.started += 1

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        self.seen.append(trade.source_id)

    async def on_stop(self, ctx: BotContext) -> None:
        self.stopped += 1


def test_runner_dispatches_wallet_trade_once(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, bool, list[str]]:
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, dummy_context)
        trade = _wallet_trade("tx-1")

        first = await runner.dispatch_wallet_trade(trade)
        duplicate = await runner.dispatch_wallet_trade(trade)

        return first, duplicate, bot.seen

    first, duplicate, seen = asyncio.run(run())

    assert first is True
    assert duplicate is False
    assert seen == ["tx-1"]


def test_runner_rejects_wallet_trade_without_source_id(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, int]:
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, dummy_context)
        trade = _wallet_trade("")

        accepted = await runner.dispatch_wallet_trade(trade)
        return accepted, len(bot.seen)

    accepted, seen_count = asyncio.run(run())

    assert accepted is False
    assert seen_count == 0


def test_runner_routes_trades_from_multiple_configured_wallets(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[bool, bool, bool, list[str]]:
        ctx = _with_config(
            dummy_context,
            BotConfig(
                name="multi-wallet",
                wallet_addresses=("0xLeaderOne", "0xLeaderTwo"),
            ),
        )
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, ctx)

        first = await runner.dispatch_wallet_trade(
            _wallet_trade("tx-1", wallet="0xleaderone")
        )
        second = await runner.dispatch_wallet_trade(
            _wallet_trade("tx-2", wallet="0xLEADERTWO")
        )
        unrelated = await runner.dispatch_wallet_trade(
            _wallet_trade("tx-3", wallet="0xother")
        )
        return first, second, unrelated, bot.seen

    first, second, unrelated, seen = asyncio.run(run())

    assert first is True
    assert second is True
    assert unrelated is False
    assert seen == ["tx-1", "tx-2"]


def test_default_wallet_plan_normalizes_and_deduplicates_addresses(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[str, ...]:
        ctx = _with_config(
            dummy_context,
            BotConfig(
                name="multi-wallet",
                wallet_addresses=("0xLeader", "0xleader", "0xSecond"),
            ),
        )
        bot = RecordingBot(seen=[])

        subscriptions = await bot.current_wallets(ctx, 0)
        return tuple(subscription.address for subscription in subscriptions)

    assert asyncio.run(run()) == ("0xleader", "0xsecond")


def test_dedupe_scopes_source_ids_to_each_wallet(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, bool, list[str]]:
        ctx = _with_config(
            dummy_context,
            BotConfig(
                name="multi-wallet",
                wallet_addresses=("0xfirst", "0xsecond"),
            ),
        )
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, ctx)

        first = await runner.dispatch_wallet_trade(
            _wallet_trade("shared-source", wallet="0xfirst")
        )
        second = await runner.dispatch_wallet_trade(
            _wallet_trade("shared-source", wallet="0xsecond")
        )
        return first, second, bot.seen

    first, second, seen = asyncio.run(run())

    assert first is True
    assert second is True
    assert seen == ["shared-source", "shared-source"]


def test_runner_calls_start_and_stop_for_wallet_stream(dummy_context: BotContext) -> None:
    async def run() -> tuple[int, int]:
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, dummy_context)

        async def trades():
            yield _wallet_trade("tx-1")

        await runner.run_wallet_trades(trades())
        return bot.started, bot.stopped

    started, stopped = asyncio.run(run())

    assert started == 1
    assert stopped == 1


def _wallet_trade(
    source_id: str,
    wallet: str = "0xleader",
) -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet=wallet,
        condition_id="0xcondition",
        token_id="123",
        side=Side.BUY,
        size=Decimal("5"),
        price=Decimal("0.42"),
        source_id=source_id,
        trade_timestamp_ms=1_000,
        observed_at_ms=1_250,
        transaction_hash="0xtx",
    )


def _with_config(ctx: BotContext, config: BotConfig) -> BotContext:
    return BotContext(
        config=config,
        broker=ctx.broker,
        markets=ctx.markets,
        books=ctx.books,
        wallet_activity=ctx.wallet_activity,
        positions=ctx.positions,
    )
