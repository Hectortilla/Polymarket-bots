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
- BTC five-minute Up/Down probability-momentum bot.

Each example must stay short and avoid framework internals.

Implementation note: the BTC example is implemented as a dynamic bucket bot.
It consumes package-owned `BookSnapshot` contracts for both outcomes and adds
paired-book freshness, microprice normalization, EMA/momentum/noise filters,
book-confirmation, and explicit position exits without importing an SDK or
adding a new network path. Its deterministic unit tests validate strategy rules;
historical performance evaluation is available through Slice 9B after Slice 9A
has captured representative market archives.

## Slice 9A: Historical Market Recorder

Status: done.

Build a standalone, market-only recorder because Polymarket does not document a
historical prediction-market L2 book endpoint. Historical price points and
public trade rows are useful supplementary datasets, but neither reconstructs
resting depth, placements, or cancellations.

Command contract:

- Run as `python -m polybot.recording`.
- Require exactly one target mode: `--bot module:factory` or one or more repeated
  `--market-slug SLUG` values.
- Accept optional `--output PATH` for the SQLite recording archive. When omitted,
  create `recordings/<local-timestamp>/<description>.sqlite3`; the timestamped
  directory separates runs and the filename describes the target. `--resume`
  still requires an explicit existing output path.
- Accept `--duration <number>[s|m|h|d]`; without it, run until graceful
  interruption.
- Refuse to overwrite an existing output on a normal run. Accept `--resume`
  only for an existing schema-compatible archive with the exact stored target
  identity, and append a new session.
- Reuse the runner's `--dotenv` and repeated `--override KEY=VALUE` options for
  bot construction.

Recording behavior:

- Keep the recorder separate from `polybot.cli`: it records inputs and does not
  run `BotRunner`, strategy event hooks, paper execution, or the dashboard.
- In bot mode, call only `current_stream_rules()` and `next_stream_rules()` in a
  read-only planning context. Make its broker reject order and cancellation
  attempts and expose no wallet activity.
- Resolve market slugs through the existing Gamma adapter. Record immutable
  metadata revisions with condition ID, slug, outcomes, token IDs, time bounds,
  and trading constraints needed to interpret later book events.
- Maintain the union of current and available next markets. Retry missing future
  slugs without blocking current capture and pre-subscribe both next-market
  tokens before rollover.
- Use `polybot.polymarket.recording_feed.MarketRecordingFeed`, backed by the
  pinned unified SDK's public `MarketSpec` stream. Preserve its package-owned
  baseline, delta, public-trade, tick-size, and resolution values in recorder
  arrival order; use `BookDepthProjector` for full normalized depth.
- Store source timestamp, local nondecreasing observed timestamp, event kind,
  market/token identity, documented book hash where present, and normalized
  payload needed for deterministic reconstruction. Do not use a timestamp or
  hash as a fabricated exchange sequence.
- Use one caller-owned SQLite file containing sessions, metadata revisions,
  chronological recorded events, book checkpoints, and coverage gaps. Keep it
  independent of `.bot-state/`, the Polyfollow database, and application
  migrations.
- Keep SQLite behind `RecordingArchive` and expose reads through
  `RecordingReader`. Use package-owned `RecordedEvent`, `BookCheckpoint`,
  `CoverageGapPayload`, `CoverageGapRecord`, and `SessionIntegrityStatus`
  contracts rather than exposing database rows.
- On `--resume`, preserve earlier sessions and gaps, mark an unclosed prior
  session interrupted, continue archive-wide arrival order, and append a new
  session. Store the target-wide offline interval as a coverage gap before
  restored unresolved conditions resume capture.

Integrity rules:

- The official prediction-market stream documents timestamps and hashes but no
  sequence, replay, or resume contract. Report `no detected gaps`, never
  `exchange-complete`.
- Open a coverage gap on disconnect, an increased
  `MarketCaptureDiagnostics.dropped_count`, interrupted or reopened condition
  capture, failed normalization after identity is known, or another detected
  continuity loss. Associate it with the affected market/token set and reason.
- Treat consecutive price-change fragments with the same condition, source
  timestamp, and per-token hashes as one logical revision only when an
  intermediate fragment would cross the projected book. Preserve the ordered
  changes and validate the combined delta transactionally. A mismatched,
  unfinished, or timed-out revision is a capture failure and opens a gap.
- Use a separate condition capture handle for every resolved market. Adding a
  next-market handle must not interrupt an existing capture or create a gap by
  itself.
- Continue capture beyond a gap only after each affected token receives a fresh
  source full-book baseline. A terminal resolution may end the gap interval but
  does not repair it. Reject deltas received before their token baseline and do
  not backfill book gaps from `/prices-history`, public `/trades`, or onchain
  settlement data.
- Preserve usable segments before and after a gap. Slice 9B rejects a requested
  replay interval containing an affecting gap while permitting clean selected
  subranges on either side.
- Track clean session closure separately from capture integrity. A graceful
  shutdown must not turn an earlier gapped session into a gap-free one.

Deliberate limitations:

- Record public market data only. Do not record arbitrary-wallet trades,
  authenticated user orders/fills, paper orders/fills, or followed-wallet state.
- Aggregated L2 does not contain maker identity, individual order IDs, or FIFO
  queue position and cannot provide exact maker-fill simulation.
- Do not record Binance, Chainlink, Pyth, sports scores, or other external
  reference feeds. Bots that use them require a later input slice.
- Do not implement replay, a historical broker, parameter sweeps, or performance
  reporting in Slice 9A.

Acceptance:

- Static recording supports multiple explicit market slugs in one archive.
- Bot recording follows dynamic current/next slug changes and has the next
  market subscribed before rollover when Gamma publishes it in time.
- Both outcome tokens have validated metadata and a source full-book baseline before
  incremental changes are considered replayable.
- Graceful shutdown commits the session state; resume appends without
  overwriting previous sessions or hiding downtime. Normal creation refuses an
  existing path, while resume rejects a missing, incompatible, or different-
  target archive.
- Injected disconnects, SDK drops, condition-handle interruptions, and malformed
  known-identity events create stable coverage-gap records and recover only on
  fresh baselines. Adding another condition leaves existing capture segments
  continuous.
- Archive inspection distinguishes open/closed gaps and can state
  `no detected gaps` without making an exchange-completeness claim.
- Tests use synthetic or recorded official-SDK models and a temporary local
  SQLite file; they do not call live Polymarket services.

## Slice 9A.1: Recorder Continuity Hardening

Status: done.

- Conservatively reassemble crossed intermediate price-change fragments using
  the same condition and source timestamp plus a consistent revision
  fingerprint: every initial token/hash must remain present and unchanged, while
  continuations may add token hashes. Additions may be omitted later but cannot
  change if they recur. Quarantine mismatches and never emit them as canonical
  events.
- Classify split-revision mismatch, timeout, stream end, and SDK drop detection
  with typed adapter failures. Check the public handle drop counter throughout
  bounded read-ahead; do not depend on private SDK internals.
- Add an optional diagnostic-only schema-v2 capture-anomaly journal with feature
  activation provenance. Persist normalized fragments, fingerprints, projected
  and advertised best prices, drop counts, elapsed time, and details for every
  failed split-revision recovery attempt without consuming archive replay
  sequence numbers.
  A resumed legacy-v2 archive gains the tables transactionally, while older
  sessions report diagnostics unavailable rather than zero.
- Preserve strict coverage gaps and fresh-baseline recovery. Do not repair gaps
  from REST history or advertised best prices and do not add an allow-gaps mode.
- On condition recovery, immediately write a common two-token checkpoint pair.
  Keep periodic checkpoints suppressed for recovered members of a target-wide
  resumed gap until all affected markets recover, then checkpoint every eligible
  market immediately after final closure using one fresh-timestamp,
  archive-wide batch. Periodic multi-market checkpoints use the same batching
  rule. Resolution-only closure creates no book checkpoint.
- Test superset matching and all rejection paths, SDK drops during read-ahead,
  quarantining, anomaly serialization/availability, legacy resume, repeated
  attempts inside one open gap, and immediate single/target-wide checkpoints.

The upstream market stream still lacks sequence/replay/resume guarantees, so
this slice reduces avoidable gaps and makes remaining gaps diagnosable; it does
not claim that capture can never have a gap.

## Slice 9A.2: Crash-Durable Recording and Partial Recovery

Status: done.

- Make every event, anomaly, gap mutation, and checkpoint acknowledgement wait
  for its committed SQLite transaction under WAL mode with
  `synchronous=FULL`. Capture pumps retain a bounded FIFO of unacknowledged
  writes so SDK bursts can enter the single writer queue and share group
  commits; queue admission assigns sequence order but is not a durability
  acknowledgement. Do not retain acknowledged in-memory-only rows.
- Add atomic writer batches for coupled metadata-plus-resolution events and
  common two-token checkpoints. Keep archive-wide sequence assignment inside
  the single writer. Assemble periodic and recovery checkpoints across all
  eligible markets into one fresh-timestamp batch so reverse task-resumption
  order after a group commit cannot regress checkpoint observation time.
- Drain and finalize the archive independently of capture/client cleanup.
  SIGINT/SIGTERM remains clean; cancellation and catchable failures end at the
  latest durable observation and retain their diagnostic status.
- Add an exclusive replay lease. Refuse a live writer, recover an abandoned
  `active` session as non-clean `incomplete` at its last committed event or
  checkpoint, checkpoint the WAL, and retain the lock through replay and
  archive hashing.
- Permit failed and recovered sessions through their durable boundary by
  default and record `session_integrity_status` plus `uses_partial_session` in
  result selection provenance. Continue rejecting affecting coverage gaps,
  invalid bounds, corruption, and missing metadata or book baselines.
- Keep schema v2 compatible. Test blocking acknowledgements, atomic batches,
  queue and disk failures, active-writer locking, abrupt `os._exit` recovery,
  WAL checkpointing, partial-source replay, resume, and unchanged clean-session
  behavior.

“Recoverable” means the committed, internally valid prefix. It excludes an
uncommitted event, a message never delivered by the upstream stream, damaged
storage, and any interval already represented by a coverage gap.

## Slice 9A.3: Recording Trim Maintenance

Status: done.

Command and selection contract:

- Run as `python -m polybot.recording.trim ARCHIVE`; accept optional
  `--session ID`, `--dry-run`, and `--no-backup`.
- Select the sole session by default and require an explicit session when the
  source archive contains more than one. Keep selection archive-level and
  all-market; do not add market-subset optimization.
- Within the selected replayable session, choose the longest interval unaffected
  by any relevant coverage gap. Treat gaps as half-open `[start, end)` ranges:
  a clean suffix may start at a closed gap's end, while a clean prefix ends
  before its start. An open gap has no clean suffix. If the selected session
  has no relevant gaps, retain its full event-bearing replayable interval.
- Accept a fresh common recovery checkpoint at or immediately after the gap end
  as the clean suffix bootstrap, including when the two recovery baselines
  straddle that boundary. Advance the suffix start to the checkpoint when
  necessary. Verify its generation and depth against canonical recovery events
  before materializing it; do not infer missing state.
- Report the selected source session, start, end, duration, retained event count,
  selected-session gap count, and whole-archive size. `--dry-run` performs
  selection and reporting without replacing the archive or creating its backup.

Rewrite and safety behavior:

- Produce one self-contained schema-v2 replay source. Retain or synthesize the
  time-correct metadata, resolution state, and common two-token book bootstrap
  needed at the new start, then preserve canonical event order inside the clean
  interval. Discard source sessions and canonical event time outside it. Mark
  the validated derived session clean and complete; source failure or recovery
  diagnostics remain available in the retained original backup.
- Never delete gap evidence while retaining events on both sides, infer a book
  across a gap, or describe trimming as gap repair. Refuse a selection that
  cannot be made independently replayable.
- Acquire the exclusive inactive-archive lease, recover an abandoned active
  session at its durable boundary, and checkpoint the WAL before reading the
  source. Refuse a recorder that still owns the archive.
- Build the replacement in a temporary file in the source directory and fully
  validate its schema, integrity, session, metadata, book bootstrap, range, and
  lack of affecting gaps before replacement.
- Preserve the checkpointed original through a hard-linked sibling backup at
  `ARCHIVE.pre-trim` by default; `--no-backup` opts out. Atomically replace the
  requested archive path only after the temporary artifact validates, and leave
  the original usable if any earlier step fails.
- Keep the operation local. It creates no Polymarket SDK/client, makes no network
  request, changes no protocol behavior, and does not use REST history to repair
  the recording.

Acceptance covers prefix/middle/suffix selection, overlapping and open gaps,
half-open and common-recovery-checkpoint boundary behavior, multi-session
ambiguity, self-contained mid-session bootstrap, active-writer refusal, dry-run
reporting, backup behavior, failed temporary validation, atomic replacement,
and a default backtest of the trimmed archive without source selection flags.

## Slice 9A.4: Recording Archive Inspector

Status: done.

- Run as `python -m polybot.recording.inspect ARCHIVE` and remain entirely
  local and read-only.
- Open a validated immutable `RecordingReader` snapshot without taking the
  exclusive replay lease, recovering an abandoned session, or blocking an
  active recorder. Clearly label active-session output as point-in-time only.
- Report archive path, size, schema, target identity, session status and event
  ranges, summed captured duration, unique markets, replay and stored event
  counts by kind, checkpoints, detected/open gaps, capture-anomaly counts or
  unavailability, and per-market spans.
- Aggregate event statistics in SQLite without deserializing every canonical
  event payload so multi-gigabyte recordings remain practical to inspect.
- Preserve integrity language: `no detected gaps` is not an exchange-complete
  claim. Present backtest caveats without certifying replayability; Slice 9B
  retains strict metadata, two-token bootstrap, range, and gap validation.

Acceptance covers typed reader aggregation, human-readable CLI reporting,
missing-archive errors, gaps and partial-session guidance, anomaly availability,
and documentation of the read-only/no-network boundary.

## Slice 9B: Deterministic Backtest Replay

Status: done.

Command and selection contract:

- Run through `python -m polybot.cli --bot module:factory --backtest ARCHIVE`.
  Accept optional `--session ID`, inclusive `--start-ms`/`--end-ms`, repeated
  `--market-slug`, `--seed` (default `0`), `--results-dir`, and
  `--report-interval-ms` (default `1000`).
- Default the sole session, all recorded markets, and its replayable event
  range. Require an explicit session when multiple sessions exist. Refuse an
  existing result directory; create a unique default when none is supplied.
- Keep `BotConfig.mode=paper`, reject `BOT_MODE=live`, and run backtests
  headless by default. Never construct SDK clients, perform network I/O, or
  touch `.bot-state/` during replay.

Replay behavior:

- Accept schema-v2 archives only. Before invoking strategy hooks, take the
  inactive-archive replay lease, check SQLite integrity, validate range and
  market selection, require time-correct metadata and baseline/checkpoint
  coverage, and reject any affecting coverage gap. Complete sessions are
  eligible in full; failed and recovered sessions default to their last durable
  boundary and carry partial-source provenance. Provide no gap override.
- Keep SQLite rows behind `RecordingReader`. Snapshot an immutable archive
  sequence cutoff, expose session/set selection and market enumeration, and
  restore common same-observation checkpoints for both tokens at mid-session
  starts without dispatching the priming events to the strategy.
- Supply archive-backed market and latest-book clients and rejecting wallet and
  position clients. Reuse `BaseBot`, `BotRunner`, `PaperBroker`,
  `OrderRequest`, and `FillEvent`; reject wallet rules, private-user inputs,
  maker queue assumptions, and external-reference dependencies with stable
  backtest failure reasons.
- Use archive-wide sequence as authoritative order and `observed_at_ms` as
  virtual time. Apply metadata revisions as time-correct `Market` values,
  baselines and deltas through `BookDepthProjector`, and recorded resolutions
  as `MarketResolutionEvent`. Tick changes update the recorded market state;
  public trades remain ordered replay inputs but produce no callback because no
  current bot hook consumes them.
- Recompute dynamic plans from virtual time. Suppress events for a recorded next
  market until its slug becomes current, emit reconstructed bootstrap books at
  admission, and retain previously admitted markets until recorded resolution.
- During broker or `ctx.clock.sleep()` latency, consume intervening events
  without re-entering the bot. Update the fill-time book cache, coalesce only
  the newest pending callback per token in live marker order, and keep
  resolutions non-coalesced. Reject latency beyond the selected interval as
  `backtest_data_exhausted`; never fill from later data.
- Call `on_start` and `on_stop` exactly once. Settle recorded positions at
  contractual `1`/`0`, update the in-memory paper portfolio, emit settlement
  telemetry, then call `on_market_resolved`. Do not force-liquidate positions
  at the end.
- Add system-backed `BotContext.clock` and `BotContext.rng` defaults. Replay
  supplies a virtual clock and separately derived seed streams for strategy
  behavior and broker jitter. Framework determinism covers bots using these
  contracts; direct wall time, `asyncio.sleep`, private randomness, external
  I/O, and parameter sweeps remain outside this slice.

Performance artifacts:

- Share executable portfolio valuation between dashboard and reporting. Mark
  longs at fresh best bid and shorts at fresh best ask; expose a prior
  executable estimate separately as stale and leave unavailable values null.
  Calculate drawdown from available marked equity and report estimated or
  incomplete history when stale or missing samples occur.
- Sample at start, every configured virtual/real interval, fills, settlements,
  and end. Stream exact-decimal `equity.csv` and `orders.csv` rows, then
  atomically finalize `summary.json` with sanitized configuration, archive and
  selection provenance, timing, event/dispatch/trading counts, cash/equity,
  gross/net PnL, return, fees, filled notional, drawdown, resolutions, open
  positions, and valuation status.
- Backtests always produce artifacts and treat output failure as fatal. Failed
  or interrupted runs retain an explicit partial status when finalization
  succeeds, and completed commands print a compact final summary and artifact
  path. Ordinary paper runs produce the same artifacts only with
  `--results-dir`; their artifact failures remain fail-open with a visible
  warning and the normal dashboard remains independently usable.

Acceptance is covered by synthetic archive replay, broker timing and
coalescing, dynamic rollover, validation/fail-closed, deterministic seed,
artifact serialization/collision/partial-status, normal paper opt-in, and full
suite tests.

## Slice 10: Terminal Dashboard and Runtime Observability

Status: done.

- Keep terminal rendering outside bot, adapter, and execution code.
- Emit optional fail-open runtime observer events for lifecycle, streams,
  dispatch outcomes, orders, fills, paper portfolio snapshots, and bot-authored
  activity messages with typed severities.
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
