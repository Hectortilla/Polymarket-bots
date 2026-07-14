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
tracking and resolution processing. The
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
paper and followed-wallet positions at contractual `1`/`0` payouts and are
persisted before `BaseBot.on_market_resolved()` runs.

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

```sh
BOT_MODE=paper \
BOT_STREAM_RULES='<stream-rules-json>' \
BOT_YES_TOKEN_ID=<yes-token-id> \
uv run python -m polybot.cli --bot polybot.my_bot:create
```
