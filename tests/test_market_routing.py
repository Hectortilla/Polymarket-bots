import asyncio
from dataclasses import dataclass
from decimal import Decimal

import pytest

from bots.framework.base import BaseBot
from bots.framework.config import BotConfig
from bots.framework.context import BotContext
from bots.framework.dispatch import DispatchSkipReason
from bots.framework.dispatch import DispatchOutcome
from bots.framework.events import Side
from bots.framework.events.books import BookLevel, BookSnapshot
from bots.framework.events.wallet_trades import WalletTradeEvent
from bots.framework.markets import MarketSubscription, market_bucket_slug
from bots.framework.runner import BotRunner


@dataclass(slots=True)
class RecordingMarketBot(BaseBot):
    books: list[str]
    wallet_trades: list[str]

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        self.books.append(book.market_slug or "")

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        self.wallet_trades.append(trade.market_slug or "")


class BucketBot(RecordingMarketBot):
    async def current_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (
            MarketSubscription(
                slug=market_bucket_slug("btc-updown-5m", now_ms, 300),
            ),
        )

    async def next_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (
            MarketSubscription(
                slug=market_bucket_slug(
                    "btc-updown-5m",
                    now_ms,
                    300,
                    bucket_offset=1,
                ),
            ),
        )


def test_runner_routes_static_multi_market_books(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, bool, list[str]]:
        ctx = _with_config(dummy_context, BotConfig(name="multi", market_slugs=("btc", "eth")))
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 1_000)

        accepted = await runner.dispatch_book(_book("btc"))
        rejected = await runner.dispatch_book(_book("sol"))

        return accepted, rejected, bot.books

    accepted, rejected, books = asyncio.run(run())

    assert accepted.accepted is True
    assert rejected.skip_reason is DispatchSkipReason.MARKET_NOT_TRACKED
    assert books == ["btc"]


def test_runner_accepts_wallet_trade_without_market_plan_per_contract(
    dummy_context: BotContext,
) -> None:
    async def run() -> bool:
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(
            bot,
            _with_config(dummy_context, BotConfig(name="wallet")),
            now_ms_fn=lambda: 1_100,
        )
        outcome = await runner.dispatch_wallet_trade(
            _wallet_trade("btc", "trade-1")
        )
        return outcome.accepted

    assert asyncio.run(run()) is True


def test_runner_rejects_fresh_book_from_untracked_market(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, int]:
        ctx = _with_config(dummy_context, BotConfig(name="multi", market_slugs=("btc", "eth")))
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 1_000)

        accepted = await runner.dispatch_book(_book("sol"))
        return accepted, len(bot.books)

    accepted, book_count = asyncio.run(run())

    assert accepted.skip_reason is DispatchSkipReason.MARKET_NOT_TRACKED
    assert book_count == 0


def test_runner_rejects_future_dated_book(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, int]:
        ctx = _with_config(
            dummy_context,
            BotConfig(name="multi", market_slugs=("btc", "eth"), book_max_age_ms=1_000),
        )
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 1_000)

        accepted = await runner.dispatch_book(
            BookSnapshot(
                token_id="123",
                bids=(),
                asks=(),
                received_at_ms=2_000,
                market_slug="btc",
            )
        )
        return accepted, len(bot.books)

    accepted, book_count = asyncio.run(run())

    assert accepted.skip_reason is DispatchSkipReason.BOOK_FUTURE_DATED
    assert book_count == 0


def test_runner_rejects_stale_book(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, int]:
        ctx = _with_config(
            dummy_context,
            BotConfig(name="multi", market_slugs=("btc", "eth"), book_max_age_ms=1_000),
        )
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 2_000)

        accepted = await runner.dispatch_book(
            BookSnapshot(
                token_id="123",
                bids=(),
                asks=(),
                received_at_ms=500,
                market_slug="btc",
            )
        )
        return accepted, len(bot.books)

    accepted, book_count = asyncio.run(run())

    assert accepted.skip_reason is DispatchSkipReason.BOOK_STALE
    assert book_count == 0


def test_runner_rejects_malformed_book_level(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, int]:
        ctx = _with_config(dummy_context, BotConfig(name="multi", market_slugs=("btc", "eth")))
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 1_000)

        accepted = await runner.dispatch_book(
            BookSnapshot(
                token_id="123",
                bids=(),
                asks=(
                    BookLevel(price=Decimal("0"), size=Decimal("10")),
                ),
                received_at_ms=1_000,
                market_slug="btc",
            )
        )
        return accepted, len(bot.books)

    accepted, book_count = asyncio.run(run())

    assert accepted.skip_reason is DispatchSkipReason.BAD_BOOK_LEVEL
    assert book_count == 0


def test_runner_combines_multi_market_and_multi_wallet_routes(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[bool, bool, bool, list[str]]:
        ctx = _with_config(
            dummy_context,
            BotConfig(
                name="multi",
                market_slugs=("btc", "eth"),
                wallet_addresses=("0xleader", "0xsecond"),
            ),
        )
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 1_100)

        accepted = await runner.dispatch_wallet_trade(_wallet_trade("eth", "tx-1"))
        wrong_market = await runner.dispatch_wallet_trade(
            _wallet_trade("sol", "tx-2")
        )
        wrong_wallet = await runner.dispatch_wallet_trade(
            _wallet_trade("btc", "tx-3", wallet="0xother")
        )

        return accepted, wrong_market, wrong_wallet, bot.wallet_trades

    accepted, wrong_market, wrong_wallet, wallet_trades = asyncio.run(run())

    assert accepted.accepted is True
    assert wrong_market.skip_reason is DispatchSkipReason.MARKET_NOT_TRACKED
    assert wrong_wallet.skip_reason is DispatchSkipReason.WALLET_NOT_TRACKED
    assert wallet_trades == ["eth"]


def test_runner_rejects_wallet_trade_without_market_slug_when_planned(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[bool, int]:
        ctx = _with_config(dummy_context, BotConfig(name="multi", market_slugs=("btc", "eth")))
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 1_100)

        accepted = await runner.dispatch_wallet_trade(_wallet_trade(None, "tx-3"))
        return accepted, len(bot.wallet_trades)

    accepted, trade_count = asyncio.run(run())

    assert accepted.skip_reason is DispatchSkipReason.MARKET_NOT_TRACKED
    assert trade_count == 0


def test_runner_rejects_stale_wallet_trade(dummy_context: BotContext) -> None:
    async def run() -> tuple[bool, int]:
        ctx = _with_config(
            dummy_context,
            BotConfig(name="multi", market_slugs=("btc", "eth"), book_max_age_ms=500),
        )
        bot = RecordingMarketBot(books=[], wallet_trades=[])
        runner = BotRunner(bot, ctx, now_ms_fn=lambda: 2_000)

        accepted = await runner.dispatch_wallet_trade(_wallet_trade("btc", "tx-stale", observed_at_ms=2_000, trade_timestamp_ms=1_000))
        return accepted, len(bot.wallet_trades)

    accepted, trade_count = asyncio.run(run())

    assert accepted.skip_reason is DispatchSkipReason.WALLET_TRADE_STALE
    assert trade_count == 0


def test_dynamic_market_hooks_expose_current_and_next(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[str, str]:
        bot = BucketBot(books=[], wallet_trades=[])
        current = await bot.current_markets(dummy_context, 1_783_549_250_000)
        next_markets = await bot.next_markets(dummy_context, 1_783_549_250_000)

        return current[0].slug, next_markets[0].slug

    current_slug, next_slug = asyncio.run(run())

    assert current_slug == "btc-updown-5m-1783549200"
    assert next_slug == "btc-updown-5m-1783549500"


def test_dispatch_outcome_enforces_reason_invariant() -> None:
    with pytest.raises(ValueError, match="require a skip reason"):
        DispatchOutcome(accepted=False)
    with pytest.raises(ValueError, match="cannot have a skip reason"):
        DispatchOutcome(accepted=True, skip_reason=DispatchSkipReason.BOOK_STALE)


def _book(market_slug: str) -> BookSnapshot:
    return BookSnapshot(
        token_id="123",
        bids=(),
        asks=(),
        received_at_ms=1_000,
        market_slug=market_slug,
    )


def _wallet_trade(
    market_slug: str | None,
    source_id: str,
    *,
    wallet: str = "0xleader",
    observed_at_ms: int = 1_100,
    trade_timestamp_ms: int = 1_000,
) -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet=wallet,
        condition_id="0xcondition",
        token_id="123",
        side=Side.BUY,
        size=Decimal("1"),
        price=Decimal("0.50"),
        source_id=source_id,
        trade_timestamp_ms=trade_timestamp_ms,
        observed_at_ms=observed_at_ms,
        market_slug=market_slug,
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
