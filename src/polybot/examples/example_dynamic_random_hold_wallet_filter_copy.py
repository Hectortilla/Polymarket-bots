"""Dynamic random-hold example restricted to configured wallet activity."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.markets import market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.framework.wallets import normalize_wallet_address
from polybot.examples.wallet_copy import (
    COPY_TRADE_NOTIONAL_USDC,
    fixed_dollar_copy_order,
)


type CopyPositionKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class CopyTradeDecision:
    """The deterministic copy order and position it may update."""

    source_key: str
    position_key: CopyPositionKey
    open_size: Decimal
    order: OrderRequest


def copy_trade_decision(
    trade: WalletTradeEvent,
    *,
    applied_source_ids: frozenset[str],
    open_positions: Mapping[CopyPositionKey, Decimal],
) -> CopyTradeDecision | None:
    """Build a bounded copy order without mutating bot or broker state."""
    if trade.source_key in applied_source_ids:
        return None
    position_key = (
        normalize_wallet_address(trade.wallet),
        trade.condition_id,
        trade.token_id,
    )
    open_size = open_positions.get(position_key, Decimal("0"))
    if trade.side is Side.SELL:
        if open_size <= 0:
            return None
        requested_size = min(COPY_TRADE_NOTIONAL_USDC / trade.price, open_size)
    else:
        requested_size = COPY_TRADE_NOTIONAL_USDC / trade.price
    return CopyTradeDecision(
        source_key=trade.source_key,
        position_key=position_key,
        open_size=open_size,
        order=fixed_dollar_copy_order(trade, size=requested_size),
    )


def positions_after_copy_fill(
    open_positions: Mapping[CopyPositionKey, Decimal],
    decision: CopyTradeDecision,
    *,
    side: Side,
    filled_size: Decimal,
) -> dict[CopyPositionKey, Decimal]:
    """Return the next copy positions after an accepted non-zero fill."""
    updated = dict(open_positions)
    if side is Side.BUY:
        updated[decision.position_key] = decision.open_size + filled_size
        return updated
    remaining = max(Decimal("0"), decision.open_size - filled_size)
    if remaining:
        updated[decision.position_key] = remaining
    else:
        updated.pop(decision.position_key, None)
    return updated


class ExampleDynamicRandomHoldWalletFilterBot(BaseBot):
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
        self.wallet_addresses = tuple(
            normalize_wallet_address(wallet) for wallet in wallet_addresses
        )
        if not self.wallet_addresses:
            raise ValueError("wallet_addresses must contain at least one wallet")
        self._open_positions: dict[CopyPositionKey, Decimal] = {}
        self._applied_source_ids: set[str] = set()

    @property
    def open_positions(self) -> dict[CopyPositionKey, Decimal]:
        """Return tracked position sizes keyed by wallet, condition, and token."""
        return self._open_positions.copy()

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

    def order_for_trade(
        self, trade: WalletTradeEvent, *, size: Decimal | None = None
    ) -> OrderRequest:
        return fixed_dollar_copy_order(trade, size=size)

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        decision = copy_trade_decision(
            trade,
            applied_source_ids=frozenset(self._applied_source_ids),
            open_positions=self._open_positions,
        )
        if decision is None:
            return
        fill = await ctx.broker.submit(decision.order)
        if fill.filled_size <= 0:
            return
        self._applied_source_ids.add(decision.source_key)
        self._open_positions = positions_after_copy_fill(
            self._open_positions,
            decision,
            side=trade.side,
            filled_size=fill.filled_size,
        )


def create(config: BotConfig) -> ExampleDynamicRandomHoldWalletFilterBot:
    """CLI factory; wallets come from the standard BOT_STREAM_RULES env value."""
    return ExampleDynamicRandomHoldWalletFilterBot(
        slug_prefix="btc-updown-5m",
        wallet_addresses=tuple(
            dict.fromkeys(
                wallet
                for rule in config.stream_rules
                for wallet in rule.wallet_addresses
            )
        ),
    )
