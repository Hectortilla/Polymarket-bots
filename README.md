# Custom Polymarket Bots

This standalone repository contains the `polybot` bot framework, a private
paper-only API and worker, and a Svelte frontend. It has no dependency on the
parent Polyfollow application, database, workers, frontend, or configuration.
The `api` package may import `polybot`; the framework does not import the API.

## Repository Layout

```text
backend/
  src/polybot/          # Independent bot framework, CLI, recording, and backtesting.
  src/api/              # Application backend: HTTP, persistence, and worker.
    http/               # FastAPI application and routes.
    execution/worker/   # Background paper-run lifecycle.
  tests/                # Python suite, including scripts and cross-language checks.
  contracts/openapi/    # Generated API schema consumed by the frontend generator.
  contracts/fixtures/   # Shared Python/TypeScript contract scenarios.
  migrations/           # Alembic database migrations.
  alembic.ini
frontend/               # Svelte application, generated API client, and UI tests.
scripts/                # Wallet analysis and database maintenance commands.
docs/                   # Architecture, author guides, and implementation plans.
data/                   # Git-ignored local outputs.
  recordings/
  backtests/
  wallet-analysis/
  bot-state/
pyproject.toml          # Shared Python dependencies, packaging, and test configuration.
uv.lock
```

Run Python commands from the repository root. The root `.env` supplies local
configuration, and `uv sync --extra dev` installs both backend packages and the
scripts into one environment. Frontend commands run from `frontend/`.
Generated build products, virtual environments, and caches are not source folders.

The API and worker use these entrypoints (with their database and Redis settings
configured in `.env`):

```sh
uv run uvicorn api.http.app:app --env-file .env --reload --no-proxy-headers
uv run --env-file .env taskiq worker api.execution.taskiq_app:broker --workers 1 --max-async-tasks 4
```

Restart API and worker processes together after changing their Python package
paths; drain an old worker queue before switching to the renamed task entrypoint.
The VS Code development-stack configuration uses these same modules.

Regenerate the backend schema from the root, then regenerate its frontend client:

```sh
uv run python -m api.http.openapi
npm --prefix frontend run generate
```

Alembic configuration lives at `backend/alembic.ini`; direct Alembic commands
must select it with `-c backend/alembic.ini`. The database recreation script
selects it automatically. Migration paths resolve relative to the configuration
file, independent of the current working directory.

Existing local outputs belong under `data/`: recordings, backtests, wallet
analysis, and retained bot-state files each have their own directory. Explicit
CLI output paths and `DEFAULT_RECORDINGS_DIR` overrides remain supported.
Historical result contents and provenance are preserved when moving directories.

Verify the repository from its root:

```sh
uv run pytest
npm --prefix frontend run generate:check
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run build
uv build
```

PostgreSQL and Redis integration tests require `POLYBOT_TEST_POSTGRES_URL` and
`POLYBOT_TEST_REDIS_URL` pointing to disposable test services; the database tests
rebuild their schema. Without those settings the service-dependent tests skip.

## Local accounts and private access

Set `POLYBOT_AUTH_ORIGIN` in `.env` to the exact browser origin, for example
`http://localhost:5173`, and set `POLYBOT_AUTH_ALLOW_HTTP=true` only for local HTTP
development. Start the frontend with `npm --prefix frontend run dev`, then open
`/register` to create your account. No email service is needed. Passwords contain
15–128 characters; emails are case-insensitive with dots and plus-tags retained.
There is no password recovery, account editing, or email verification in this MVP.

Sessions expire after 7 days; signing out revokes the current session and
closes browser streams. Already-authorized background runs continue. Each account
sees only its own bots, templates and run history. Code-owned starter graphs remain
available to every signed-in account. The full policy lives in
[the identity architecture](docs/web-control-plane-architecture.md#slice-15-identity-and-authorization).

Migration 0005 requires empty pre-auth resource tables. The September 8 development
reset was explicitly approved. On a disposable pre-auth installation only, use:

```sh
uv run --env-file .env python -m scripts.recreate_control_plane_database
```

This command deletes the configured database, including all bots, runs and accounts.
Once accounts exist, preserve data through explicit forward migrations and backups;
do not rewrite migration history or silently reset the database. Downgrading 0005
removes identity and cannot represent duplicate template names across users.

Keep API and frontend on one origin and retain the private network boundary.
HTTPS deployments must use `POLYBOT_AUTH_ALLOW_HTTP=false`; cookies are then Secure.
Run Uvicorn with `--no-proxy-headers` locally. Behind a controlled reverse proxy,
explicitly allow only its address and overwrite incoming forwarded headers; never
trust arbitrary forwarded IPs. PostgreSQL and Redis must remain private. Redis
availability is required for signup/login, including invalid attempts. No public
deployment is authorized by this slice.

Browser acceptance uses real PostgreSQL, Redis, API sessions and Chromium. Only
market discovery and execution delivery are fixtures; graph editing, ownership,
persistence, SSE and stop transitions use application code. After installing
Chromium with `npm --prefix frontend exec -- playwright install chromium`, run:

```sh
POLYBOT_BROWSER_POSTGRES_URL=postgresql://polybot:polybot@127.0.0.1:55432/polybot_browser_test \
POLYBOT_BROWSER_REDIS_URL=redis://127.0.0.1:56379/15 \
npm --prefix frontend run test:e2e
```

The browser harness recreates only the explicitly configured local `*_test`
database and requires loopback Redis with an explicit port and nonzero database.
Throttle cleanup deletes only authentication keys. Use separate disposable databases and Redis databases for Python and
browser suites. Service-dependent tests must pass without skips to establish
multi-user isolation. Account acceptance CI enforces this requirement.

## Documentation and Current Status

Start with:

- `docs/architecture.md`
- `docs/bot-author-guide.md`
- `docs/api-notes.md`
- `docs/implementation-plan.md`

The web-control-plane contract and remaining implementation work are specified
separately:

- `docs/web-control-plane-spec.md`
- `docs/web-control-plane-architecture.md`

[Slice 15](docs/implementation-plan.md#slice-15-users-authentication-and-resource-ownership)
adds email/password accounts, server-side sessions, and private ownership of bots,
templates, revisions, runs, and event streams. Registration signs in immediately
without verification mail. Social login, password recovery and a marketplace are
not included; the application still requires a local/private access boundary.

[Slice 16: marketplace MVP](docs/marketplace-mvp-plan.md) is planned next: signed-in
users publish visual-node strategy snapshots, browse shared listings, and create
independent private copies for paper runs. It is a proposal, not implemented
functionality; its delivery units are in the main implementation plan.


The architecture document also defines strict field, abstraction, module,
validation, safety, and test budgets for each implementation slice. A task that
names one Slice 12 sub-slice must not scaffold later slices.

That plan adds a private, paper-only SvelteKit/FastAPI control plane around this
standalone package. Slices 12A through 12E and Slices 13A through 13F provide its strict
catalog/bot/run contracts, code-owned bot catalog, PostgreSQL persistence,
Taskiq worker, durable progress events, migrations, async stores, FastAPI runs
API, durable SSE path,
deterministic OpenAPI artifact, static client-rendered dashboard UI, and a
validated alpha graph contract with framework-derived triggers, typed constants,
comparisons, generic operations, portfolio queries, signal controls, decision preview,
event-driven fixed-side paper broker actions, editable graph
storage, reusable saved bots, and immutable bot-owned graph revisions. The
browser presents one node-based bot workspace: configuration and graph editing
live in the same form, and a new graph can start fresh or copy another bot.
Its Markets field searches through the backend and supports multiple removable
selections; bot configuration still stores exact market slugs.

Install and verify the frontend from `frontend/`:

```sh
npm ci
npm run generate:check
npm run check
npm test
npm run build
```

For local UI development, run the FastAPI control plane on port `8000` and then
run `npm run dev` from `frontend/`; Vite proxies same-origin `/api` requests to
that API. Run detail combines bounded durable reload history with live market,
executable-equity, followed-wallet, and stream-health updates. Its visible
controls mirror the terminal dashboard's `z`/`x`/`r`/`v`/`j`/`k` keys.
Failed rows in Recent Runs show the latest durable runtime error together with
the recorded failure outcome on hover or keyboard focus.

For local migration work, add the exact disposable PostgreSQL target to `.env`:

```dotenv
POLYBOT_DATABASE_URL=postgresql://user:password@localhost:5432/polybot_dev
```

Then run the `Recreate control-plane database` launch configuration in VS Code.
It terminates connections to that database, drops it if present, creates it,
and applies Alembic migrations through `head`. The command is intentionally
destructive and refuses the `postgres`, `template0`, and `template1` databases.

The current package has the Slice 1 contract layer, Slice 2 paper fill engine,
Slice 3 public market-data adapters, Slice 4 wallet activity inputs, Slice 5
paper runner CLI, Slice 9A historical market recorder and local trim
maintenance, Slice 9B deterministic archive backtester and performance
artifacts, Slice 9B.1 opt-in coverage-gap blackout replay, Slice 10 terminal
dashboard, Slice 11 dynamic market tracking and resolution processing, and the
isolated Slices 12A through 12E and Slices 13A through 13F control-plane
foundation, worker, durable progress path, runs API, mixed durable/live SSE
stream, and browser dashboard. The dashboard has market-price and
followed-wallet timeline views, plus one Svelte Flow bot editor that combines
paper configuration and graph editing. Its trigger outputs, Number/Boolean/Text constants, comparisons, operations,
portfolio queries, signal controls, and fixed-side submit actions come from one
backend catalog. See [graph MVP authoring](docs/graph-node-mvp.md) and its
[two-phase checklist](docs/graph-mvp-plan.md). New
bots start from the catalog graph or a copy of another bot's latest graph. The
frontend uses the existing template-copy API as an internal persistence detail,
then snapshots the bot-owned revision for each run and executes it as an
event-driven paper-trading `NodeBasedBot`;
enabled actions submit through the existing paper
broker and observability path. Press `v` to switch between chart views. Gamma
discovery, CLOB snapshots, market WebSocket books, and Data API wallet reads
use the pinned unified Polymarket SDK and normalize SDK models at the
`polybot.polymarket` boundary. Authenticated runtime adapters remain intentionally
unimplemented until their later slices; no arbitrary-wallet trade stream is
bundled because the pinned SDK does not provide one.

The paper runtime maintains one condition-keyed union of configured markets,
accepted followed-wallet discoveries, and paper positions. Dynamically
discovered markets remain subscribed until resolution. Resolution events settle
paper and followed-wallet positions at contractual `1`/`0` payouts, remove the
terminal condition from the active subscription, and then invoke
`BaseBot.on_market_resolved()`. Paper runs are process-local experiments: a
restart begins a new run with a new bot instance and paper portfolio.

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
`DEFAULT_RECORDINGS_DIR/<local-timestamp>/markets.sqlite3` (or a descriptive
bot/market filename). `DEFAULT_RECORDINGS_DIR` is loaded from the same
environment or `--dotenv` file as the bot and defaults to `data/recordings` when
unset. The timestamped directory separates runs. Use an explicit
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

Before choosing a recording for backtesting, inspect its contents locally:

```sh
uv run python -m polybot.recording.inspect data/recordings/capture.sqlite3
```

The report shows archive size and schema, target identity, total captured event
time, session count and status, unique markets, replay-event counts by kind,
checkpoints, detected/open gaps, capture-anomaly availability, and a per-market
breakdown. It uses an immutable read snapshot and aggregates SQLite indexes and
rows without decoding every event payload. An active recording can be inspected,
but its report is only a point-in-time snapshot and the recorder must stop before
backtesting. `no detected gaps` still does not mean exchange-complete, and the
backtester remains responsible for validating metadata, book bootstrap, range,
and selected-market coverage.

To replace a gapped archive with its longest clean, archive-level all-market
interval, run the local trim utility:

```sh
uv run python -m polybot.recording.trim data/recordings/capture.sqlite3
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
  --backtest data/recordings/btc-five-minute.sqlite \
  --seed 0
```

Replay is headless by default and never constructs a Polymarket SDK client,
performs a network read, or performs paper-runtime persistence. `BOT_MODE=live`
is rejected.
The only replay inputs are metadata revisions, books, lifecycle events, and
coverage-gap evidence from the selected archive interval. A deterministic
virtual clock drives event delivery, strategy sleeps, paper latency, and broker
jitter, so multi-day data runs as quickly as local SQLite reads and bot
computation permit.

By default the sole session's replayable markets and replayable range are
selected. Metadata-only rollover candidates are excluded, and the default
range ends at the last selected market event. Use `--session ID` when an
archive has multiple sessions,
inclusive `--start-ms` and `--end-ms` for a subrange, and repeated
`--market-slug` values for a subset. `--report-interval-ms` defaults to `1000`.
Replay refuses an archive whose recorder lock is still held, unsupported
schemas, missing initial metadata/baselines, and invalid ranges. The default
`--gap-policy strict` also rejects every coverage gap affecting the selected
interval. Once the writer lock is released, abandoned and failed sessions
default to their last committed boundary and are reported as partial recording
sources. A clean subrange on either side of a real coverage gap remains usable
in strict mode; recovery never guesses across that gap.

For a deliberately approximate run that preserves the rest of a long gapped
recording, opt into blackout handling:

```sh
BOT_MODE=paper \
uv run python -m polybot.cli \
  --bot polybot.examples.example_btc_five_minute_momentum:create \
  --backtest data/recordings/btc-five-minute.sqlite \
  --gap-policy blackout
```

Blackout replay does not interpolate, tween, or synthesize a book. At each
gap's exact recorded `started_at_ms` boundary it invalidates only the affected
market books, clears their pending callbacks and executable valuation marks,
and keeps virtual time, strategy and portfolio state, and unaffected markets
running. Affected books become executable again only after real post-gap full
book baselines for both outcome tokens arrive in one subscription generation.
An open gap remains unavailable through the selected end. An order whose
simulated submission-to-fill latency crosses an affecting blackout is rejected
as `backtest_coverage_gap`, even if a fresh book exists again by fill time.
Because strategy callbacks and exchange changes inside each gap are unknown,
the CLI labels the completed result approximate and prints the gap count,
clipped union duration, and open-gap count.

After `polybot.recording.trim` succeeds, the replacement archive contains one
self-contained clean interval, so ordinary backtest defaults can select it
without `--session`, `--start-ms`, or `--end-ms`.

Every backtest creates a new result directory; pass `--results-dir PATH` to
choose it, or let the CLI generate a unique path. Existing directories are
never overwritten. The directory contains:

- `summary.json`: sanitized run/archive identity, selection, seed, event and
  dispatch counts, cash/equity/PnL/return/fees/drawdown metrics, order/fill/
  rejection/resolution totals, open positions, valuation completeness, and
  selected gap-policy provenance and blackout impact metrics;
- `equity.csv`: exact-decimal start, interval, fill, settlement, and end samples
  ready for plotting; and
- `orders.csv`: each submission and completion with requested and filled values,
  rejection details, strategy reason, and source ID.

Open positions are not force-liquidated at the end. Fresh executable marks are
reported when available; last executable estimates are explicitly stale, and
unavailable values remain null. During an affecting blackout the current and
last executable marks are deliberately cleared, so an affected open position is
reported unavailable until a real paired-book recovery. Failed or interrupted
replays retain partial CSV output and an explicit partial status when
finalization can complete.
On completion, the CLI prints a compact performance summary, the result
directory path, and a static full-run net-PnL chart. The chart reads every
`equity.csv` sample before resampling the complete run to the current terminal
width; unlike the live dashboard, it is not limited by the in-memory chart
window. Its summary shows fills, orders, rejections, resolutions, net PnL,
return, drawdown, fees, initial/final equity, filled notional, and valuation
quality. Fresh PnL is green, while stale or temporarily unavailable spans are
dim green. Chart rendering is presentation-only: a rendering failure warns but
does not change a successfully completed backtest's exit status or artifacts.

Display the same chart later by passing a saved result directory:

```sh
uv run python -m polybot.cli.performance_chart data/backtests/<run>
```

The command validates `summary.json` and the exact `equity.csv` schema, works
for finalized completed or partial runs, performs no network access, and does
not require a bot factory or recording archive. It prints a static chart into
terminal scrollback rather than opening the interactive dashboard.

The same performance artifacts are opt-in for an ordinary paper run:

```sh
BOT_MODE=paper \
uv run python -m polybot.cli \
  --bot polybot.my_bot:create \
  --results-dir data/paper-run
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
