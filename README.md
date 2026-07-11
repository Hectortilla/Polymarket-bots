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
Slice 3 public market-data adapters, and Slice 4 wallet activity inputs. Gamma
discovery, CLOB snapshots, market WebSocket books, and Data API wallet reads
use the pinned unified Polymarket SDK and normalize SDK models at the
`bots.polymarket` boundary. Authenticated runtime adapters remain intentionally
unimplemented until their later slices; no arbitrary-wallet trade stream is
bundled because the pinned SDK does not provide one.

Future Polymarket integrations must use an official Polymarket Python SDK or
client wherever it supports the required capability. The unified
`polymarket-client` async SDK is the default for this event-driven framework;
specialized official clients such as `py-clob-client-v2` are the next choice.
Direct HTTP, WebSocket, authentication, signing, or order serialization is
allowed only for a documented capability gap in the official libraries. See
`docs/api-notes.md` for the dependency-selection rule and current official
packages.

The target v1 is event-driven from the start. Paper and live modes must consume
the same market-book, wallet-trade, and fill event shapes so paper behavior
stays close to live behavior.

The live framework is performance-first. WebSocket/streaming sources are the
target live paths for fast-changing data. REST polling is for bootstrap,
metadata, reconnect backfill, reconciliation, or explicit degraded fallback.

Bots can operate on one market, many static market slugs, or dynamic market
slugs generated from context such as time buckets. The runner routes
market-tagged events only to bots whose current market set includes that slug.

Wallet-following bots can watch one or many leader addresses through
`BOT_WALLET_ADDRESSES`. The runner matches addresses case-insensitively and
routes wallet-trade events only from the bot's current wallet set.

Runner dispatch returns a typed `DispatchOutcome`. Rejected events carry a
stable `DispatchSkipReason` instead of collapsing every skip into a boolean.
