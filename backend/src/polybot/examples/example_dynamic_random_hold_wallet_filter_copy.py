"""Dynamic random-hold example restricted to configured wallet activity."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from polybot.examples.btc_five_minute_market import (
    BTC_FIVE_MINUTE_BUCKET_SECONDS,
    BTC_FIVE_MINUTE_SLUG_PREFIX,
)
from polybot.examples.wallet_copy import (
    FixedDollarCopyPolicy,
)
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.markets import market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.framework.wallets import normalize_wallet_address

type CopyPositionKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class CopyTradeDecision:
    """The deterministic copy order and position it may update."""

    source_key: str
    position_key: CopyPositionKey
    open_size: Decimal
    order: OrderRequest


@dataclass(frozen=True, slots=True)
class CopyPositionBook:
    """A copy strategy's source claims and immutable position transitions."""

    applied_source_ids: frozenset[str] = frozenset()
    open_positions: Mapping[CopyPositionKey, Decimal] = field(default_factory=dict)

    def decision(self, trade: WalletTradeEvent) -> CopyTradeDecision | None:
        """Build a bounded copy order without mutating bot or broker state."""
        if trade.source_key in self.applied_source_ids:
            return None
        position_key = (
            normalize_wallet_address(trade.wallet),
            trade.condition_id,
            trade.token_id,
        )
        open_size = self.open_positions.get(position_key, Decimal("0"))
        maximum_size = _sellable_position_size(trade.side, open_size)
        if trade.side is Side.SELL and maximum_size is None:
            return None
        requested_size = FixedDollarCopyPolicy.size(
            trade,
            maximum_size=maximum_size,
        )
        return CopyTradeDecision(
            source_key=trade.source_key,
            position_key=position_key,
            open_size=open_size,
            order=FixedDollarCopyPolicy.order(trade, size=requested_size),
        )

    def after_fill(
        self, decision: CopyTradeDecision, *, side: Side, filled_size: Decimal
    ) -> CopyPositionBook:
        updated = dict(self.open_positions)
        if side is Side.BUY:
            updated[decision.position_key] = decision.open_size + filled_size
        else:
            remaining = max(Decimal("0"), decision.open_size - filled_size)
            if remaining:
                updated[decision.position_key] = remaining
            else:
                updated.pop(decision.position_key, None)
        return CopyPositionBook(
            self.applied_source_ids | {decision.source_key}, updated
        )


def _sellable_position_size(side: Side, open_size: Decimal) -> Decimal | None:
    if side is Side.BUY:
        return None
    return open_size if open_size > 0 else None


class ExampleDynamicRandomHoldWalletFilterBot(BaseBot):
    """Random-hold bot for consecutive five-minute buckets and wallet filters."""

    def __init__(
        self,
        slug_prefix: str,
        wallet_addresses: Iterable[str],
        bucket_seconds: int = BTC_FIVE_MINUTE_BUCKET_SECONDS,
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
        self._positions = CopyPositionBook()

    @property
    def open_positions(self) -> dict[CopyPositionKey, Decimal]:
        """Return tracked position sizes keyed by wallet, condition, and token."""
        return dict(self._positions.open_positions)

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

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        decision = self._positions.decision(trade)
        if decision is None:
            return
        fill = await ctx.broker.submit(decision.order)
        if not fill.has_execution:
            return
        self._positions = self._positions.after_fill(
            decision,
            side=trade.side,
            filled_size=fill.filled_size,
        )

    def order_for_trade(
        self, trade: WalletTradeEvent, *, size: Decimal | None = None
    ) -> OrderRequest:
        return FixedDollarCopyPolicy.order(trade, size=size)

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


def create(config: BotConfig) -> ExampleDynamicRandomHoldWalletFilterBot:
    """CLI factory; wallets come from the standard BOT_STREAM_RULES env value."""
    return ExampleDynamicRandomHoldWalletFilterBot(
        slug_prefix=BTC_FIVE_MINUTE_SLUG_PREFIX,
        wallet_addresses=tuple(
            dict.fromkeys(
                wallet
                for rule in config.stream_rules
                for wallet in rule.wallet_addresses
            )
        ),
    )
