# Bot Framework Architecture

## Goals

- Keep all custom bot code inside this standalone `polybot` package.
- Keep the package isolated from the main app.
- Make new polybot small: subclass `BaseBot`, override event hooks, use `ctx`.
- Treat low latency as a core framework requirement, not an optimization.
- Make paper trading realistic enough to test bot behavior before live trading.
- Keep files short and named by responsibility.

## Current Status

Slices 1 through 5 and Slices 9A through 11 are implemented: framework
contracts, the paper fill engine, public Polymarket market-data adapters, wallet
activity Data API inputs, the paper runner CLI, the standalone historical
market recorder, deterministic archive replay and performance artifacts, the
terminal dashboard, and dynamic market tracking and resolution settlement.
Public adapters use the unified SDK for Gamma discovery, CLOB bootstrap
snapshots, market WebSocket events, and wallet trade/activity reads. The package
does not yet implement authenticated clients or an arbitrary-wallet trade
stream. The CLI subscribes one union of unresolved configured, wallet-discovered,
and paper-position markets, resolves next markets best-effort for rollover
preparation, and replaces the union subscription when its registry changes. It
fails closed when wallet
addresses are configured without either the SDK-backed Data API client or an
injected compatible source. The CLI supplies the SDK-backed polling client;
an injected source is optional and can provide lower-latency wallet events.
At the adapter boundary, SDK-specific positional outcome fields become an
ordered pair of opaque `MarketOutcome(label, token_id)` values. Core framework
and execution code use generic token IDs and never infer meaning from labels.
CLI paper runs persist normalized source-event claims, followed-wallet epochs,
baselines, movement journals, checkpoints, and settlements under `.bot-state/`.
A restart cannot submit the same wallet-following source event twice or reapply
the same resolution. Direct
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
- No application database or database-service integration in v1. Slice 9A's
  user-selected SQLite file is a standalone local artifact.
- No mirror-follow app behavior.
- No RFQ, combo, perps, bridge, or redemption support in v1.

## Package Layout

```text
polyfollow-polybot/
  src/polybot/       # Installed and imported as `polybot`.
  docs/
  framework/
    base.py       # BaseBot event hooks.
    clock.py      # System and replay-compatible clock contract.
    config/       # Config model, defaults, environment, and stream-rule parsing.
    context.py    # Object passed to every bot hook.
    dedupe.py     # Source event dedupe for wallet-following inputs.
    dispatch.py   # Typed dispatch outcomes and stable skip reasons.
    events/       # Orders/fills plus book, wallet-trade, and resolution contracts.
    markets.py    # Static and dynamic market subscription contracts.
    wallets.py    # Watched-wallet subscription contracts.
    runner/       # Dispatch orchestration plus owned validation policy.
  cli/
    runner/       # Runtime lifecycle, stream planning, and event dispatch.
      service.py
      factory.py
      streams.py
      dispatch.py
      book_dispatch.py
      wallet_dispatch.py
      resolution_dispatch.py
      state.py
    tracked_markets.py # Condition-keyed union market registry.
    tracking/     # Wallet-discovery and paper-position registry workflows.
    streams/      # CLI stream contracts, construction, merging, and telemetry.
    followed_wallets/ # Follow contracts, position replay, and persistence.
    resolution.py # Gamma reconciliation and settlement ordering.
    resolution_state.py # Idempotent resolution ledger.
    persistence.py # Atomic JSON file primitive.
  polymarket/       # Installed as polybot.polymarket; does not shadow the SDK.
    gamma.py      # SDK-backed market discovery and future-slug retry.
    normalization/ # Market, book, and scalar SDK-payload normalization.
    data.py       # SDK-backed normalized current-position adapter.
    clob.py       # Official-client-backed CLOB adapter.
    wallet_activity/  # Wallet trades/activity stream and fallback.
      constants.py
    ws_market.py  # SDK-backed public market stream and depth state.
    ws_user.py    # SDK-backed authenticated user stream adapter.
    types.py      # Polymarket-specific normalized types.
  recording/        # Standalone market recorder and SQLite archive boundary.
  backtesting/      # Archive validation, state projection, virtual replay.
  performance/      # Shared valuation, CSV streams, and atomic run summary.
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

Every runtime also owns one `condition_id`-keyed tracked-market registry. It
unions configured markets, accepted wallet discoveries, and paper-position
interests into one SDK market subscription. New token pairs are batched at the
interval owned by `MARKET_ADDITION_BATCH_SECONDS` in
`polybot.cli.tracked_markets` before the current SDK handle is closed and
replaced; the pinned SDK cannot
mutate an open handle. Filtered stream rules remain strict allowlists, while
wallet-only and independent rules can discover new markets. Entries remain
until resolution.
The registry's admitted slugs are also supplied to `BotRunner` as runtime book
routes. This lets wallet-only discoveries reach `on_book` while keeping
filtered-rule allowlists strict at registry ingress. Resolution makes a
condition terminal for the runner lifetime and across restarts through the
resolution ledger: terminal conditions cannot be admitted again by configured
plans, wallet discoveries, or paper positions.

Resolution follows a separate non-fill path:

```text
MarketResolvedEvent or Gamma reconciliation
  -> MarketResolutionEvent
  -> idempotency check
  -> paper and followed-wallet settlement via `MarketResolutionEvent.payout_for`
  -> atomic persistence and registry removal
  -> observer MarketSettled event
  -> BaseBot.on_market_resolved(ctx, event)
```

The official market subscription enables custom lifecycle events. Gamma checks
all unresolved registry entries immediately after each subscription replacement
and at `RESOLUTION_RECONCILIATION_SECONDS` so a disconnect or SDK queue loss
cannot permanently hide a resolution.
Live resolution validation compares the WebSocket winner label with Gamma's
public outcome label, including arbitrary labels such as `Up`/`Down` or
candidate names, and preserves that opaque label end to end. Settlement is
label-agnostic: the winning token ID receives `1` and the other token receives
`0`.

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

## Historical Recording Boundary

Slice 9A records the public market data that the Slice 9B backtester replays.
It is a separate process from the paper runner and never dispatches
books to `BotRunner`, invokes strategy event hooks, or submits orders. In bot
selection mode it instantiates the factory only to call
`current_stream_rules()` and `next_stream_rules()` with a planning context whose
broker and wallet activity source reject every operation. Explicit
selection mode instead uses one or more static market slugs.

```text
bot current/next rules or repeated market slugs
  -> Gamma metadata resolution and future-slug retry
  -> current plus available next-market conditions
  -> one MarketRecordingFeed / official SDK handle per condition
  -> chronological package-owned events and BookDepthProjector state
  -> integrity monitor and book checkpoints
  -> local SQLite recording archive
```

`polybot.polymarket.recording_feed.MarketRecordingFeed` owns the SDK stream
boundary. Each per-condition `MarketCapture` is an async context manager and
iterator that emits package-owned book baseline/delta, public trade, tick-size,
and resolution values without exposing the SDK handle. A full book rebaselines
the shared `BookDepthProjector`; deltas before a baseline and identity-mismatched
events fail closed. `MarketCaptureDiagnostics.dropped_count` surfaces the
SDK's cumulative drop count to the integrity monitor.

A WebSocket resolution is committed before its condition handle closes. The
recorder then reconciles Gamma metadata and keeps retrying without the handle
until Gamma exposes final terminal metadata; the recorded WebSocket resolution
remains the authoritative event-order boundary during that lag.

The recorder uses the same Gamma adapter as the live paper runtime. For dynamic
bucket bots it resolves both the current and next plan and subscribes the next
market before rollover whenever Gamma has published it. Missing future slugs
are retried without blocking current-market capture. The recorder opens one
condition capture handle per resolved market; the SDK manager multiplexes those
handles on its shared connection. Adding the next market therefore does not
replace or interrupt an existing condition capture. An interrupted condition
handle is reopened separately and must receive fresh full-book baselines before
its incremental updates become replayable again.

One SQLite recording archive owns:

- recording sessions, including separate invocations appended with `--resume`;
- immutable market metadata revisions and their outcome-token identity;
- chronological recorded events with source time, local observed time, and a
  recorder-owned arrival order;
- full normalized book checkpoints from which replay can restart; and
- explicit coverage gaps scoped to known conditions/tokens, with resumed
  recorder downtime represented by a target-wide gap;
- an additive diagnostic capture-anomaly journal whose rows never consume the
  canonical replay sequence.

`RecordingArchive` is the write boundary; `RecordingReader` exposes stored
`RecordedEvent`, `BookCheckpoint`, `CoverageGapRecord`, `CaptureAnomalyRecord`,
and `SessionIntegrityStatus` values without leaking SQLite rows. Gap events use
the package-owned `CoverageGapPayload` contract, while the reader reports a
typed unavailable error for sessions that predate anomaly diagnostics. These
types preserve the artifact boundary consumed by Slice 9B.

`AsyncRecordingWriter` is the sole archive sequence owner. Every event,
checkpoint, gap mutation, and anomaly acknowledgement waits for a committed
SQLite transaction under WAL mode with `synchronous=FULL`. Already queued
events may share a group commit, while compound metadata-plus-resolution writes
and common two-token checkpoint pairs use one atomic archive call. The capture
coordinator therefore never treats an acknowledged row as an in-memory-only
buffer.

SQLite is an artifact format at the standalone package boundary. It does not
reuse `.bot-state/`, open the Polyfollow application database, run application
migrations, or become a shared runtime service. The required `--output` path is
owned by the caller and can be copied together with a bot experiment. A new run
uses non-overwriting creation and refuses an existing path. `--resume` instead
requires a schema-compatible archive with the exact stored target identity,
marks an unclosed prior session interrupted, continues the archive-wide arrival
order, and appends a new session. The offline interval becomes an explicit
target-wide gap; it is never presented as continuously observed time.

Replay opens the archive through `RecordingReader.for_replay()`. That factory
acquires and retains the exclusive writer lock, so an actively recording file
is refused and cannot change during replay or hashing. If the lock is free and
the latest session is still `active`, recovery marks it non-clean `incomplete`
at the latest committed event/checkpoint observation and checkpoints the WAL
before opening the immutable read transaction. A catchably failed session keeps
its `failed` diagnostic status but exposes the same durable-prefix boundary.
SQLite corruption, missing initial replay inputs, uncommitted work, and actual
coverage gaps remain unrecoverable.

The prediction-market WebSocket documents a timestamp on market events and a
hash on full books and price changes. It does not document a monotonic sequence,
hash lineage, missed-message replay, or resume cursor. The recorder therefore
orders equal-timestamp arrivals by its own append order and never treats a hash
as a sequence number. The source can split one logical price revision across
consecutive level-update frames. If projecting the first fragment would cross
the book, `MarketCapture` reads ahead for fragments with the same condition and
source timestamp. Every token/hash fingerprint from the first fragment must be
present and unchanged, while later fragments may add other token hashes. Added
tokens need not recur in every later fragment, but a recurring token cannot
change its first-seen hash. The capture preserves change order and records only
a transactionally valid combined delta. An incompatible fragment is quarantined
instead of being returned to the canonical stream. A mismatch, end of stream,
bounded read-ahead timeout, SDK drop-oldest counter increase, or combined
revision that remains crossed becomes a typed capture anomaly and capture
failure. A disconnect, condition-capture interruption, or other detected loss
opens a coverage gap.
For continuing capture, the gap closes only after every affected token has a
fresh source full-book baseline; price history or public trade history cannot
silently repair it. A terminal resolution may instead end the gap interval, but
the interval remains recorded and incomplete. Opening an additional condition
handle for a newly resolved next market is not itself a gap in already active
captures.

Capture anomalies are normalized package-owned diagnostics: failure kind,
revision fingerprints, quarantined fragments, before-failure projected books,
advertised best prices, SDK drop counters, elapsed time, and details. They live
in optional additive schema-v2 tables and never affect `events.sequence` or
Slice 9B input. New archives enable the feature at session start; resuming a
legacy schema-v2 archive creates the tables transactionally, while prior sessions
correctly report journal availability as unavailable. Every failed split-revision
recovery attempt is journaled even if a coverage gap is already open.

Fresh two-token baselines close a condition gap and immediately afterward
produce a common checkpoint pair at a fresh observation timestamp. For a
resumed target-wide gap, periodic checkpoints stay suppressed until every
affected condition recovers; the final closure writes every eligible market's
fresh checkpoint pair in one archive-wide batch. Periodic multi-market
checkpoints use the same batching rule. This prevents reverse task-resumption
order after a group commit from reusing an older observation timestamp. A
resolution may close bookkeeping but never fabricates a book checkpoint.

Integrity reporting uses the phrase `no detected gaps`, not
`exchange-complete`. A clean report means the recorder observed no known loss
between its checkpoints. It cannot prove that the upstream service emitted
every exchange event because the official stream provides no sequence or replay
contract. Recorded segments on either side of a gap remain inspectable. Slice
9B rejects an affecting gap but permits a selected clean subrange on either
side. A cleanly closed session and a gap-free interval are separate facts:
orderly shutdown does not erase an earlier integrity gap.

Slice 9A is deliberately market-only. Aggregated L2 depth and public market
lifecycle events do not reveal individual maker identities, FIFO queue
position, private order/fill state, or arbitrary-wallet activity. The archive
also excludes Binance, Chainlink, Pyth, sports scores, and other external
reference feeds. A bot whose decision depends on one of those sources cannot be
fully reproduced from this archive alone.

## Deterministic Replay Boundary

Slice 9B is selected through the existing bot CLI with `--backtest ARCHIVE`.
The backtest branch keeps `BotConfig.mode` at `paper`, runs headless by default,
and constructs archive-backed market and latest-book clients plus rejecting
wallet and position clients. It does not create SDK clients, open network
streams, or use live-runtime persistence under `.bot-state/`.

Before any strategy lifecycle or event hook runs, the replay service accepts
schema-v2 archives only, checks SQLite integrity, takes the inactive-archive
lease, resolves an unambiguous session, and validates the inclusive time and
market selection. Complete sessions are eligible in full; failed and recovered
sessions default to their last durable boundary and carry explicit
partial-source provenance. Metadata and baseline or checkpoint coverage must
exist, and no coverage gap may affect the selected interval. The reader
captures an immutable archive-wide sequence cutoff when it opens. SQLite rows
remain private to `RecordingReader`.

For a mid-session start, replay restores a same-observation checkpoint pair for
both outcome tokens, applies subsequent archive events without strategy
callbacks through the selected start, and then calls `on_start`. Metadata
revisions produce time-correct `Market` values; book baselines and deltas flow
through `BookDepthProjector`; resolutions become
`MarketResolutionEvent`. Archive-wide sequence is the authoritative event
order, including equal timestamps. `observed_at_ms` drives virtual time, while
source timestamps remain diagnostic data.

```text
schema-v2 RecordingReader selection
  -> metadata plus common token checkpoint pair
  -> ArchiveMarketState and BookDepthProjector
  -> ReplayClock and ReplayScheduler
  -> BotRunner and unchanged BaseBot hooks
  -> PaperBroker and unchanged OrderRequest/FillEvent contracts
  -> performance artifacts
```

`BotContext.clock` and `BotContext.rng` have system-backed defaults for normal
runs. Replay supplies a virtual clock plus separately derived deterministic RNG
streams for strategy decisions and broker jitter. The scheduler advances to
recorded observation times and refreshes dynamic stream rules from virtual
time. A recorded next market remains silent until its slug becomes current;
admission emits reconstructed bootstrap books, and previously admitted markets
remain available until their recorded resolution.

If a bot or broker sleeps during a callback, the scheduler consumes intervening
events without re-entering that callback. The fill-time latest-book cache still
advances, pending books coalesce to the newest value per token in live marker
order, and resolutions remain non-coalesced. A paper order therefore fills from
the virtual fill-time book. Latency beyond the inclusive replay end is rejected
as `backtest_data_exhausted`; replay never borrows later archive data.

Recorded resolution settles paper inventory at contractual `1`/`0`, emits
settlement telemetry, and invokes `on_market_resolved` afterward. `on_start`
and `on_stop` each run once. End-of-window positions are not force-liquidated.
Wallet rules, private-user inputs, maker queue assumptions, and external
reference dependencies fail with a typed backtest reason because Slice 9A did
not record those inputs.

## Performance Artifact Boundary

`polybot.performance` owns executable portfolio valuation shared with dashboard
state. Long positions mark at a fresh best bid and shorts at a fresh best ask.
When a current executable side is unavailable, the most recent executable mark
is exposed only as a labeled stale estimate; otherwise value remains
unavailable. Drawdown uses available marked equity and the summary labels stale
or missing history as estimated or incomplete.

Backtests always stream exact-decimal `equity.csv` and `orders.csv` rows to a
new results directory and atomically finalize `summary.json`. Sampling occurs
at start, each configured interval (one second by default), fills, settlements,
and end. The summary contains sanitized configuration, archive provenance and
selection, virtual duration, event/dispatch and trading totals, cash, equity,
gross/net PnL, return, fees, filled notional, drawdown, resolutions, open
positions, and valuation status. Existing result directories are refused, and
failed or interrupted runs remain explicitly partial. Output failures are fatal
to a backtest. A completed command prints the final metrics and result path.

Ordinary paper runs create the same artifacts only when `--results-dir` is
provided. The dashboard can remain active at the same time. Paper recording is
fail-open for trading and emits a visible warning if artifact output later
fails; without `--results-dir`, normal paper behavior is unchanged.

## Terminal Observability

The CLI enables its terminal dashboard by default and accepts `--no-dashboard`
for headless operation. It may attach a fail-open `RuntimeObserver` without exposing it to bots,
adapters, or paper execution. The observer receives lifecycle, stream,
dispatch, order, fill, settlement, portfolio, and bot-activity events. `BotContext.activity`
is an async, fail-open framework sink; bots use it to emit a message with an
`ActivitySeverity` without importing Dashboard or CLI types. Its Rich dashboard projects them
in memory, uses `asciichartpy` for fixed-scale price and variance-padded
executable-wallet-value charts. The price chart is taller for clearer y-axis
resolution. Completed buys and sells are marked directly on the traded token's
line in wallet-value green and red, respectively. Press `z` to narrow the
displayed time window,
`x` to widen it, and `r` to reset it. Zooming resamples history into a fixed
chart width, and the visible range's start and end times are shown below the
plots. Press `v` to switch between the market-price view and the followed-wallet
view. The followed-wallet view is a trade-time event raster with one lane per
configured or observed wallet: green is buy, red is sell, yellow is a mixed
bucket, and `·`/`●`/`◆` show relative aggregate notional. Events skipped by the
runner are dimmed. `j` and `k` page wallet lanes when the terminal cannot show
all of them. Press `m` to show or hide blue market events in Activity; they are
hidden by default. It retains separate bounded dashboard-only event histories
so market noise cannot evict order, fill, or runtime activity. Order and fill
rows use the market/outcome token label when market metadata has reached the
dashboard. It uses the
same selected time range as the market chart. These dashboard-only controls
never affect bot execution.
Expired market data retains its last plotted
value in a dimmed series rather than being treated as a current quote. The
status row continues to use fresh executable marks where they exist. If a held
position's book disappears, including while the market awaits resolution, it
instead shows a clearly marked stale estimate using that position's last
executable unit mark, multiplied by its current size. A fill refreshes that
mark when the current book can execute the updated position. Settlement is the
only event that converts a position to its contractual `1`/`0` cash payout.
The dashboard renders independently of bot execution. During startup, its Activity
panel also reports fail-open wallet and market bootstrap progress as
completed/total counters while configured markets and followed-wallet positions
are loaded.
The market-price chart plots up to twenty tokens and keeps its admitted selection
stable when more books are tracked than can be plotted. Overflow books still
update runtime state and the activity ticker, but repeated union snapshots
cannot rotate the visible lines or erase their histories.
On successful settlement, both outcome tokens are removed from chart state,
legend labels, and activity ticker rather than retaining a final payout series.
The status row shows a deduplicated, run-lifetime `resolved N` count. No
separate tracked-markets panel is introduced.

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
Bootstrap progress is attached at this same boundary by
`polybot.cli.observability.bootstrap.BootstrapProgressAdapter`, which wraps the
market-resolution and followed-wallet ports without adding observer calls to
the core workflows.

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

    async def on_market_resolved(self, ctx: BotContext, event: MarketResolutionEvent) -> None:
        ...
```

Only override hooks that are needed. Do not put SDK clients, HTTP clients,
signing, fee math, or simulation details in bot classes.

Framework-aware strategy code should also obtain time and randomness from
`ctx.clock` and `ctx.rng`. Their normal defaults use the system clock and a
process RNG; deterministic replay replaces them without changing bot hooks.

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

Wallet bootstrap follows the same distinction. An independent wallet selector
loads all current positions. A filtered selector resolves its rule market slugs
to condition IDs and loads only those markets through the Data API position
filter; the normalized result is checked against the slug allowlist again before
it can affect follow state or market tracking.

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

Paper runs write no performance files unless the CLI receives `--results-dir`.

### Backtest

Backtesting is the paper execution contract driven by a selected recording
archive and a deterministic virtual clock. It is requested with `--backtest`,
rejects live mode, does not perform network or persistent live-runtime I/O, and
always writes a performance result directory.

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
process lifetime. CLI paper runs additionally persist claims across restarts in
an atomic file-backed store; direct broker users may inject their own store.

## Followed-Wallet Accounting

When a wallet is first followed, only its current open Data API positions are
loaded. Each position receives its baseline at the first valid executable bid,
so tracked gross PnL begins at zero; an unsafe or unavailable mark leaves PnL
unavailable without preventing market tracking. Closed history and Polymarket
lifetime PnL are not imported.

Post-follow movements replay by `(trade_timestamp_ms, source_key)`. Buys update
weighted basis, sells realize against basis, and resolution realizes remaining
value at `1` or `0`. Fees are never inferred, so this accounting is explicitly
gross. Removing and later re-adding a wallet creates a new persisted follow
epoch.

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
