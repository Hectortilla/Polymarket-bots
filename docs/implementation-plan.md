# Implementation Plan

Implement this package in small slices. Do not connect it to the main app.

Latency is a product requirement. Each implementation slice must prefer the
fastest correct source available and document any fallback that is slower than
the intended live path. Do not implement polling as the primary live signal path
when a correct WebSocket/streaming source is available.

## Slice 1: Contracts

Status: done.

- Keep `BaseBot`, `BotContext`, event contracts, and broker protocol small.
- Add tests for fee calculation.
- Add first-class wallet-trade contracts and runner dedupe.
- Add first-class market subscription contracts and market-slug event routing.
- Do not implement network clients yet.

Acceptance:

- `bots` package imports.
- Example bot can be instantiated.
- Fee helper passes symmetry and rounding tests.
- Duplicate wallet source events are skipped before bot hooks run.
- Static multi-market slug lists route only matching market events.
- Dynamic market hooks can expose current and next market slugs.

## Slice 2: Paper Fill Engine

Status: done.

Implement `PaperBroker`.

Required behavior:

- Accept `OrderRequest`.
- Sleep simulated latency plus deterministic or random jitter.
- Read latest book at fill time.
- Sweep asks for buys and bids for sells.
- Respect `max_slippage_pct`.
- Support partial fills.
- Compute taker fee for every consumed level.
- Emit `FillEvent`.
- Track cash, positions, average entry, and cumulative fees in memory.

Tests:

- Fill uses fill-time book, not decision-time book.
- Larger order has equal or worse average price.
- Partial fill never exceeds available depth.
- Slippage cap rejects bad levels.
- Fee is accumulated across multiple levels.

## Slice 3: Public Market Data

Implement public adapters:

- `GammaClient.find_by_slug`.
- `ClobClient.latest`.
- `MarketStream.books`.

Rules:
- Use async I/O.
- Use Polymarket market WebSocket as the live order-book/price signal path.
- Use REST for bootstrap, metadata, backfill, and reconciliation.
- Resolve bot market slugs through Gamma/CLOB metadata before subscribing or
  trading.
- Use `MarketPlan.next` to pre-resolve and pre-subscribe upcoming dynamic
  markets when the upstream source allows it.
- Normalize external payloads at adapter boundaries.
- Emit only typed internal contracts to bots.
- Stable skip/reject reasons for missing or malformed data.

Tests:

- Parse normal market payload.
- Reject missing token IDs.
- Parse book levels into sorted `BookSnapshot`.
- Resolve multiple configured slugs.
- Retry unresolved future dynamic slugs without blocking current market events.

## Slice 4: Wallet Activity Input

Implement wallet-following inputs:

- `WalletActivityClient.latest_trades` using Data API `/trades?user=...`.
- Optional `/activity?user=...` reconciliation path.
- `WalletActivityStream.trades` for the preferred low-latency source.
- Normalize every source into `WalletTradeEvent`.

Rules:

- Do not treat Data API polling as the target live wallet-following path unless
  no correct streaming source exists.
- If no official arbitrary-wallet Polymarket WebSocket exists, evaluate
  on-chain/indexer WebSocket sources before accepting polling.
- Every event needs a stable `source_id`.
- Sort backfilled rows by trade timestamp and deterministic tie-breaker.
- Preserve `trade_timestamp_ms` and `observed_at_ms` for latency modeling.
- Skip missing condition ID, token ID, side, size, price, or source ID.
- Do not let duplicate source IDs call `on_wallet_trade` twice.

Tests:

- Data API trade row normalization.
- Activity trade row normalization.
- Missing required fields are rejected.
- Replayed rows are deduped.
- Observed delay is preserved.

## Slice 5: Runner CLI

Add a tiny script or module entrypoint.

Responsibilities:

- Load `.env`.
- Build `BotConfig`.
- Apply per-bot overrides.
- Build paper broker.
- Open market stream and/or wallet activity stream.
- Subscribe to all current market slugs and prepare `next_markets`.
- Run one bot.

No app imports.

## Slice 6: Live Broker Skeleton

Implement live gating before live order submission.

Required gates:

- `BOT_MODE=live`.
- `BOT_LIVE_ENABLED=true`.
- Private key is configured.
- Wallet/funder address is configured.
- CLOB credentials can be derived or loaded.

Acceptance:

- Missing any live requirement fails closed.
- Paper mode cannot accidentally instantiate live broker.

## Slice 7: Live Fill Confirmation

Implement authenticated user WebSocket parsing.

Rules:

- A live order is not considered final until confirmed by user stream or a
  deliberate reconciliation call.
- `FillEvent` shape must match paper events.
- Include exact fee when available.

## Slice 8: Bot Examples

Add examples one by one:

- Price threshold bot.
- Wallet follower bot.
- Spread watcher bot.
- Small market-maker bot with inventory limits.

Each example must stay short and avoid framework internals.

## Slice 9: Backtesting Inputs

Optional later slice.

- Replay stored book snapshots into `BotRunner`.
- Replay stored wallet trades into `BotRunner`.
- Reuse the same `BaseBot` hooks.
- Make latency deterministic for repeatable tests.
