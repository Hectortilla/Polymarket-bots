# Bot Author Guide

## Minimal Bot

```python
from decimal import Decimal

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.events import OrderRequest, Side
from bots.framework.events.books import BookSnapshot


class BuyCheapYes(BaseBot):
    def __init__(self, yes_token_id: str) -> None:
        self.yes_token_id = yes_token_id

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        if book.token_id != self.yes_token_id or not book.asks:
            return

        best_ask = book.asks[0]
        if best_ask.price <= Decimal("0.45"):
            await ctx.broker.submit(
                OrderRequest(
                    token_id=self.yes_token_id,
                    side=Side.BUY,
                    price=best_ask.price,
                    size=min(best_ask.size, ctx.config.max_order_size),
                )
            )
```

## Rules For Bot Files

- Keep each bot in one short file.
- Put strategy decisions in event hooks.
- Use `ctx.broker` for orders.
- Use `ctx.markets` for discovery.
- Use `ctx.books` for latest cached books.
- Use config market slugs or market hooks for multi-market bots.
- Use config wallet addresses or `current_wallets()` for multi-wallet followers.
- Do not import `backend/app`.
- Do not access `.env` directly from bots.
- Do not compute fees inside bots.
- Do not sign orders inside bots.
- Do not import or instantiate Polymarket SDK/client classes inside bots.

Official Polymarket libraries belong behind the framework adapters. Bot code
uses `ctx.markets`, `ctx.books`, normalized events, and `ctx.broker`; this keeps
strategies independent of SDK releases and guarantees that paper and live modes
continue to share package-owned contracts.

## Common Hooks

`on_start`

- Resolve markets.
- Store token IDs.
- Initialize strategy state.

`current_markets`

- Return the market slugs that should receive events right now.
- Use the default implementation for static `BOT_MARKET_SLUGS`.
- Override it for time-bucketed or otherwise dynamic markets.

`next_markets`

- Return market slugs that should be prepared next.
- Use this for consecutive short-lived markets so metadata/subscriptions can be
  ready before rollover.

`current_wallets`

- Return the leader wallet addresses whose trades should reach the bot now.
- Use the default implementation for static `BOT_WALLET_ADDRESSES`.
- Override it only for a deliberate runtime-managed leader set.

`on_book`

- React to public order-book updates.
- Submit orders through the broker.
- Keep decisions fast.

`on_wallet_trade`

- React to a normalized trade from a watched wallet.
- Mirror, fade, scale, filter, or ignore the leader trade.
- Use `trade.source_id` indirectly through the runner dedupe; do not build
  custom dedupe inside every bot.

`on_fill`

- Update bot-local state after a fill.
- Stop quoting after a position is reached.
- React to partial fills.

`on_stop`

- Clean up bot-local resources.
- The broker owns order cancellation behavior.

## Config Overrides

Use global `.env` defaults for shared behavior:

```text
BOT_MODE=paper
BOT_MARKET_SLUGS=btc-up,eth-up
BOT_WALLET_ADDRESSES=0xleader1,0xleader2
BOT_MAX_ORDER_SIZE=10
BOT_MAX_SLIPPAGE_PCT=0.02
BOT_PAPER_LATENCY_MS=250
BOT_PAPER_LATENCY_JITTER_MS=100
BOT_PAPER_PORTFOLIO_USDC=1000
BOT_LIVE_ENABLED=false
POLYMARKET_PRIVATE_KEY=
POLY_API_KEY=
POLY_API_SECRET=
POLY_API_PASSPHRASE=
DEPOSIT_WALLET_ADDRESS=
```

Use per-bot overrides for strategy-specific settings:

```python
config = BotConfig.from_env("fast-test").with_overrides(
    max_order_size=Decimal("2"),
    paper_latency_ms=100,
)
```

## Testing A Bot

Unit tests should feed synthetic `BookSnapshot` events into `BotRunner` and use a
fake broker. Do not call Polymarket in bot unit tests.

Adapter tests for the framework itself should exercise recorded or synthetic
official-SDK models and events, then assert their conversion into internal
contracts. They should not teach individual bots about SDK response shapes.

Paper-broker tests should use deterministic latency and book sequences:

- Decision book at time T.
- Fill book at time T plus latency.
- Expected fills, fees, and cash movements.

## Wallet-Following Bot

```python
from decimal import Decimal

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.events import OrderRequest
from bots.framework.events.wallet_trades import WalletTradeEvent


class FollowLeaders(BaseBot):
    def __init__(self, leader_wallets: tuple[str, ...]) -> None:
        self.leader_wallets = frozenset(
            wallet.lower() for wallet in leader_wallets
        )

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        if trade.wallet.lower() not in self.leader_wallets:
            return

        await ctx.broker.submit(
            OrderRequest(
                token_id=trade.token_id,
                side=trade.side,
                price=trade.price,
                size=min(trade.size * Decimal("0.25"), ctx.config.max_order_size),
                market_slug=trade.market_slug,
                condition_id=trade.condition_id,
                source_id=trade.source_key,
                reason="wallet_follow",
            )
        )
```

Wallet-following strategies receive already-validated normalized events.
Structural validation, finite positive price/size checks, required identifiers,
timestamp ordering, and freshness belong to adapter and runner boundaries.
Strategies should make the scaling rule obvious. Examples:

- Fixed multiplier of leader size.
- Cap by `ctx.config.max_order_size`.
- Ignore trades below a minimum size.
- Ignore stale trades when observed delay is too high.
- Ignore unsupported markets until Gamma/CLOB metadata is resolved.

For a static multi-wallet bot, configure the same addresses in
`BOT_WALLET_ADDRESSES`; the runner then filters unrelated leaders before this
hook runs. Keep an explicit set in the strategy only when the strategy itself
needs per-leader policy. A single follower can combine multiple wallet and
market subscriptions: both route filters must match before dispatch.

## Dynamic Market Bot

```python
from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.markets import MarketSubscription


class FiveMinuteBot(BaseBot):
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def current_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (MarketSubscription(slug=self._slug(now_ms, 0)),)

    async def next_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (MarketSubscription(slug=self._slug(now_ms, 1)),)

    def _slug(self, now_ms: int, offset: int) -> str:
        bucket = now_ms // 1000 // 300 + offset
        return f"{self.prefix}-{bucket * 300}"
```

This lets a bot initialize in the middle of a bucket, receive events for the
current market, and prepare the next slug before rollover.

## Cross-Market Bot

Use one `on_book` handler and inspect `book.market_slug` to decide which market
produced the event. Orders may target a different market by setting
`OrderRequest.market_slug`.

```python
rule = CrossMarketRule(
    signal_slug="btc-up",
    target_slug="eth-down",
    target_token_id="eth-no-token",
    trigger_price=Decimal("0.40"),
    order_price=Decimal("0.52"),
    max_size=Decimal("3"),
)

bot = ExampleMultiMarketBot(rules=(rule,))
```

In this example, a cheap ask on `btc-up` can trigger a BUY on `eth-down`. The
same bot can declare both slugs in `current_markets()`, receive both markets'
book events through the same callback, and route decisions by slug.
