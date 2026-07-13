# Bot Framework Architecture

## Goals

- Keep all custom bot code inside this standalone `polybot` package.
- Keep the package isolated from the main app.
- Make new polybot small: subclass `BaseBot`, override event hooks, use `ctx`.
- Treat low latency as a core framework requirement, not an optimization.
- Make paper trading realistic enough to test bot behavior before live trading.
- Keep files short and named by responsibility.

## Current Status

Slices 1 through 5 are implemented: framework contracts, the paper fill engine,
public Polymarket market-data adapters, wallet activity Data API inputs, a
paper runner CLI, and an opt-in terminal dashboard.
Public adapters use the unified SDK for Gamma discovery, CLOB bootstrap
snapshots, market WebSocket events, and wallet trade/activity reads. The package
does not yet implement authenticated clients or an arbitrary-wallet trade
stream. The CLI subscribes only to current markets, resolves next markets
best-effort for rollover preparation, and rebuilds its current subscriptions
when a dynamic bot's active stream plan changes. It fails closed when wallet
addresses are configured without an injected compatible source.
CLI paper runs persist normalized source-event claims under `.bot-state/` so a
restart cannot submit the same wallet-following source event twice. Direct
`PaperBroker` users may inject another idempotency store; tests retain the
process-local default.

## Official Client Boundary

Polymarket network adapters must be built on official Polymarket Python
libraries wherever those libraries support the required capability. The
default is the unified `polymarket-client` SDK, using `AsyncPublicClient` for
public discovery, market data, and public streams and `AsyncSecureClient` for
authenticated reads, trading, and user streams. This matches the framework's
async, event-driven runtime.

When the unified SDK does not expose a required operation, use the relevant
specialized official client before writing a direct integration. For example,
`py-clob-client-v2` is the official full-CLOB Python client and
`py-builder-relayer-client` is the official relayer client. Direct HTTP or
WebSocket code is the last resort and requires a documented capability,
correctness, or latency gap in `api-notes.md` and the relevant implementation
slice. Authentication, signing, and order serialization must never be
hand-rolled when an official library supports them.

The official libraries are transport/protocol dependencies, not framework
contracts. Modules under `polybot.polymarket` own their lifecycle and convert SDK
models and events into `BookSnapshot`, `WalletTradeEvent`, `FillEvent`, and
other package-owned types. Bots, runners, paper execution, and broker protocols
must not import SDK types. The selected library version must be pinned and its
adapter behavior covered by contract tests, especially while
`polymarket-client` remains beta.

## Non-Goals

- No FastAPI routes.
- No frontend integration.
- No database integration in v1.
- No mirror-follow app behavior.
- No RFQ, combo, perps, bridge, or redemption support in v1.

## Package Layout

```text
polyfollow-polybot/
  src/polybot/       # Installed and imported as `polybot`.
  docs/
  framework/
    base.py       # BaseBot event hooks.
    config.py     # Global env config plus per-bot overrides.
    context.py    # Object passed to every bot hook.
    dedupe.py     # Source event dedupe for wallet-following inputs.
    dispatch.py   # Typed dispatch outcomes and stable skip reasons.
    events/       # Orders/fills plus semantic book and wallet-trade contracts.
    markets.py    # Static and dynamic market subscription contracts.
    wallets.py    # Watched-wallet subscription contracts.
    runner/       # Dispatch orchestration plus owned validation policy.
    polymarket/       # Installed as polybot.polymarket; does not shadow the SDK.
    gamma.py      # SDK-backed market discovery and future-slug retry.
    normalization/ # Market, book, and scalar SDK-payload normalization.
    data.py       # SDK-backed positions/trades/activity adapter.
    clob.py       # Official-client-backed CLOB adapter.
    wallet_activity/  # Wallet trades/activity stream and fallback.
    ws_market.py  # SDK-backed public market stream and depth state.
    ws_user.py    # SDK-backed authenticated user stream adapter.
    types.py      # Polymarket-specific normalized types.
  execution/
    broker.py     # Broker protocol used by polybot.
    paper/        # Orchestration, validation, fill math, market data, portfolio.
    live.py       # Live broker.
    orders.py     # Shared order and fee helpers.
  examples/
  tests/
```

## Runtime Flow

```text
MarketStream
  -> BookSnapshot
  -> per-token newest-pending coalescing
  -> market slug route check
  -> BotRunner
  -> BaseBot.on_book(ctx, book)
  -> ctx.broker.submit(OrderRequest)
  -> ObservableBroker (CLI-only)
  -> PaperBroker
  -> FillEvent returned to the calling strategy hook
```

Paper and live brokers intentionally share `OrderRequest` and `FillEvent`.
The bot should not know whether the fill came from a simulation or from the
authenticated user WebSocket.

Wallet-following bots use a parallel event path:

```text
WalletActivityStream or Data API reconciliation
  -> WalletTradeEvent
  -> market slug route check
  -> watched wallet address route check
  -> SourceEventDeduper
  -> BotRunner
  -> BaseBot.on_wallet_trade(ctx, trade)
  -> ctx.broker.submit(OrderRequest)
  -> ObservableBroker (CLI-only)
  -> PaperBroker
  -> FillEvent returned to the calling strategy hook
```

`dispatch_book()` and `dispatch_wallet_trade()` return `DispatchOutcome`.
Accepted events have no skip reason. Rejected events use the finite
`DispatchSkipReason` contract for route mismatches, malformed/stale/future data,
crossed books, and duplicate source events.

The CLI merger applies stream-specific backpressure before dispatch. It retains
at most one pending `BookSnapshot` per token and replaces that snapshot with the
newest arrival, so a slow strategy does not drain an obsolete FIFO of books.
Idempotent market-trade wake hints are similarly coalesced by condition ID.
Wallet trades are never coalesced: every normalized wallet event remains in
lossless FIFO order. Market-data memory is therefore bounded by the subscribed
token and condition counts, while wallet traffic intentionally retains
lossless semantics. The runner's five-second default freshness validation is
unchanged and still rejects a genuinely stale latest snapshot.

## Terminal Observability

The CLI enables its terminal dashboard by default and accepts `--no-dashboard`
for headless operation. It may attach a fail-open `RuntimeObserver` without exposing it to bots,
adapters, or paper execution. The observer receives lifecycle, stream,
dispatch, order, fill, and portfolio events. Its Rich dashboard projects them
in memory, uses `asciichartpy` for fixed-scale price and variance-padded
executable-wallet-value charts. The price chart is taller for clearer y-axis
resolution. Completed buys and sells are marked directly on the traded token's
line in wallet-value green and red, respectively. Press `z` to narrow the
displayed time window,
`x` to widen it, and `r` to reset it. Zooming resamples history into a fixed
chart width, and the visible range's start and end times are shown below the
plots. These dashboard-only controls never affect bot execution.
Expired market data retains its last plotted
value in a dimmed series rather than being treated as a current quote. The
dashboard renders independently of bot execution.

Stream health distinguishes local book coalescing from upstream SDK loss. It
reports run-lifetime raw book arrivals and pending snapshots superseded before
dispatch, plus cumulative and recent drop ratios for telemetry state. Queue depth is
reset when a dynamic subscription generation closes, while lifetime counts and
peak depth continue across stream-plan rebuilds.

Dashboard state sampling takes a locked snapshot before rendering in a worker
thread. A rendering failure closes the live display and prints its traceback to
the terminal while the fail-open observer boundary lets bot execution continue.

Custom CLI integrations can pass a
`polybot.cli.observability.observer.RuntimeObserver` to `run_bot()`. Its
`start(config)`, `emit(event)`, and `stop()` methods receive
`polybot.cli.observability.events.RuntimeEvent` values; observer exceptions are
deliberately suppressed so telemetry cannot interrupt the paper runtime.

The current paper CLI does not automatically call `BaseBot.on_fill()` after
`broker.submit()`. Strategies that need immediate paper fill handling should
use the returned `FillEvent`; `on_fill()` remains available to runtimes that
explicitly dispatch fill events.

## Bot Contract

Each custom bot subclasses `BaseBot`:

```python
class MyBot(BaseBot):
    async def on_start(self, ctx: BotContext) -> None:
        ...

    async def current_stream_rules(self, ctx: BotContext, now_ms: int) -> tuple[StreamRule, ...]:
        ...

    async def next_stream_rules(self, ctx: BotContext, now_ms: int) -> tuple[StreamRule, ...]:
        ...

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        ...

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        ...

    async def on_fill(self, ctx: BotContext, fill: FillEvent) -> None:
        ...
```

Only override hooks that are needed. Do not put SDK clients, HTTP clients,
signing, fee math, or simulation details in bot classes.

## Multi-Market Routing

Multi-market bots are supported through market slugs. A bot can use a static
list from config:

```text
BOT_STREAM_RULES=[{"relation":"filtered","market_slugs":["btc-up","eth-up","sol-up"],"wallet_addresses":["0x0000000000000000000000000000000000000001"]}]
```

The default `BaseBot.current_stream_rules()` returns configured stream rules.
The runner refreshes its stream plan before dispatch and routes events according
to the active relation.

Market-sensitive events must carry market identity:

- `BookSnapshot.market_slug`
- `BookSnapshot.condition_id`
- `WalletTradeEvent.market_slug`
- `WalletTradeEvent.condition_id`
- `OrderRequest.market_slug`
- `OrderRequest.condition_id`

If a bot has no configured/current market set, the runner accepts all market
events. Once a bot declares current markets, untagged events are rejected rather
than guessed.

Cross-market strategies should use one event callback and branch on
`event.market_slug`. A signal from one slug can submit an `OrderRequest` for a
different `market_slug`, as long as the target market is also part of the bot's
current market plan or was deliberately pre-resolved by the bot.

## Dynamic Consecutive Markets

Dynamic market bots should override `current_stream_rules()` and
`next_stream_rules()`.
This supports short-lived markets whose slug can be derived from the current
time bucket, while allowing the runner or future stream manager to subscribe to
the next market before rollover.

Example shape:

```python
class FiveMinuteBucketBot(BaseBot):
    async def current_stream_rules(self, ctx: BotContext, now_ms: int) -> tuple[StreamRule, ...]:
        return (MarketSubscription(slug=self.slug_for(now_ms, bucket_offset=0)),)

    async def next_stream_rules(self, ctx: BotContext, now_ms: int) -> tuple[StreamRule, ...]:
        return (MarketSubscription(slug=self.slug_for(now_ms, bucket_offset=1)),)
```

The framework does not hardcode BTC or five-minute market rules. It provides
the hook structure so a bot can compute the current slug on startup, compute the
next slug ahead of time, and transition instantly when the active market closes.

Future stream managers should use `MarketPlan.next` to pre-resolve metadata and
pre-subscribe where the external APIs support it.

## Multi-Wallet Routing

Wallet-following polybot support a static list of leader addresses from config:

```text
`BOT_STREAM_RULES` is the sole configuration schema for market/wallet topology.
```

Wallet selectors are declared by `StreamRule.wallet_addresses`; address matching
is case-insensitive, and repeated configured addresses collapse to one selector.

If a bot has no configured/current wallet set, the runner accepts trades from
all wallets so custom upstream filtering remains possible. Once a bot declares
wallets, trades from other addresses are rejected before dedupe and strategy
logic. A bot may override `current_stream_rules()` for a deliberate
runtime-managed leader set.

Market and wallet routing are independent and cumulative. A wallet trade must
match both the current wallet plan and the current market plan when both are
declared. This permits one follower to watch many leaders across many markets
without duplicating bot instances.

## Configuration

Configuration has two layers:

1. Global environment variables loaded by `BotConfig.from_env(name)`.
2. Per-bot overrides through `config.with_overrides(...)`.

Example:

```python
config = BotConfig.from_env("dip-buyer").with_overrides(
    max_order_size=Decimal("5"),
    paper_latency_ms=400,
)
```

Global env should hold account-level and shared defaults. Per-bot overrides
should hold strategy-specific risk and simulation knobs.

## Execution Modes

### Paper

Paper is the default mode. It must simulate:

- Network latency.
- Latency jitter.
- Fill-time order-book movement.
- Marketable order sweep across book depth.
- Partial fills.
- Max slippage rejection.
- Taker fee calculation per fill.
- Portfolio cash and position updates.

### Live

Live must be behind an explicit hard gate:

- `BOT_MODE=live`
- `BOT_LIVE_ENABLED=true`
- `POLYMARKET_PRIVATE_KEY` is configured.
- `POLY_API_KEY`, `POLY_API_SECRET`, and `POLY_API_PASSPHRASE` are configured.
- `DEPOSIT_WALLET_ADDRESS` is configured as the funder address.

The live broker submits signed CLOB orders through an official Polymarket SDK or
client and confirms fills from the official SDK's authenticated user stream
when supported. It must cancel open orders on shutdown when that is safe and
configured.

## Paper Realism Rule

Paper mode must not fill against stale, future-dated, malformed, or crossed
decision-time prices. It should queue an
order, wait configured latency plus jitter, then fill against the latest known
book at fill time. If no fresh book is available, the order is rejected with a
stable reason instead of guessing. Source IDs are claimed atomically across the
full in-flight submission so concurrent duplicates cannot apply two portfolio
transitions. Successful paper source claims remain available for the broker's
process lifetime; durable claims across restarts require a future persistence
slice because v1 has no database integration.

## Performance Rule

Live bot inputs must use the fastest correct source available. Do not choose a
slower polling path because it is easier to implement.

Primary live data paths:

- Public market/order-book changes: official async SDK market subscription.
- Own live order and fill status: official async SDK user subscription.
- Watched-wallet trades: the lowest-latency stream that can correctly identify
  wallet, condition ID, token ID, side, size, price, timestamp, and source ID.
- Static or slowly changing metadata: Gamma/CLOB REST, cached before hot-path
  decisions whenever possible.

The last two paths must also use an official SDK/client operation wherever one
exists. REST and WebSocket describe the upstream transport; they do not imply
that this package should implement that transport itself.

REST polling is not a primary live signal path for fast bots. It is allowed for:

- Startup bootstrap.
- Reconnect backfill.
- Reconciliation.
- Metadata enrichment.
- Fallback when no correct streaming source exists.

If Polymarket does not expose an official arbitrary-wallet trade WebSocket, the
wallet-following implementation should investigate on-chain or indexer
WebSocket streams before accepting Data API polling as the live path. Polling
can be used as a temporary degraded mode only when the docs and config make that
latency tradeoff explicit.

## Wallet-Following Rule

Wallet-following is a first-class strategy type. A follower bot must react to
`WalletTradeEvent`, not infer leader activity from public market-book updates.
One follower may subscribe to multiple leader wallets and must apply the same
normalization, routing, freshness, and dedupe rules to every leader.

Every normalized wallet trade must include:

- Leader wallet address.
- Condition ID.
- Token ID.
- Side.
- Size.
- Price.
- Stable `source_id`.
- Leader trade timestamp.
- Local observed timestamp.
- Transaction hash when available.

The `source_id` is mandatory because activity sources can replay rows during
polling, reconnect, or reconciliation. The runner dedupes by normalized wallet
address plus source ID before calling `on_wallet_trade`; equal source IDs from
different watched wallets remain distinct events.

Orders produced from a wallet trade should put `trade.source_key` into
`OrderRequest.source_id`. Broker implementations should preserve that ID in
paper fill records, live order metadata where possible, logs, and reconciliation
state.

Paper wallet-following should model both detection delay and order-submission
delay. The event's `observed_at_ms - trade_timestamp_ms` is the measured
detection lag. The paper broker then adds configured execution latency and fills
against the fill-time book.

Preferred source order:

1. A low-latency wallet activity stream if one exists and can emit normalized
   wallet, condition, token, side, size, price, timestamp, and source ID.
2. An on-chain/indexer stream with the same normalized fields.
3. Data API `/trades?user=...` and `/activity?user=...` for bootstrap,
   reconnect backfill, reconciliation, and degraded fallback.
