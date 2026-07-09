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

The current package has the Slice 1 contract layer plus the Slice 2 paper fill
engine: contracts, docs, safety gates, example shape, and an in-memory
`PaperBroker.submit()` implementation. The network adapters are still
intentionally unimplemented until the later implementation-plan slices fill
them in.

The target v1 is event-driven from the start. Paper and live modes must consume
the same market-book, wallet-trade, and fill event shapes so paper behavior
stays close to live behavior.

The live framework is performance-first. WebSocket/streaming sources are the
target live paths for fast-changing data. REST polling is for bootstrap,
metadata, reconnect backfill, reconciliation, or explicit degraded fallback.

Bots can operate on one market, many static market slugs, or dynamic market
slugs generated from context such as time buckets. The runner routes
market-tagged events only to bots whose current market set includes that slug.
