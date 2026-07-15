# Implementation Plan

Implement this package in small slices. Do not connect it to the main app.

Latency is a product requirement. Each implementation slice must prefer the
fastest correct source available and document any fallback that is slower than
the intended live path. Do not implement polling as the primary live signal path
when a correct WebSocket/streaming source is available.

## Network Implementation Rule

Every network slice must first map its requirements against the current
official Polymarket Python libraries. Use the unified `polymarket-client` async
SDK wherever it supports the operation or stream. If it does not, use a
specialized official client such as `py-clob-client-v2` or
`py-builder-relayer-client` before considering a direct integration.

Direct HTTP/WebSocket, authentication, signing, order serialization, or
protocol-model implementations are prohibited unless the official libraries
lack the required capability or cannot satisfy a documented correctness or
latency requirement. Record such an exception in `docs/api-notes.md` and the
affected slice before implementation. Keep official-library types within
`polybot.polymarket` adapters and normalize them into package-owned contracts.
Pin the chosen dependency version and add adapter contract tests; the unified
SDK's current beta status is not, by itself, an exception.

## Slice 1: Contracts

Status: done.

- Keep `BaseBot`, `BotContext`, event contracts, and broker protocol small.
- Add tests for fee calculation.
- Add first-class wallet-trade contracts and runner dedupe.
- Add static multi-wallet configuration, subscription contracts, and
  case-insensitive wallet-event routing.
- Add first-class market subscription contracts and market-slug event routing.
- Do not implement network clients yet.

Acceptance:

- `polybot` package imports.
- Example bot can be instantiated.
- Fee helper passes symmetry and rounding tests.
- Duplicate wallet source events are skipped before bot hooks run.
- Multiple configured wallet addresses route only matching wallet trades.
- Static multi-market slug lists route only matching market events.
- Dynamic market hooks can expose current and next market slugs.
- Dispatch rejection exposes a stable typed reason.
- Future-dated, malformed, crossed, and stale inputs fail closed before hooks.

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
- Claim source IDs atomically across concurrent in-flight submissions.
- Retain successful paper source claims for the broker process lifetime so
  replayed source IDs cannot apply a second portfolio transition.
- Keep validation, market lookup, fill math, and portfolio transitions in
  responsibility-owned modules.

Tests:

- Fill uses fill-time book, not decision-time book.
- Larger order has equal or worse average price.
- Partial fill never exceeds available depth.
- Slippage cap rejects bad levels.
- Fee is accumulated across multiple levels.

## Slice 3: Public Market Data

Status: done.

Implement public adapters:

- Internal `GammaClient.find_by_slug`, backed by the unified async SDK.
- Internal `ClobClient.latest`, backed by the unified async SDK or the official
  CLOB client when required.
- Internal `MarketStream.books`, backed by the unified async SDK subscription.

Rules:
- Use async I/O.
- Do not expose official SDK/client models outside the adapter boundary.
- Use Polymarket market WebSocket as the live order-book/price signal path.
- Use REST for bootstrap, metadata, backfill, and reconciliation.
- Resolve bot market slugs through Gamma/CLOB metadata before subscribing or
  trading.
- Use `MarketPlan.next` to pre-resolve and pre-subscribe upcoming dynamic
  markets when the upstream source allows it.
- Normalize external payloads at adapter boundaries.
- Emit only typed internal contracts to polybot.
- Stable skip/reject reasons for missing or malformed data.

Tests:

- Pin and record the selected official library version.
- Contract-test official-library models/events into internal types.
- Parse normal market payload.
- Reject missing token IDs.
- Parse book levels into sorted `BookSnapshot`.
- Reject book snapshots whose token or condition identity disagrees with
  resolved metadata.
- Reject malformed market payloads and unknown price-change sides at ingress.
- Resolve multiple configured slugs.
- Retry unresolved future dynamic slugs without blocking current market events.

Implementation notes:

- `GammaClient.find_by_slug()` uses `AsyncPublicClient.get_market(slug=...)`
  for one-off lookups. `GammaClient.find_many()` uses
  `AsyncPublicClient.list_markets(slug=..., page_size=100)` to resolve
  sequential paginated Gamma requests with no more than 100 slugs per filter
  array and a query-size-safe encoded budget, and exposes a cancel-safe retry
  loop for future slugs. Unresolved first-pass slugs are retried in a batch with
  `closed=true` because the list endpoint defaults to `closed=false`.
- `ClobClient` uses `AsyncPublicClient.get_order_book(token_id=...)` for REST
  bootstrap and reconciliation snapshots.
- `MarketStream` uses `AsyncPublicClient.subscribe(MarketSpec(...))`. It owns
  live depth, applies all changes in one price-change message atomically, and
  emits only complete sorted `BookSnapshot` contracts.
- The selected official library remains pinned in `pyproject.toml`.
  No direct-network exception was required.

## Slice 4: Wallet Activity Input

Status: done.

Implement wallet-following inputs:

- `WalletActivityClient.latest_trades` using the unified async SDK's Data API
  coverage when available, otherwise a documented direct
  `/trades?user=...` exception.
- Optional `/activity?user=...` reconciliation path.
- `WalletActivityStream.trades` for the preferred low-latency source.
- Normalize every source into `WalletTradeEvent`.
- Subscribe the low-latency stream to every current wallet address.
- Fan out wallet-scoped bootstrap and reconciliation reads across all current
  wallet addresses with bounded concurrency, then merge them deterministically.

Rules:

- Do not treat Data API polling as the target live wallet-following path unless
  no correct streaming source exists.
- If no official arbitrary-wallet Polymarket WebSocket exists, evaluate
  on-chain/indexer WebSocket sources before accepting polling.
- Re-check the unified SDK and specialized official clients before selecting a
  direct Data API or third-party stream implementation.
- Every event needs a stable `source_id`.
- Sort backfilled rows by trade timestamp and deterministic tie-breaker.
- Preserve `trade_timestamp_ms` and `observed_at_ms` for latency modeling.
- Skip missing condition ID, token ID, side, size, price, or source ID.
- Do not let duplicate source IDs for the same wallet call
  `on_wallet_trade` twice. Do not collapse equal source IDs from different
  wallets.
- Normalize wallet addresses for case-insensitive matching before framework
  routing.

Tests:

- Data API trade row normalization.
- Activity trade row normalization.
- Missing required fields are rejected.
- Replayed rows are deduped.
- Observed delay is preserved.
- Multiple wallets are fetched/subscribed and merged without dropping events.
- One failing wallet read does not silently erase successful wallet results;
  the adapter exposes a stable failure or degraded-state reason.

Implementation notes:

- `WalletActivityClient` uses the pinned unified SDK's public
  `list_trades(user=...)` and `list_activity(user=..., activity_types=("TRADE",))`
  methods; no direct HTTP exception is required.
- Reads for multiple wallets use bounded concurrency, deterministic timestamp
  ordering, wallet-scoped source dedupe, and explicit per-wallet failures.
- The pinned SDK does not expose an arbitrary-wallet trade stream. The
  `WalletActivityStream` boundary supports an injected compatible low-latency
  source and otherwise uses SDK-backed Data API polling as its explicit
  degraded fallback. It fails closed only when neither source is configured.

## Slice 5: Runner CLI

Status: done.

Add a tiny script or module entrypoint.

Responsibilities:

- Load `.env`.
- Build `BotConfig`.
- Apply per-bot overrides.
- Build paper broker.
- Open market stream and/or wallet activity stream.
- Load all configured wallet addresses and pass the current wallet plan to the
  wallet activity stream/client.
- Subscribe to all current markets declared by `StreamPlan` and prepare next
  stream rules.
- Run one bot.

Implementation notes:

- `polybot.cli` loads `.env` files with the `python-dotenv` library, including
  quoted multiline values, without overriding existing process variables;
  it accepts `module:attribute` bot factories and supports typed config
  overrides.
- Slice 5 originally subscribed current markets only and resolved available next
  markets on a best-effort basis. Slice 11 supersedes that lifecycle with the
  unresolved union registry. The runner still refreshes dynamic plans once per
  second without blocking the current market hot path on next-market
  resolution.
- Market and wallet streams are multiplexed into one `BotRunner` lifecycle.
- Stream multiplexing applies freshness-preserving backpressure: pending books
  coalesce by token ID, idempotent market-trade wake hints coalesce by condition
  ID, and wallet trades remain lossless FIFO events. A superseded pending book
  is counted as a local coalescing drop; generation-close cleanup is not.
- The CLI supplies SDK-backed Data API polling for wallet streams because the
  pinned SDK does not provide an arbitrary-wallet stream. Compatible injected
  sources remain optional low-latency additions; a stream fails closed only
  when neither a client nor a source is configured.
- CLI paper runs use an atomic file-backed source-claim store under
  `.bot-state/` to preserve wallet-event idempotency across restarts without
  adding a database dependency.

No app imports.

## Slice 6: Live Broker Skeleton

Implement live gating before live order submission.

Build live authentication, credential derivation, signing, and submission on
`AsyncSecureClient` or, where necessary, the official CLOB client. Do not
reimplement those protocol operations.

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

Use the unified async SDK's authenticated user subscription unless a verified
capability, correctness, or latency gap is documented before implementation.

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

## Slice 10: Terminal Dashboard and Runtime Observability

Status: done.

- Keep terminal rendering outside bot, adapter, and execution code.
- Emit optional fail-open runtime observer events for lifecycle, streams,
  dispatch outcomes, orders, fills, and paper portfolio snapshots.
- Emit fail-open bootstrap progress for configured market resolution and
  followed-wallet loading; render completed/total counters in Activity.
- Decorate the CLI broker without changing its public order/fill contract.
- Render a Rich dashboard with an `asciichartpy` fixed-scale multi-token price
  chart with a taller plotting area, variance-padded executable-wallet-value
  curve, activity ticker, and persistent status metrics. Support terminal-only
  fixed-width time-window controls: `z` zooms in, `x` zooms out, and `r`
  resets. Show the visible start and end times below the plots. Mark completed
  buys in wallet-value green and sells in red, anchored to the traded token's
  line. Add a `v`-toggled followed-wallet trade-time raster view with one lane
  per wallet, relative-notional glyphs, dimmed skipped events, shared time
  controls, and `j`/`k` wallet paging.
- Extend stream health with run-lifetime raw/coalesced book counts, cumulative
  dropped/received ratio, and a recent ratio over the last 100 book-bearing
  health-counter deltas; retain these in telemetry state without displaying
  the drop metrics in the dashboard status row. Preserve lifetime counters and peak queue depth across
  dynamic stream-plan rebuilds while resetting current depth per generation.
- Enable by default and support `--no-dashboard` for headless operation (with
  `--dashboard` retained as the explicit positive form).

Acceptance:

- Dashboard failures cannot interrupt dispatch, execution, or shutdown.
- Dashboard failures close the live display and leave a traceback in the
  terminal.
- No strategy logging or rendering code is required.
- PnL marks longs at best bid and shorts at best ask. If a held position loses
  its book, including while its market awaits resolution, show a clearly
  labeled stale estimate from that position's last executable unit mark,
  multiplied by the current position size. A fill refreshes that mark when the
  current book can execute the updated position.
- The chart displays up to twenty tokens. Additional tracked tokens do not
  rotate visible series or reset their histories when repeated market snapshots
  arrive.

## Slice 11: Dynamic Market Tracking and Resolution

Status: done.

- Own one deduplicated runtime registry keyed by `condition_id`, merging
  configured, accepted followed-wallet, and paper-position interests.
- Keep filtered rules as strict allowlists; allow wallet-only and independent
  rules to discover markets. Retain unresolved dynamic entries across stream
  plan changes.
- Bootstrap newly followed wallets from current open positions only. Persist
  follow epochs, executable baselines, deterministic movement journals, source
  IDs, checkpoints, and settlements atomically under `.bot-state/`.
- Bootstrap absolute wallet follows from all current positions, but use the
  Data API market condition-ID filter for filtered wallet follows so unrelated
  positions are never loaded into follow state.
- Replay gross PnL by `(trade_timestamp_ms, source_key)` without guessing fees.
- Subscribe once with `MarketSpec(..., custom_feature_enabled=True)`. Batch new
  registry token pairs at the interval owned by `MARKET_ADDITION_BATCH_SECONDS`
  in `polybot.cli.tracked_markets` and replace the union SDK handle because the
  pinned SDK cannot mutate it.
- Normalize SDK `MarketResolvedEvent` into `MarketResolutionEvent`; reject
  mismatched condition, token-pair, winner, or outcome identity. Preserve
  Gamma's public outcome labels (including `Up`/`Down`) through books, wallet
  events, resolution events, and persistence. Use the winning token ID, never a
  fixed label vocabulary, to determine contractual payout.
- Reconcile unresolved markets through Gamma immediately after replacement and
  at the interval owned by `RESOLUTION_RECONCILIATION_SECONDS`.
- Settle paper and followed-wallet positions at `1` for the winning token and
  `0` for the losing token. Transfer paper payout to cash, archive wallet
  journals, persist idempotency, then invoke `BaseBot.on_market_resolved()`.
- Emit non-coalesced resolution and observer settlement events. A successful
  settlement is terminal: remove the condition from the union subscription and
  clear both outcome tokens from the dashboard series, legend, labels, ticker,
  and cached chart state. The dashboard retains only a deduplicated,
  run-lifetime `resolved N` status count; do not add a second market panel.

Acceptance:

- Multiple wallets discovering one condition create one registry entry and one
  token pair in the active SDK handle.
- Books for registry-admitted wallet discoveries reach `on_book` even when the
  originating wallet-only rule declares no static market slugs.
- Filtered rules never expand outside their allowlists; wallet-only and
  independent rules can expand the registry.
- Bootstrap PnL starts at zero when an executable mark exists and remains
  unavailable when it does not.
- Buys, sells, out-of-order delivery, duplicates, restarts, removal/re-add, and
  resolution produce deterministic gross accounting.
- Resolution settlement is persisted before the bot hook and is idempotent.
- Resolved markets leave the next union handle while unresolved entries remain,
  cannot be re-admitted after restart from configured, wallet, or paper
  position interests, and are settled before a bootstrap/rebuild can subscribe
  to a Gamma-known resolved market.
- Gamma reconciliation recovers lifecycle events missed by the stream.
