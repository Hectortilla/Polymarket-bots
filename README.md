# Custom Polymarket Bots

This package is an isolated workspace for custom Polymarket bots. It does not
import from `backend/app` and it should not be wired into the FastAPI app,
database models, workers, or frontend unless a future task explicitly changes
that boundary.

The package shares only:

- The backend Python environment and dependencies.
- Process environment variables from `.env`.
- The repository test runner.

Start with:

- `docs/architecture.md`
- `docs/bot-author-guide.md`
- `docs/api-notes.md`
- `docs/implementation-plan.md`

The current package has the Slice 1 contract layer, Slice 2 paper fill engine,
Slice 3 public market-data adapters, Slice 4 wallet activity inputs, Slice 5
paper runner CLI, Slice 9A historical market recorder and local trim
maintenance, Slice 9B deterministic archive backtester and performance
artifacts, Slice 10 terminal dashboard, and Slice 11 dynamic market tracking and
resolution processing. The
dashboard has market-price and followed-wallet timeline views; press `v` to
switch between them. Gamma
discovery, CLOB snapshots, market WebSocket books, and Data API wallet reads
use the pinned unified Polymarket SDK and normalize SDK models at the
`polybot.polymarket` boundary. Authenticated runtime adapters remain intentionally
unimplemented until their later slices; no arbitrary-wallet trade stream is
bundled because the pinned SDK does not provide one.

The paper runtime maintains one condition-keyed union of configured markets,
accepted followed-wallet discoveries, and paper positions. Dynamically
discovered markets remain subscribed until resolution. Resolution events settle
paper and followed-wallet positions at contractual `1`/`0` payouts, persist the
terminal condition before `BaseBot.on_market_resolved()` runs, remove it from
the active subscription, and prevent future re-admission after restart.

Future Polymarket integrations must use an official Polymarket Python SDK or
client wherever it supports the required capability. The unified
`polymarket-client` async SDK is the default for this event-driven framework;
specialized official clients such as `py-clob-client-v2` are the next choice.
Direct HTTP, WebSocket, authentication, signing, or order serialization is
allowed only for a documented capability gap in the official libraries. See
`docs/api-notes.md` for the dependency-selection rule and current official
packages.

The target v1 is event-driven from the start. Paper and live modes must consume
the same market-book, wallet-trade, resolution, and fill event shapes so paper
behavior stays close to live behavior.

The live framework is performance-first. WebSocket/streaming sources are the
target live paths for fast-changing data. REST polling is for bootstrap,
metadata, reconnect backfill, reconciliation, or explicit degraded fallback.

Bots can operate on one market, many static market slugs, or dynamic market
slugs generated from context such as time buckets. The runner routes
market-tagged events only to bots whose current market set includes that slug.

Wallet-following and market-wide trade streams are declared together through
`BOT_STREAM_RULES`. Rules express filtered wallet-and-market streams or
independent wallet-or-market streams; the runner applies the declared relation
before dispatching normalized wallet trades.

Runner dispatch returns a typed `DispatchOutcome`. Rejected events carry a
stable `DispatchSkipReason` instead of collapsing every skip into a boolean.

The CLI enables the dashboard by default. Use `--no-dashboard` for headless
operation:

Bots can add typed informational rows to the Dashboard Activity panel with
`await ctx.activity.emit(message, severity=ActivitySeverity.INFO)`. These
events also reach custom runtime observers during headless runs.

During startup, the Activity panel shows compact wallet and market bootstrap
progress counters while configured markets and followed-wallet positions are
loaded.

```sh
BOT_MODE=paper \
BOT_MAX_ORDER_SIZE=5 \
uv run python -m polybot.cli --bot polybot.my_bot:create
```

`polybot.my_bot:create` is the default BTC five-minute momentum factory. Bot
factories may accept no arguments or one validated `BotConfig`; the public type
is `polybot.framework.factories.BotFactory`. Programmatic integrations can run
a bot through `polybot.runtime.run_bot`.

## Historical Market Recording

Polymarket exposes current L2 books, historical token-price points, and public
trade rows through different API surfaces. It does not document a public
archive of historical L2 books. Slice 9A therefore records the live public
market stream into a local SQLite recording archive that Slice 9B can replay.

Slice 9A's standalone command is `python -m polybot.recording`. Select either a
bot factory, whose current and
next market rules provide the recording topology, or one or more explicit
market slugs. The two selection modes are mutually exclusive:

```sh
uv run python -m polybot.recording \
  --market-slug btc-updown-5m-1767225600 \
  --market-slug eth-updown-5m-1767225600 \
  --duration 2h
```

```sh
uv run python -m polybot.recording \
  --bot polybot.examples.example_btc_five_minute_momentum:create \
  --duration 10d
```

Without `--output`, recordings are written under
`recordings/<local-timestamp>/markets.sqlite3` (or a descriptive bot/market
filename). The timestamped directory separates runs. Use an explicit
`--output` path with `--resume` to append to an existing archive.

Omit `--duration` to run until graceful interruption. Use `--resume` to append
another recording session to an existing compatible archive with the same
target selection. A normal run refuses to overwrite an existing output, and
`--resume` records the offline interval as a coverage gap. The recorder also
accepts the runner's existing `--dotenv` and `--override` options when loading a
bot factory.

The archive contains sessions, market metadata revisions, chronological
recorded events, full book checkpoints, explicit coverage gaps, and (for newly
created or resumed archives) a non-replayable capture-anomaly journal. An archive
can report `no detected gaps`; it cannot prove exchange-complete capture because
the official prediction-market stream documents timestamps and book hashes but
no sequence number, replay cursor, or resume protocol.
Every recorder mutation is acknowledged only after its SQLite transaction has
committed with WAL mode and full synchronization. Each market capture keeps a
bounded pipeline of unacknowledged events so it can continue draining SDK
bursts while the single writer commits; global sequence numbers are assigned
when events enter that pipeline, and no event is reported durable early.
Concurrently queued market events may share one commit,
metadata-plus-resolution writes and common two-token checkpoints are atomic,
periodic and recovery checkpoints across markets share one fresh-timestamp
batch, and shutdown drains the writer before sealing the session.

SIGINT and SIGTERM request a clean shutdown, but process kills, power loss, and
similar failures cannot be caught. The committed prefix still remains usable.
Replay takes the archive's exclusive writer lock, refuses a recorder that is
still running, converts an abandoned active session to non-clean `incomplete`
at its last durable event/checkpoint boundary, and checkpoints the surviving
WAL before hashing or replay. Failed and recovered sessions are labeled partial
sources. Do not delete or separate a crash-surviving `-wal` sidecar before this
recovery; it is part of the SQLite archive until checkpointed.
Price revisions split across consecutive same-timestamp/hash level-update frames
are combined transactionally when an intermediate fragment would otherwise look
crossed. A continuation may add hashes for tokens not present in the first
fragment, but every original token/hash must remain present and unchanged.
Added tokens may be omitted from a later fragment; if they reappear, their
first-seen hash must still match. Incomplete, mismatched, dropped, or
still-crossed revisions are quarantined, journaled, and recorded as gaps rather
than entering replay data. Once fresh full books recover a gap, the recorder
writes an immediate common checkpoint pair so the clean post-gap range can be
selected without waiting for the periodic checkpoint.
The upstream stream has no replay cursor, so the recorder can reduce and explain
gaps but cannot guarantee that they never occur.

To replace a gapped archive with its longest clean, archive-level all-market
interval, run the local trim utility:

```sh
uv run python -m polybot.recording.trim recordings/capture.sqlite3
```

The sole session is selected by default; archives with multiple sessions require
`--session ID`. Run `--dry-run` first to review the chosen interval without
replacing the archive. A normal run prints that interval before it begins the
export. Coverage gaps are half-open intervals: the clean range after a
closed gap may begin at its recorded end, while the range before it must end
before its start. A selected session with no relevant gaps retains its full
event-bearing replayable interval. A fresh common recovery checkpoint recorded
at or immediately after a gap's end can bootstrap the clean suffix even when
its two recovery baselines straddle the gap boundary; in the latter case the
suffix starts at the checkpoint. The replacement keeps the metadata and book
bootstrap needed to make that range self-contained, and discards all other
source sessions and times rather than pretending to repair missing data.

Trimming refuses an active recorder, builds and validates a temporary archive in
the same directory, retains the original as a hard-linked
`ARCHIVE.pre-trim` backup by default (for example,
`capture.sqlite3.pre-trim`), and atomically replaces the requested path only
after validation. If that backup path already exists, the command refuses to
replace the archive; move the existing backup aside or deliberately pass
`--no-backup`. The operation is entirely local and performs no Polymarket or
other network requests.

Slice 9A is market-only. It does not record arbitrary-wallet activity, private
orders or fills, maker identities or queue position, or Binance, Chainlink,
Pyth, or other external reference feeds. Strategies that require those inputs
need additional future recording slices before their results can be reproduced.
The SQLite file is a local artifact, not an application database or a dependency
on the Polyfollow app.

## Backtesting and Performance Results

Run the same bot factory through the normal CLI with `--backtest` to replace all
live inputs with one schema-v2 recording archive:

```sh
BOT_MODE=paper \
uv run python -m polybot.cli \
  --bot polybot.examples.example_btc_five_minute_momentum:create \
  --backtest recordings/btc-five-minute.sqlite \
  --seed 0
```

Replay is headless by default and never constructs a Polymarket SDK client,
performs a network read, or touches `.bot-state/`. `BOT_MODE=live` is rejected.
The only replay inputs are metadata revisions, books, and lifecycle events from
the selected archive interval. A deterministic virtual clock drives event
delivery, strategy sleeps, paper latency, and broker jitter, so multi-day data
runs as quickly as local SQLite reads and bot computation permit.

By default the sole session, all its markets, and its replayable range are
selected. Use `--session ID` when an archive has multiple sessions,
inclusive `--start-ms` and `--end-ms` for a subrange, and repeated
`--market-slug` values for a subset. `--report-interval-ms` defaults to `1000`.
Replay refuses an archive whose recorder lock is still held, unsupported
schemas, missing metadata/baselines, invalid ranges, and coverage gaps that
affect the selected interval. Once the writer lock is released, abandoned and
failed sessions default to their last committed boundary and are reported as
partial recording sources. A clean subrange on either side of a real coverage
gap remains usable; recovery never guesses across that gap.

After `polybot.recording.trim` succeeds, the replacement archive contains one
self-contained clean interval, so ordinary backtest defaults can select it
without `--session`, `--start-ms`, or `--end-ms`.

Every backtest creates a new result directory; pass `--results-dir PATH` to
choose it, or let the CLI generate a unique path. Existing directories are
never overwritten. The directory contains:

- `summary.json`: sanitized run/archive identity, selection, seed, event and
  dispatch counts, cash/equity/PnL/return/fees/drawdown metrics, order/fill/
  rejection/resolution totals, open positions, and valuation completeness;
- `equity.csv`: exact-decimal start, interval, fill, settlement, and end samples
  ready for plotting; and
- `orders.csv`: each submission and completion with requested and filled values,
  rejection details, strategy reason, and source ID.

Open positions are not force-liquidated at the end. Fresh executable marks are
reported when available; last executable estimates are explicitly stale, and
unavailable values remain null. Failed or interrupted replays retain partial
CSV output and an explicit partial status when finalization can complete.
On completion, the CLI also prints a compact performance summary and the result
directory path.

The same performance artifacts are opt-in for an ordinary paper run:

```sh
BOT_MODE=paper \
uv run python -m polybot.cli \
  --bot polybot.my_bot:create \
  --results-dir results/paper-run
```

Without `--results-dir`, ordinary paper behavior is unchanged and the dashboard
remains enabled by default. With it, dashboard rendering and performance
recording can run together.

For reproducible bots, read time from `ctx.clock.now_ms()`, await
`ctx.clock.sleep(...)`, and draw randomness from `ctx.rng`. Direct wall-clock
reads, `asyncio.sleep`, external I/O, and private randomness are outside the
framework's determinism guarantee.

The paper-only BTC five-minute momentum example continuously rolls across the
canonical `btc-updown-5m-<bucket-start>` markets:

```sh
BOT_MODE=paper \
BOT_MAX_ORDER_SIZE=5 \
uv run python -m polybot.cli \
  --bot polybot.examples.example_btc_five_minute_momentum:create
```

It uses only normalized Up/Down order books: paired microprices, fast/slow EMA
trend, rate-of-change, an adaptive noise floor, and top-of-book imbalance. It
holds at most one outcome and has spread, depth, price, time-window, stop,
target, reversal, cooldown, and pre-expiry guards. See
`docs/bot-author-guide.md` for the full strategy explanation. Keep it in paper
mode until its parameters have been evaluated on representative recorded data;
unit tests validate deterministic behavior, not profitability.
