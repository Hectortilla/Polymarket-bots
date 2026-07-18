# Bot Author Guide

## Minimal Bot

```python
from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot


class BuyCheapOutcome(BaseBot):
    def __init__(self, outcome_token_id: str) -> None:
        self.outcome_token_id = outcome_token_id

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        if book.token_id != self.outcome_token_id or not book.asks:
            return

        best_ask = book.asks[0]
        if best_ask.price <= Decimal("0.45"):
            await ctx.broker.submit(
                OrderRequest(
                    token_id=self.outcome_token_id,
                    side=Side.BUY,
                    price=best_ask.price,
                    size=min(best_ask.size, ctx.config.max_order_size),
                )
            )
```

Outcome labels are opaque market metadata. Resolve the label advertised by the
market to its token ID; do not assume every market uses `Yes` and `No`.

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

`on_market_resolved`

- Receive a package-owned `MarketResolutionEvent` after paper and followed-wallet
  positions are settled and resolution state is persisted.

Resolution event contracts are defined in
`polybot.framework.events.resolutions`; import that module directly when a bot
needs the event or settlement types.
- Treat it as a lifecycle event, not as a fill; settlement does not fabricate an
  order or `FillEvent`.

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
BOT_EVENT_MAX_AGE_MS=5000
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

## Recording Markets For Future Backtests

Slice 9A defines the implemented standalone `python -m polybot.recording`
command. The recorder does not run a strategy or
paper broker. With `--bot`, it loads the factory only to evaluate the bot's
current and next stream rules, rejects any attempted order, and records the
markets named by those rules. This keeps dynamic slug generation in one place
without turning data collection into a trading run.

Record a dynamic bot's markets:

```sh
uv run python -m polybot.recording \
  --bot polybot.examples.example_btc_five_minute_momentum:create \
  --output recordings/btc-five-minute.sqlite \
  --duration 10d
```

Record a fixed set instead by repeating `--market-slug`:

```sh
uv run python -m polybot.recording \
  --market-slug btc-updown-5m-1767225600 \
  --market-slug eth-updown-5m-1767225600 \
  --output recordings/two-markets.sqlite \
  --duration 2h
```

`--bot` and `--market-slug` are mutually exclusive, `--output` is required,
and `--duration` accepts a positive integer followed by `s`, `m`, `h`, or `d`.
Without a duration the process runs until graceful interruption. `--resume`
requires an existing compatible SQLite recording archive with the same target
selection and appends a new session. Without `--resume`, the recorder refuses to
overwrite an existing output. A resumed run preserves the previous session and
records the offline interval as a coverage gap. `--dotenv` and `--override` have
their normal runner meanings when constructing the bot.

Dynamic bots should keep current and next market generation deterministic. The
recorder resolves both plans, subscribes to the current market, and
pre-subscribes an available next market before rollover. A not-yet-published
next slug is normal and is retried without interrupting the current stream.

Before evaluating a strategy, inspect the archive's sessions and coverage gaps.
`no detected gaps` means no loss was observed by the recorder; it does not mean
exchange-complete because Polymarket documents no market-stream sequence or
resume cursor. Slice 9B will own deterministic replay and the policy for gaps.

The Slice 9A archive contains public market metadata and aggregated book data
only. It cannot reproduce wallet-following hooks, private order/fill state,
individual maker priority, or decisions based on an external reference feed.
For example, the BTC five-minute momentum example is compatible because it uses
only its two normalized outcome books. A bot that reads Binance or Chainlink
prices needs those feeds recorded by a future input slice as well.

## Terminal Dashboard

The CLI dashboard is enabled by default. It is an external observer: bots
should not import dashboard classes, but may add custom Activity rows through
the framework contract. Use `--no-dashboard` for headless runs.
It shows market/wallet activity, paper orders and fills, multi-token prices,
green buy and red sell markers anchored to the traded token's line, and
executable paper wallet value without changing strategy behavior. When a
market book expires, its last chart value stays visible in a dimmed color.
Press `v` to switch from the market chart to a followed-wallet trade-time
timeline. The timeline has one lane per wallet; green/red/yellow indicate
buy/sell/mixed buckets, `·`/`●`/`◆` indicate relative notional, and dimmed
events were skipped before bot dispatch. It shares `z`/`x`/`r` time controls
with the market chart. Use `j`/`k` to page wallet lanes. Press `m` to show or
hide blue market events in Activity; they are hidden by default. Order and fill
rows show their market/outcome label after its metadata reaches the dashboard.

Emit bot activity from any async function that receives `ctx`:

```python
from polybot.framework.activity import ActivitySeverity

await ctx.activity.emit(
    "Rebound trigger confirmed",
    severity=ActivitySeverity.SUCCESS,
)
```

Activity is informational and fail-open: it cannot affect trading. The same
typed event reaches a custom runtime observer in headless runs.

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

### BTC five-minute probability-momentum example

`polybot.examples.example_btc_five_minute_momentum:create` is a complete
paper-trading example for consecutive `btc-updown-5m` markets. It deliberately
uses only the current Up and Down token books, so it demonstrates what can be
done without an external BTC price feed.

For each fresh pair of books it computes:

- A microprice for each token, weighted by best-bid and best-ask size.
- A normalized Up probability: `up_microprice / (up_microprice + down_microprice)`.
- Fast and slow exponential moving averages of that probability.
- Multi-sample probability momentum and the average absolute move over the same
  window as a noise estimate.

An entry needs EMA trend and momentum to agree and exceed both fixed minimums
and their adaptive noise floors. The target token must also have positive
three-level book imbalance. The imbalance is confirmation only because visible
depth can be canceled; it never creates a trade by itself.

The risk rules keep the example bounded:

- At most one long Up or Down position; it never opens a naked short.
- Both books must be fresh enough to pair, and both spreads must be acceptable.
- The target book must have adequate bid/ask depth and a non-extreme entry
  price.
- No entry during the opening buffer or near bucket expiry.
- Exit on executable-price stop, profit target, strong EMA reversal, maximum
  hold time, or the pre-expiry deadline.
- A cooldown after an exit prevents immediate churn.

Run it through the normal CLI:

```sh
BOT_MODE=paper \
BOT_MAX_ORDER_SIZE=5 \
uv run python -m polybot.cli \
  --bot polybot.examples.example_btc_five_minute_momentum:create
```

The defaults in `polybot.examples.btc_five_minute_strategy.MomentumSettings`
are intentionally readable starting values, not optimized parameters. Unit
tests cover its signal, confirmation, rollover, stop, and expiry behavior.
Historical replay remains Slice 9B, so those tests do not establish a live
trading edge or expected return. Slice 9A only gathers the market archive that
replay will consume.

### Dynamic wallet-filtered example

`polybot.my_bot:create` runs the separate dynamic random-hold wallet-filter
example. It reads a JSON wallet list from the root `.env` file. The market
slugs are generated from the time bucket:

```dotenv
EXAMPLE_DYNAMIC_RANDOM_HOLD_WALLETS='["0x0000000000000000000000000000000000000001","0x0000000000000000000000000000000000000002"]'
```

Each current and next bucket is then declared as a `filtered` stream rule for
that complete wallet list. The bot fails closed at construction time when the
list is empty. Its copied positions are tracked by normalized wallet,
condition, and token, so a sell from one followed wallet can only reduce a
position opened from that same wallet's buy; sells for untracked inventory are
ignored.

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
