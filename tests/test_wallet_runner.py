import asyncio
from dataclasses import dataclass, replace
from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason
from polybot.framework.events import Side
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.runner import BotRunner
from polybot.framework.streams import StreamRelation, StreamRule


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
        runner = BotRunner(bot, dummy_context, now_ms_fn=lambda: 1_250)
        trade = _wallet_trade("tx-1")

        first = await runner.dispatch_wallet_trade(trade)
        duplicate = await runner.dispatch_wallet_trade(trade)

        return first, duplicate, bot.seen

    first, duplicate, seen = asyncio.run(run())

    assert first.accepted is True
    assert duplicate.skip_reason is DispatchSkipReason.DUPLICATE_SOURCE_EVENT
    assert seen == ["tx-1"]


def test_runner_rejects_wallet_trade_without_source_id(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, int]:
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, dummy_context, now_ms_fn=lambda: 1_250)
        trade = _wallet_trade("")

        accepted = await runner.dispatch_wallet_trade(trade)
        return accepted, len(bot.seen)

    accepted, seen_count = asyncio.run(run())

    assert accepted.skip_reason is DispatchSkipReason.WALLET_TRADE_INVALID
    assert seen_count == 0


def test_runner_rejects_invalid_wallet_trade_before_bot_dispatch(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[DispatchSkipReason | None, int]:
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, dummy_context, now_ms_fn=lambda: 1_250)
        invalid_trade = replace(_wallet_trade("invalid"), size=Decimal("0"))
        outcome = await runner.dispatch_wallet_trade(invalid_trade)
        return outcome.skip_reason, len(bot.seen)

    skip_reason, seen_count = asyncio.run(run())

    assert skip_reason is DispatchSkipReason.WALLET_TRADE_INVALID
    assert seen_count == 0


def test_runner_rejects_future_dated_wallet_trade(dummy_context: BotContext) -> None:
    async def run():
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, dummy_context, now_ms_fn=lambda: 1_000)
        trade = _wallet_trade("future")
        trade = WalletTradeEvent(
            wallet=trade.wallet,
            condition_id=trade.condition_id,
            token_id=trade.token_id,
            side=trade.side,
            size=trade.size,
            price=trade.price,
            source_id=trade.source_id,
            trade_timestamp_ms=2_000,
            observed_at_ms=2_100,
        )
        return await runner.dispatch_wallet_trade(trade)

    outcome = asyncio.run(run())
    assert outcome.skip_reason is DispatchSkipReason.WALLET_TRADE_FUTURE_DATED


def test_runner_rejects_promptly_observed_trade_after_queue_delay(
    dummy_context: BotContext,
) -> None:
    async def run():
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, dummy_context, now_ms_fn=lambda: 10_000)
        return await runner.dispatch_wallet_trade(_wallet_trade("queued"))

    outcome = asyncio.run(run())
    assert outcome.skip_reason is DispatchSkipReason.WALLET_TRADE_STALE


def test_runner_rechecks_wallet_freshness_before_claiming_source_id(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[DispatchOutcome, DispatchOutcome, list[str]]:
        ctx = _with_config(
            dummy_context,
            _bot_config(
                "wallet",
                wallets=("0xleader",),
                event_max_age_ms=1_000,
            ),
        )
        now_values = iter((1_000, 1_000, 2_001, 2_001, 2_001, 2_001))
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: next(now_values))
        stale_after_refresh = replace(
            _wallet_trade("source-id"),
            trade_timestamp_ms=0,
            observed_at_ms=1_000,
        )
        first = await runner.dispatch_wallet_trade(stale_after_refresh)
        second = await runner.dispatch_wallet_trade(
            replace(
                stale_after_refresh,
                trade_timestamp_ms=2_001,
                observed_at_ms=2_001,
            )
        )
        return first, second, bot.seen

    first, second, seen = asyncio.run(run())

    assert first.skip_reason is DispatchSkipReason.WALLET_TRADE_STALE
    assert second.accepted is True
    assert seen == ["source-id"]


def test_runner_routes_trades_from_multiple_configured_wallets(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[bool, bool, bool, list[str]]:
        ctx = _with_config(
            dummy_context,
            _bot_config(
                "multi-wallet",
                wallets=("0xLeaderOne", "0xLeaderTwo"),
            ),
        )
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 1_250)

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

    assert first.accepted is True
    assert second.accepted is True
    assert unrelated.skip_reason is DispatchSkipReason.WALLET_NOT_TRACKED
    assert seen == ["tx-1", "tx-2"]


def test_default_stream_rules_normalize_and_deduplicate_wallet_addresses(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[str, ...]:
        ctx = _with_config(
            dummy_context,
            _bot_config(
                "multi-wallet",
                wallets=("0xLeader", "0xleader", "0xSecond"),
            ),
        )
        bot = RecordingBot(seen=[])

        rules = await bot.current_stream_rules(ctx, 0)
        return rules[0].wallet_addresses

    assert asyncio.run(run()) == ("0xleader", "0xsecond")


def test_dedupe_scopes_source_ids_to_each_wallet(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, bool, list[str]]:
        ctx = _with_config(
            dummy_context,
            _bot_config(
                "multi-wallet",
                wallets=("0xfirst", "0xsecond"),
            ),
        )
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 1_250)

        first = await runner.dispatch_wallet_trade(
            _wallet_trade("shared-source", wallet="0xfirst")
        )
        second = await runner.dispatch_wallet_trade(
            _wallet_trade("shared-source", wallet="0xsecond")
        )
        return first, second, bot.seen

    first, second, seen = asyncio.run(run())

    assert first.accepted is True
    assert second.accepted is True
    assert seen == ["shared-source", "shared-source"]


def test_runner_calls_start_and_stop_for_wallet_stream(dummy_context: BotContext) -> None:
    async def run() -> tuple[int, int]:
        bot = RecordingBot(seen=[])
        runner = BotRunner(bot, dummy_context, now_ms_fn=lambda: 1_250)

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


def _bot_config(
    name: str,
    *,
    wallets: tuple[str, ...],
    **overrides: object,
) -> BotConfig:
    return BotConfig(
        name=name,
        stream_rules=(StreamRule(StreamRelation.INDEPENDENT, wallet_addresses=wallets),),
        **overrides,  # type: ignore[arg-type]
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
