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
- Use `ctx.clock` for current time and sleeps.
- Use `ctx.rng` for strategy randomness.
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

Expose a CLI bot as a `module:create` factory. A factory may take no arguments,
or accept the already-validated `BotConfig` when construction depends on stream
rules or other framework configuration. The discoverable typing contract is
`polybot.framework.factories.BotFactory`.

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

For replayable strategy behavior, do not read the wall clock directly, call
`asyncio.sleep`, or create private entropy. Use `ctx.clock.now_ms()`, await
`ctx.clock.sleep(...)`, and draw from `ctx.rng`. The framework can reproduce its
own scheduling and paper execution for a fixed archive, selection, config, and
seed; external I/O and code that bypasses these context contracts cannot be
made deterministic by the runner.

## Recording Markets For Backtests

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
  --duration 10d
```

Record a fixed set instead by repeating `--market-slug`:

```sh
uv run python -m polybot.recording \
  --market-slug btc-updown-5m-1767225600 \
  --market-slug eth-updown-5m-1767225600 \
  --duration 2h
```

`--bot` and `--market-slug` are mutually exclusive. When omitted, `--output`
defaults to `recordings/<local-timestamp>/<description>.sqlite3`, with simple
target-labelled filenames. `--duration` accepts a positive integer followed by
`s`, `m`, `h`, or `d`. Without a duration the process runs until graceful
interruption. `--resume`
requires an existing compatible SQLite recording archive with the same target
selection and appends a new session. Without `--resume`, the recorder refuses to
overwrite an existing output. A resumed run preserves the previous session and
records the offline interval as a coverage gap. `--dotenv` and `--override` have
their normal runner meanings when constructing the bot.

Records, anomaly diagnostics, gap changes, and checkpoints return to the
capture coordinator only after their SQLite transaction commits. Concurrent
market events may be group-committed. Each capture may have a bounded set of
unacknowledged events in the writer queue so SDK bursts are drained without
waiting for one disk synchronization per message; sequence ownership remains
with the writer and each completion still means its transaction committed.
Metadata-plus-resolution writes and common two-token checkpoints are stored
atomically. This makes the committed prefix independent of final shutdown.
Periodic and recovery checkpoints across markets also use one fresh-timestamp
batch, so concurrent acknowledgements cannot make checkpoint observation time
move backward.

An uncatchable process kill can still leave the latest session marked `active`
and committed rows in SQLite's `-wal` sidecar. Backtest replay acquires the
writer lock, refuses a recorder that is still running, seals an abandoned
session as non-clean `incomplete` at its last committed event/checkpoint, and
checkpoints the WAL. Keep the main archive and any crash-surviving SQLite
sidecars together until that recovery runs.

Dynamic bots should keep current and next market generation deterministic. The
recorder resolves both plans, subscribes to the current market, and
pre-subscribes an available next market before rollover. A not-yet-published
next slug is normal and is retried without interrupting the current stream.

Before evaluating a strategy, inspect the archive:

```sh
uv run python -m polybot.recording.inspect recordings/capture.sqlite3
```

The read-only report includes total captured event time, session status, unique
market count and per-market spans, event-kind counts, checkpoints, detected and
open gaps, capture anomalies, archive size, and target/schema provenance. It can
take a point-in-time snapshot of an active recording, but the recorder must stop
before replay. `no detected gaps` means no loss was observed by the recorder; it
does not mean exchange-complete because Polymarket documents no market-stream
sequence or resume cursor. The report is orientation rather than a replayability
certificate: Slice 9B still validates metadata, book bootstrap, range, and
coverage. Its default strict policy refuses any gap affecting the selected
interval, while Slice 9B.1 requires an explicit approximate blackout policy to
continue around one. A clean subrange before or after a gap remains eligible in
strict mode.
The recorder transactionally combines split same-timestamp/hash price revisions
that would be crossed only in their intermediate form. It accepts a continuation
only when every token/hash named by the first fragment is still present and
unchanged; extra token hashes are allowed because one logical revision can be
split by token. An added token may be absent from a later fragment, but its hash
cannot change if that token appears again. A mismatched, timed-out, dropped, or
still-invalid revision is quarantined and remains a real coverage gap.

New and resumed schema-v2 archives also contain a diagnostic-only capture
anomaly journal. It records the failure kind, normalized quarantined fragments,
revision fingerprints, projected/advertised top of book, SDK drop counters, and
elapsed recovery time without consuming replay sequence numbers. Sessions made
before the journal was activated report diagnostics as unavailable rather than
claiming zero anomalies. These rows help explain a gap but never reconstruct its
missing data. Strict replay still rejects it. Approximate blackout replay may
preserve the surrounding state without treating those diagnostic rows as market
data. Recovery still requires fresh full-book baselines for both outcome tokens.
The recorder writes a common checkpoint immediately when that recovery boundary
closes (and for every affected market when a resumed target-wide gap finally
closes), making the clean range after the gap usable promptly.

Known gaps cannot always be prevented: the public stream has no documented
sequence, replay, or resume mechanism. The recorder detects SDK queue drops and
uses bounded conservative reassembly, then fails closed and resubscribes when it
cannot prove continuity. It never fills a missing interval from REST history.

When retaining only the largest usable portion is preferable to passing a
manual range on every backtest, trim the archive locally:

```sh
uv run python -m polybot.recording.trim recordings/capture.sqlite3
```

The utility considers all markets in one source session and chooses its longest
archive-level clean interval. It selects the sole session automatically and
requires `--session ID` when the archive contains more than one. Gaps are
half-open: a post-gap range can start at the gap's recorded end, while a pre-gap
range ends before its start. Run `--dry-run` first to review the selection
without replacing the archive; a normal run prints the same plan before export.
Selecting a session with no relevant gaps retains that session's full
event-bearing replayable interval, which can also extract it from a multi-session
file. A common recovery checkpoint recorded at or immediately
after the gap end can initialize the suffix when its fresh token baselines
straddle that boundary; the selected suffix then starts at the checkpoint.

The replacement is a self-contained replay source: required metadata and book
bootstrap state are retained, while other times and source sessions are
discarded. This does not repair or infer any missing book data. The command
refuses an archive held by a recorder, builds and validates a same-directory
temporary archive, retains the original as a hard-linked
`ARCHIVE.pre-trim` backup by default (for example,
`capture.sqlite3.pre-trim`), and then atomically replaces the requested path. An
existing backup at that exact path makes the command refuse replacement; move it
aside or use `--no-backup` only when the retained original is not wanted. No SDK
client or network source is opened.

The Slice 9A archive contains public market metadata and aggregated book data
only. It cannot reproduce wallet-following hooks, private order/fill state,
individual maker priority, or decisions based on an external reference feed.
For example, the BTC five-minute momentum example is compatible because it uses
only its two normalized outcome books. A bot that reads Binance or Chainlink
prices needs those feeds recorded by a future input slice as well.

## Running A Backtest

Use the regular bot CLI and add `--backtest`:

```sh
BOT_MODE=paper \
uv run python -m polybot.cli \
  --bot polybot.examples.example_btc_five_minute_momentum:create \
  --backtest recordings/btc-five-minute.sqlite \
  --seed 0
```

A replay uses the same bot factory, hooks, `BotRunner`, paper broker, order
requests, and fill events as a paper run. It is headless by default and reads
only the selected archive: no SDK/network client is constructed and
`.bot-state/` is not read or written. `BOT_MODE=live`, wallet stream rules,
private-user inputs, maker-queue assumptions, and dependencies on unrecorded
external reference feeds are rejected.

The default selection is all markets and the full sole session. If the
archive contains multiple sessions, choose one with `--session ID`. Narrow the
inclusive interval with `--start-ms` and `--end-ms`, or repeat
`--market-slug SLUG` to choose a subset. The recorder must no longer hold the
archive lock. Complete sessions are eligible in full. Failed and abandoned
sessions default to their last durable event/checkpoint boundary, are labeled
as partial recording sources, and may also be narrowed explicitly. The range
must have time-correct metadata and an initial common book baseline/checkpoint
for both outcome tokens. The default `--gap-policy strict` rejects an affecting
coverage gap. Recovery cannot make a prefix replayable if the process died
before those minimum inputs were committed.

Use `--gap-policy blackout` only when keeping the continuous strategy and
portfolio state around known gaps is more useful than a strictly clean replay:

```sh
BOT_MODE=paper \
uv run python -m polybot.cli \
  --bot polybot.examples.example_btc_five_minute_momentum:create \
  --backtest recordings/btc-five-minute.sqlite \
  --gap-policy blackout
```

Blackout mode is approximate, not interpolation. At the exact recorded gap
start it removes the affected market books and any pending callbacks and marks
affected positions unavailable. Virtual time, strategy state, the paper
portfolio, and unrelated markets continue. `ctx.books.latest(token_id)` returns
no book for an affected token and the bot receives no affected `on_book`
callback until real fresh full-book baselines for both outcomes establish one
post-gap subscription generation. Open gaps remain unavailable through the
selected end. Bot code should treat this as missing input, not as a price move
or zero liquidity.

The broker rejects an affected order submitted inside a blackout or whose
simulated latency crosses one with `backtest_coverage_gap`. This remains true if
the market recovers before the nominal fill time, because the unknown interval
could have changed execution. Orders for unaffected markets continue normally.
Blackout never creates a price, depth level, spread, trade, or fill and never
modifies the source archive.

A successfully trimmed archive has one self-contained clean interval and can be
passed to `--backtest` without the source `--session`, `--start-ms`, or
`--end-ms` selection.

Replay uses archive arrival sequence as authoritative order and
`observed_at_ms` as virtual time. Dynamic `current_stream_rules()` and
`next_stream_rules()` are recalculated from that time. A pre-recorded next
market produces no callback until it becomes current, when the runtime emits
reconstructed bootstrap books; an admitted prior market remains available
until its recorded resolution. Strategy and broker sleeps consume intervening
events without callback re-entry, and pending books coalesce per token before
the next callback. The fill therefore uses the book that exists at virtual fill
time when that market has continuous coverage. A sleep extending beyond the
selected end produces the stable `backtest_data_exhausted` rejection; a broker
latency interval crossing an affecting blackout produces
`backtest_coverage_gap`.

Every backtest writes `summary.json`, `equity.csv`, and `orders.csv`. Select a
new directory with `--results-dir`; otherwise a unique default is created.
Existing directories are refused. `--report-interval-ms` controls periodic
equity samples and defaults to `1000`. `summary.json` includes sanitized config
and archive identity, the exact selection and seed, event/dispatch/trading
counts, PnL/return/fee/drawdown metrics, open positions, and valuation quality.
CSV decimals are exact strings suitable for plotting or lossless decimal
parsing. Start, fill, settlement, interval, and end samples can share a
timestamp but never move backward. The command prints a compact final summary,
the result directory, and a static full-run net-PnL chart when replay completes.
The chart uses the complete `equity.csv` time range and resamples it only to fit
the terminal width; fresh values are green and stale or unavailable spans are
dim green. A compact header includes fills, orders, rejections, resolutions,
net PnL, return, drawdown, fees, initial/final equity, filled notional, and
valuation quality. For every run, selection
provenance records `gap_policy`; blackout runs also record sorted coverage-gap
IDs, count, clipped half-open union duration, open count, and affected position
token IDs. Metrics include the number of orders rejected for coverage gaps, and
the CLI prints an explicit approximate-results warning for blackout runs.

Replay settles recorded resolutions at contractual `1`/`0` before
`on_market_resolved` runs. It does not liquidate an open end-of-window position:
fresh executable value, a labeled last-executable stale estimate, or a null
unavailable value is reported instead. Interrupted or failed runs retain an
explicit partial status when summary finalization succeeds.

Render a finalized backtest result again without loading a bot or archive:

```sh
uv run python -m polybot.cli.performance_chart results/backtest-run
```

The argument is the result directory containing `summary.json` and
`equity.csv`. The local command validates both artifacts, labels partial runs,
does not require an interactive terminal, and performs no network access.

To collect the same performance files during an ordinary paper run, pass only
`--results-dir`:

```sh
BOT_MODE=paper \
uv run python -m polybot.cli \
  --bot polybot.my_bot:create \
  --results-dir results/paper-experiment
```

Normal paper runs create no artifacts without that flag. The dashboard remains
enabled by default and can operate alongside performance recording;
performance-output failures warn visibly but do not stop trading.

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
`polybot.cli.observability.observer.RuntimeObserver` to
`polybot.runtime.run_bot()`. Observers
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
from polybot.framework.markets import market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule


class FiveMinuteBot(BaseBot):
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (StreamRule(StreamRelation.INDEPENDENT, (self._slug(now_ms, 0),)),)

    async def next_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (StreamRule(StreamRelation.INDEPENDENT, (self._slug(now_ms, 1),)),)

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
Unit tests still do not establish a live trading edge or expected return. Use
Slice 9B against representative Slice 9A archives to measure historical paper
performance under the recorded market inputs.

### Dynamic wallet-filtered example

`polybot.examples.example_dynamic_random_hold_wallet_filter_copy:create` runs
the dynamic random-hold wallet-filter example. Its factory reads followed
wallets from the standard validated `BOT_STREAM_RULES` config, while the bot
generates market slugs from the current time bucket:

```dotenv
BOT_STREAM_RULES='[{"relation":"independent","market_slugs":[],"wallet_addresses":["0x0000000000000000000000000000000000000001","0x0000000000000000000000000000000000000002"]}]'
```

Each current and next bucket is then declared as a `filtered` stream rule for
that complete wallet list. The bot fails closed at construction time when no
wallet appears in the configured rules. Its copied positions are tracked by
normalized wallet, condition, and token, so a sell from one followed wallet can
only reduce a position opened from that same wallet's buy; sells for untracked
inventory are ignored.

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
