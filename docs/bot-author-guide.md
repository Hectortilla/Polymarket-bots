# Bot Author Guide

## Minimal Bot

```python
from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot


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
- Use `current_stream_rules()` for market, wallet, and mixed subscriptions.
- Do not import `backend/app`.
- Do not access `.env` directly from polybot.
- Do not compute fees inside polybot.
- Do not sign orders inside polybot.
- Do not import or instantiate Polymarket SDK/client classes inside polybot.

Official Polymarket libraries belong behind the framework adapters. Bot code
uses `ctx.markets`, `ctx.books`, normalized events, and `ctx.broker`; this keeps
strategies independent of SDK releases and guarantees that paper and live modes
continue to share package-owned contracts.

## Common Hooks

`on_start`

- Resolve markets.
- Store token IDs.
- Initialize strategy state.

`current_stream_rules`

- Return `StreamRule` values for the current market/wallet topology.
- Use `StreamRelation.FILTERED` for wallet-and-market intersection and
  `StreamRelation.INDEPENDENT` for market-or-wallet union.

`next_stream_rules`

- Return the rules that should be prepared for the next dynamic interval.

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

- Update bot-local state after an explicitly dispatched fill.
- The paper CLI returns a `FillEvent` from `ctx.broker.submit()` but does not
  automatically invoke this hook; use the returned value when needed.

`on_stop`

- Clean up bot-local resources.
- The broker owns order cancellation behavior.

## Config Overrides

Use global `.env` defaults for shared behavior:

```text
BOT_MODE=paper
BOT_STREAM_RULES=[{"relation":"filtered","market_slugs":["btc-up","eth-up"],"wallet_addresses":["0x0000000000000000000000000000000000000001"]}]
BOT_MAX_ORDER_SIZE=10
BOT_MAX_SLIPPAGE_PCT=0.02
BOT_PAPER_LATENCY_MS=250
BOT_PAPER_LATENCY_JITTER_MS=100
BOT_BOOK_MAX_AGE_MS=5000
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

## Terminal Dashboard

The CLI dashboard is enabled by default. It is an external observer: bots
should not import dashboard classes or emit display events. Use
`--no-dashboard` for headless runs.
It shows market/wallet activity, paper orders and fills, multi-token prices,
and executable paper wallet value without changing strategy behavior. When a
market book expires, its last chart value stays visible in a dimmed color.

Tools integrating the CLI may pass a custom
`polybot.cli.observability.observer.RuntimeObserver` to `run_bot()`. Observers
receive `polybot.cli.observability.events.RuntimeEvent` values and must remain
non-essential: the runtime suppresses their lifecycle and event failures.

## Wallet-Following Bot

```python
from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest
from polybot.framework.events.wallet_trades import WalletTradeEvent


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

For a static multi-wallet bot, declare the wallet selectors in
`BOT_STREAM_RULES`; the runner applies the selected relation before this hook
runs. Keep an explicit set in the strategy only when it needs per-leader policy.

## Dynamic Market Bot

```python
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.markets import MarketSubscription, market_bucket_slug


class FiveMinuteBot(BaseBot):
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (MarketSubscription(slug=self._slug(now_ms, 0)),)

    async def next_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (MarketSubscription(slug=self._slug(now_ms, 1)),)

    def _slug(self, now_ms: int, bucket_offset: int) -> str:
        return market_bucket_slug(
            self.prefix,
            now_ms,
            300,
            bucket_offset=bucket_offset,
        )
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
same bot can declare both slugs in `current_stream_rules()`, receive both markets'
book events through the same callback, and route decisions by slug.
