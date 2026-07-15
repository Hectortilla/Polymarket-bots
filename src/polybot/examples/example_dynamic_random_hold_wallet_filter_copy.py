"""Dynamic random-hold example restricted to configured wallet activity."""

from __future__ import annotations

from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest
from polybot.framework.events.wallet_trades import WalletTradeEvent

from collections.abc import Iterable

from polybot.examples.example_random_hold import ExampleRandomHoldBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.markets import market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.framework.wallets import normalize_wallet_address

COPY_TRADE_NOTIONAL_USDC = Decimal("10")
FIXED_DOLLAR_COPY_REASON = "fixed_dollar_wallet_copy"


class ExampleDynamicRandomHoldWalletFilterBot(ExampleRandomHoldBot):
    """Random-hold bot for consecutive five-minute buckets and wallet filters."""

    def __init__(
        self,
        slug_prefix: str,
        wallet_addresses: Iterable[str],
        bucket_seconds: int = 300,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.slug_prefix = slug_prefix
        self.bucket_seconds = bucket_seconds
        self.wallet_addresses = wallet_addresses
        if not self.wallet_addresses:
            raise ValueError("wallet_addresses must contain at least one wallet")

    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (self._stream_rule(now_ms, bucket_offset=0),)

    async def next_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (self._stream_rule(now_ms, bucket_offset=1),)

    def _stream_rule(self, now_ms: int, *, bucket_offset: int) -> StreamRule:
        slug = market_bucket_slug(
            self.slug_prefix,
            now_ms,
            self.bucket_seconds,
            bucket_offset=bucket_offset,
        )
        return StreamRule(
            StreamRelation.FILTERED,
            market_slugs=(slug,),
            wallet_addresses=self.wallet_addresses,
        )

    def order_for_trade(self, trade: WalletTradeEvent) -> OrderRequest:
        return OrderRequest(
            token_id=trade.token_id,
            side=trade.side,
            price=trade.price,
            size=COPY_TRADE_NOTIONAL_USDC / trade.price,
            market_slug=trade.market_slug,
            condition_id=trade.condition_id,
            source_id=trade.source_key,
            reason=FIXED_DOLLAR_COPY_REASON,
        )

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        await ctx.broker.submit(self.order_for_trade(trade))


def create_btc_version(wallet_addresses: Iterable[str]) -> ExampleDynamicRandomHoldWalletFilterBot:
    """CLI factory; wallets come from the standard BOT_STREAM_RULES env value."""
    return ExampleDynamicRandomHoldWalletFilterBot(
        slug_prefix="btc-updown-5m",
        wallet_addresses=wallet_addresses,
    )
