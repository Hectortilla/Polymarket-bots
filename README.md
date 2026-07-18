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
paper runner CLI, Slice 10 terminal dashboard, and Slice 11 dynamic market
tracking and resolution processing, plus Slice 9A's standalone historical
market recorder. The
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
BOT_STREAM_RULES='<stream-rules-json>' \
BOT_YES_TOKEN_ID=<yes-token-id> \
uv run python -m polybot.cli --bot polybot.my_bot:create
```

## Historical Market Recording

Polymarket exposes current L2 books, historical token-price points, and public
trade rows through different API surfaces. It does not document a public
archive of historical L2 books. Slice 9A therefore records the live public
market stream into a user-selected SQLite recording archive for later Slice 9B
replay.

Slice 9A's standalone command is `python -m polybot.recording`. Select either a
bot factory, whose current and
next market rules provide the recording topology, or one or more explicit
market slugs. The two selection modes are mutually exclusive:

```sh
uv run python -m polybot.recording \
  --market-slug btc-updown-5m-1767225600 \
  --market-slug eth-updown-5m-1767225600 \
  --output recordings/two-markets.sqlite \
  --duration 2h
```

```sh
uv run python -m polybot.recording \
  --bot polybot.examples.example_btc_five_minute_momentum:create \
  --output recordings/btc-five-minute.sqlite \
  --duration 10d
```

Omit `--duration` to run until graceful interruption. Use `--resume` to append
another recording session to an existing compatible archive with the same
target selection. A normal run refuses to overwrite an existing output, and
`--resume` records the offline interval as a coverage gap. The recorder also
accepts the runner's existing `--dotenv` and `--override` options when loading a
bot factory.

The archive contains sessions, market metadata revisions, chronological
recorded events, full book checkpoints, and explicit coverage gaps. An archive
can report `no detected gaps`; it cannot prove exchange-complete capture because
the official prediction-market stream documents timestamps and book hashes but
no sequence number, replay cursor, or resume protocol.

Slice 9A is market-only. It does not record arbitrary-wallet activity, private
orders or fills, maker identities or queue position, or Binance, Chainlink,
Pyth, or other external reference feeds. Strategies that require those inputs
need additional future recording slices before their results can be reproduced.
The SQLite file is a local artifact, not an application database or a dependency
on the Polyfollow app.

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
