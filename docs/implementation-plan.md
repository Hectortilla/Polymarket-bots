# Implementation Plan

Implement this package in small slices. Do not connect it to the Polyfollow app.
Slices 12A through 12F plan a standalone web control plane inside this
repository; they do not authorize imports from Polyfollow application code,
models, workers, frontend, or configuration.

Latency is a product requirement. Each implementation slice must prefer the
fastest correct source available and document any fallback that is slower than
the intended live path. Do not implement polling as the primary live signal path
when a correct WebSocket/streaming source is available.

## Repository Organization

Source packages live at `backend/src/polybot` and `backend/src/api`; the HTTP
layer is `api.http`, and the Taskiq entrypoint is
`api.execution.taskiq_app:broker`. Python tests, migrations, and exported
contracts live under `backend`. Python tooling and the lockfile stay at the
repository root. Local output defaults live under `data`. This repository-wide
relocation preserves implemented slice behavior and adds no new slice features;
see `docs/architecture.md`, **Package Layout**, for the directory map.

## September 10 local migration consolidation

The user confirmed that nothing is deployed and local data is disposable, and
approved replacing the entire Alembic chain with one initial revision (`0001`).
This maintenance change supersedes the historical migration/reset requirements
below for the current local schema; it adds no product slice. The initial revision
creates the complete schema from Slices 12–21, including verification defaults,
ownership, event cursor indexes, launch reliability, operations state, and lifecycle
metadata, plus the saved-bot deletion marker. The user also approved folding
the soft-delete migration into this initial revision: there are no deployments
and local data will be removed. Old development databases must be explicitly
recreated. Future retained
deployments still require forward migrations and backups.

Migration acceptance covers the sole `0001` root/head, offline SQL, complete schema
parity with ORM metadata, database defaults, required operations seed state,
repeat upgrades on populated data, and upgrade/downgrade/re-upgrade. Manual Ruff
and Prettier launch commands are optional; no formatting enforcement is introduced.

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
- Internal `MarketStream.books`, backed by the unified async SDK subscription,
  yielding `BookSnapshot` values and typed `BookGapEvent` continuity losses.

Rules:
- Use async I/O.
- Do not expose official SDK/client models outside the adapter boundary.
- Use Polymarket market WebSocket as the live order-book/price signal path.
- Use REST for bootstrap, metadata, backfill, and reconciliation.
- Resolve bot market slugs through Gamma/CLOB metadata before subscribing or
  trading.
- Use `StreamPlan.next` to pre-resolve and pre-subscribe upcoming dynamic
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
- Invalidate every affected condition book on a stream gap or rejected frame,
  emit a stable typed `BookGapEvent`, and require fresh baselines for every
  subscribed token before resuming snapshots.
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
  emits complete sorted `BookSnapshot` contracts plus typed `BookGapEvent`
  continuity losses. Affected condition depth remains quarantined until every
  subscribed outcome token receives a fresh full-book baseline.
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
- CLI paper runs retain source-event idempotency only for one process. A restart
  deliberately begins a new paper run rather than attempting a partial resume.

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
  create `DEFAULT_RECORDINGS_DIR/<local-timestamp>/<description>.sqlite3`, using
  `data/recordings` when that environment variable is unset; the timestamped directory
  separates runs and the filename describes the target. `--resume`
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
- Use `polybot.polymarket.recording_feed.feed.MarketRecordingFeed`, backed by the
  pinned unified SDK's public `MarketSpec` stream. Preserve its package-owned
  baseline, delta, public-trade, tick-size, and resolution values in recorder
  arrival order; use `BookDepthProjector` for full normalized depth.
- Store source timestamp, local nondecreasing observed timestamp, event kind,
  market/token identity, documented book hash where present, and normalized
  payload needed for deterministic reconstruction. Do not use a timestamp or
  hash as a fabricated exchange sequence.
- Use one caller-owned SQLite file containing sessions, metadata revisions,
  chronological recorded events, book checkpoints, and coverage gaps. Keep it
  independent of the paper runtime, the Polyfollow database, and application
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
- Preserve usable segments before and after a gap. Slice 9B's default strict
  policy rejects a requested replay interval containing an affecting gap while
  permitting clean selected subranges on either side; Slice 9B.1 later adds an
  explicit approximate blackout policy without changing recorder integrity.
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
- Preserve strict coverage-gap evidence and fresh-baseline recovery. Do not
  repair gaps from REST history or advertised best prices and do not add a
  recorder-side or implicit allow-gaps mode. Slice 9B.1's later explicit
  blackout replay policy consumes the same evidence without mutating it.
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
  result selection provenance. Continue rejecting affecting coverage gaps in
  default strict replay, plus invalid bounds, corruption, and missing metadata
  or book baselines. Slice 9B.1 later adds only an explicit approximate policy.
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
  retains strict metadata, two-token bootstrap, and range validation. It rejects
  gaps by default; Slice 9B.1 requires an explicit approximate blackout choice.

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
- Default the sole session, all replayable markets, and their replayable event
  range. Exclude metadata-only rollover candidates and end the default range
  at the last selected market event. Require an explicit session when multiple
  sessions exist. Refuse an existing result directory; create a unique default
  when none is supplied.
- Keep `BotConfig.mode=paper`, reject `BOT_MODE=live`, and run backtests
  headless by default. Never construct SDK clients, perform network I/O, or
  perform paper-runtime persistence during replay.

Replay behavior:

- Accept schema-v2 archives only. Before invoking strategy hooks, take the
  inactive-archive replay lease, check SQLite integrity, validate range and
  market selection, require time-correct metadata and baseline/checkpoint
  coverage, and reject any affecting coverage gap under the default `strict`
  policy. Complete sessions are eligible in full; failed and recovered sessions
  default to their last durable boundary and carry partial-source provenance.
  Slice 9B.1 adds only an explicit `blackout` policy; there is no implicit gap
  override.
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
- After successful finalization, print a static full-run net-PnL chart from
  `equity.csv`. Reuse the live dashboard's green/dim-green single-series
  renderer and variance padding, but resample the complete artifact range to
  terminal width instead of applying the bounded live history window. Include
  a compact summary of trading counts, PnL/return/drawdown/fees, equity,
  notional, and valuation quality. Keep this post-completion presentation
  fail-open.
- Provide `python -m polybot.cli.performance_chart RESULTS_DIR` to validate a
  finalized `summary.json` plus exact-schema `equity.csv` and render the same
  chart for completed, failed, or cancelled runs. The command is static,
  read-only, bot/archive-independent, and network-free.

Acceptance is covered by synthetic archive replay, broker timing and
coalescing, dynamic rollover, validation/fail-closed, deterministic seed,
artifact serialization/collision/partial-status, normal paper opt-in, and full
suite tests. Static-chart acceptance additionally covers exact CSV validation,
nondecreasing and duplicate timestamps, finite PnL values, fresh/stale/missing
samples, full-range resampling beyond the live history limit, partial-run
labels, and nonfatal automatic rendering failures.

## Slice 9B.1: Approximate Coverage-Gap Blackout Replay

Status: done.

Command and policy contract:

- Extend the backtest CLI with `--gap-policy {strict,blackout}`. Keep `strict`
  as the default and preserve Slice 9B's pre-hook rejection of every affecting
  coverage gap. Require the caller to select `blackout` explicitly and label
  its completed result approximate.
- Retain the inactive-archive lease, immutable replay cutoff, schema and SQLite
  integrity checks, selected-session/range/market validation, and initial
  time-correct metadata plus common two-token baseline/checkpoint requirements.
  Blackout is not a corruption, missing-bootstrap, or invalid-range override.
- Resolve only gaps that affect the selected markets. Keep the archive
  read-only, construct no SDK/client, make no network call, and never change a
  session or gap's stored integrity status.

Blackout scheduling and state:

- Preload the selected `CoverageGapRecord` values. Schedule a gap from the
  payload's exact `started_at_ms`, even when loss was detected and its canonical
  gap event was appended later. At an equal timestamp, activate the blackout
  before applying or dispatching market events. Treat closed intervals as
  half-open `[start, end)` and clip accounting to the selected replay range.
- Resolve condition-, slug-, token-, and target-wide scope conservatively. At
  activation, invalidate the affected market projectors and latest books,
  remove affected performance books and last executable marks, and purge
  pending coalesced callbacks for the affected tokens. Preserve bot state,
  virtual time, paper cash and positions, metadata, and unaffected market
  processing.
- Do not dispatch affected book callbacks or expose an executable affected book
  during a blackout. Continue ordinary callbacks, fills, dynamic planning, and
  valuation for unaffected markets. Overlapping scopes keep a market unavailable
  until every affecting blackout permits recovery.
- Recover only from canonical recorder evidence. For a closed affected market,
  require fresh full-book baselines for both outcome tokens after the gap opened
  and in one subscription generation; make the pair visible atomically only at
  the verified recovery boundary. A single-token, mixed-generation, stale, or
  pre-gap baseline cannot restore either book. A resolution is terminal and
  never fabricates a recovery book. An open gap remains unavailable through the
  selected end.

Execution safety and approximation boundary:

- Reject an order for an affected market when it is submitted during a
  blackout or when its simulated submission-to-fill latency interval crosses
  one. Use the stable `backtest_coverage_gap` fill rejection even if a real
  paired book has recovered by nominal fill time. Leave unaffected-market
  orders and `backtest_data_exhausted` end-of-selection behavior unchanged.
- Never interpolate, tween, hold forward, or synthesize price, spread, depth,
  liquidity, a public trade, strategy callback, or fill. Do not use
  `/prices-history`, public trades, onchain settlement, advertised best prices,
  or later book state to populate the interval. Blackout preserves surrounding
  state but cannot recover the exchange events or decisions that were missed.
- Keep affected open positions in the paper portfolio. Their valuation is
  unavailable while their executable books and marks are invalid; a real paired
  recovery can make subsequent valuation fresh again.

Provenance and acceptance:

- Add deterministic selection provenance for `gap_policy`, sorted
  `coverage_gap_ids`, `coverage_gap_count`, clipped half-open union
  `coverage_gap_duration_ms`, `coverage_gap_open_count`, sorted
  `coverage_gap_affected_position_token_ids`, and
  `coverage_gap_affected_position_count`. Add
  `coverage_gap_rejected_order_count` to performance metrics, while preserving
  each order's stable rejection in `orders.csv`.
- Print `Backtest used blackout coverage-gap handling: gaps=N duration=Nms
  open=N; results are approximate` after a completed blackout run.
- Acceptance covers unchanged default strict rejection, backdated exact-start
  activation, same-timestamp ordering, scoped multi-market continuation,
  pending-callback purge, same-generation paired recovery, open and overlapping
  gaps, unavailable-then-fresh position valuation, latency-crossing order
  rejection after recovery, deterministic provenance, and no synthetic fills or
  archive mutation.

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
  coalesced/received ratio, and a recent coalescing ratio over the last 100
  book-bearing health-counter deltas; retain these in telemetry state without
  displaying the coalescing metrics in the dashboard status row. Preserve
  lifetime counters and peak queue depth across dynamic stream-plan rebuilds
  while resetting current depth per generation.
- Enable by default and support `--no-dashboard` for headless operation (with
  `--dashboard` retained as the explicit positive form).

Acceptance:

- Dashboard failures cannot interrupt dispatch, execution, or shutdown.
- Dashboard failures close the live display and leave a traceback in the
  terminal.
- An empty paper portfolio shows configured cash and equity with zero PnL from
  startup, before the first order or fill.
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
- Bootstrap newly followed wallets from current open positions only. Keep follow
  epochs, executable baselines, deterministic movement journals, source IDs, and
  settlements in memory for the current paper run.
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
  journals in memory, then invoke `BaseBot.on_market_resolved()`.
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
- Buys, sells, out-of-order delivery, duplicates, removal/re-add, and resolution
  produce deterministic gross accounting within one run.
- Resolution settlement is idempotent within one run and occurs before the bot
  hook.
- Resolved markets leave the next union handle while unresolved entries remain,
  cannot be re-admitted during the run from configured, wallet, or paper
  position interests, and are settled before a bootstrap/rebuild can subscribe
  to a Gamma-known resolved market.
- Gamma reconciliation recovers lifecycle events missed by the stream.

## Web Control-Plane Slice Rule

Slices 12A through 12F implement the planned private web control plane. For any
task naming one slice:

- that slice is the complete scope;
- follow the field, abstraction, module, validation, safety, and test budgets in
  `web-control-plane-architecture.md`;
- use that architecture as the source for contracts and algorithms rather than
  copying them into code or tests; and
- do not scaffold a later slice.

A new field, module, abstraction, dependency, endpoint, fallback, or test helper
must have a current-slice consumer. If it does not, omit it.

## Slice 12A: Minimal Contracts, Catalog, and Run Row

Status: implemented.

Minimum deliverable:

- Add the inward-dependent `api` package without changing
  `polybot`.
- Add only the Pydantic, SQLModel/SQLAlchemy async PostgreSQL, driver, and
  Alembic dependencies imported by this slice.
- Implement the canonical catalog and run contracts named in
  `web-control-plane-architecture.md`.
- Register the catalog rows owned by the product-spec table. Each entry
  has one Pydantic launch model, generated schema, and direct conversion to the
  credential-free `PaperRunConfig`.
- Add the Slice 12A run row defined by the architecture and its first Alembic
  migration. Persist
  the one resolved config snapshot; do not persist a second copy of launch
  inputs.
- Add only the small run-store operations needed to create, read, and list those
  rows. Direct owning-module SQLModel session code is preferred over a generic
  repository class.

Do not add FastAPI routes, Taskiq, Redis, events, claim/stop/heartbeat logic,
summary fields, error frameworks, users, credentials, live mode, ECS, retention,
or frontend files.

Acceptance:

- Catalog tests cover the initial entries, alias omission, generated schema, one
  bot-managed case, and the wallet-input case.
- A conversion test proves exact decimal strings and that a `PaperRunConfig`
  cannot contain live/credential fields.
- One PostgreSQL migration test proves upgrade/downgrade and the exact run
  columns. One model test proves the public contract does not gain database-only
  fields.
- One PostgreSQL round trip proves create/read/list ordering and exact typed
  config/decimal restoration.

## Slice 12B: Taskiq Worker and Durable Progress

Status: implemented; depends on Slice 12A.

Minimum deliverable:

- Add only Taskiq, its Redis broker integration, and the async Redis dependency
  first used here.
- Implement the canonical `RunLauncher` protocol, one Taskiq adapter, and the
  architecture-owned task/worker entrypoints.
- Add the Slice 12B run columns and exact durable-event table from the
  architecture in one migration.
- Implement one conditional atomic claim returning a typed run or `None`.
  Worker concurrency is Taskiq deployment configuration; do not implement a
  second capacity scheduler.
- Convert the already-decoded `PaperRunConfig` to `BotConfig`, instantiate
  the exact catalog factory, run the existing runtime, write heartbeat, poll the
  durable stop state, and record lifecycle outcome.
- Implement the web observer with a small runtime-event projection and separate
  async event-store/Redis I/O, following the architecture-owned durability
  classification. Retain only the latest stream-health input in memory and
  append it once as a final summary during graceful observer shutdown.
- Drain accepted durable progress before the terminal event on cooperative
  stop. Preserve the architecture-owned observer boundary.

Do not add FastAPI, SSE, Redis polling fallbacks, Taskiq result storage/task
termination, ECS fields/adapters, auto-resume, generic executor/service classes,
retry frameworks, or event metadata outside the architecture contract.

Acceptance:

- A real-PostgreSQL concurrent-delivery test proves one claim and one bot
  instance for a duplicated run ID.
- Scenario tests cover queued stop, running cooperative stop, worker lease loss
  to `interrupted`, and no restart/resume on redelivery.
- Failure scenarios cover runtime failure sanitization and prove the
  architecture-owned observer isolation invariant.
- Event tests cover the canonical projection/durability mapping, ordered
  append/read, terminal-only stream-health coalescing, and graceful drain. Do
  not add an idempotency subsystem merely for a test.
- A migration test proves the 12A-to-12B upgrade and downgrade.

## Slice 12C: FastAPI Runs API and SSE

Status: implemented; depends on Slices 12A and 12B.

Minimum deliverable:

- Add FastAPI and build exactly the HTTP routes in
  `web-control-plane-architecture.md`; do not add convenience endpoints.
- At POST ingress, resolve and parse once, persist before launch, and
  call the injected `RunLauncher`.
- Keep API workers stateless. Stop changes durable state; no API process reaches
  into a local worker task.
- For queued stop, commit the API-owned terminal run transition and terminal
  lifecycle event atomically, then publish the durable Redis wake-up. Idempotent
  stop must not append a second terminal event. Slice 18 supersedes the original
  launch-failure behavior: delivery outages leave a durable queued retry.
- Implement the canonical durable-only replay/subscription/recheck SSE sequence.
  Decode the strict decimal durable-wake frame at the Redis adapter boundary and
  expose required-ID `PersistedDurableEvent` on the SSE route in OpenAPI. Keep
  optional-ID `DurableEvent` at the pre-persistence write boundary. Live chart
  frames remain Slice 12E scope.
- Return durable history as newest-first cursor pages with strict default and
  maximum limits, and read SSE replay backlogs in bounded batches. Add the
  composite per-run event cursor index in one migration.
- Keep `RunRead` at the exact durable run-row contract; Slice 12E first adds
  event-derived equity summary fields.
- Export OpenAPI deterministically without starting a server. Running
  `uv run python -m api.http.openapi` writes the canonical
  `backend/contracts/openapi/control-plane.json` artifact.
- Use FastAPI's built-in request errors and a small 404 detail.

Do not add authentication, users, CORS for a separate production origin,
generic pagination/filter frameworks, custom problem details, database-polling SSE
fallback, caching, WebSockets, or live-mode fields.

Acceptance:

- API tests cover launch, unknown definitions, list/detail, and idempotent
  queued/running stop. Queued stop writes exactly one terminal event; running
  stop leaves terminal event ownership with the worker.
- An ingress test proves requests violating the product-spec **Trust Boundary**
  are rejected without persisting a run.
- A launcher failure preserves the committed queued run for bounded recovery
  (Slice 18 supersedes the original terminal launch-failure behavior).
- One PostgreSQL+Redis integration scenario injects a durable event in the
  replay/subscribe handoff and proves the architecture-owned delivery guarantee,
  ending after the terminal event.
- A stream reconnect uses the durable cursor; a malformed durable-wake frame is
  dropped at Redis ingress; disconnect releases resources. Event pages enforce
  their bounds and an SSE backlog is read in bounded ordered batches.
- Health returns the architecture-owned success response only when PostgreSQL
  and Redis are ready and otherwise returns the sanitized `503`.

## Slice 12D: Static SvelteKit Launch and Run UI

Status: done; depends on Slice 12C.

Minimum deliverable:

- Create a client-rendered SvelteKit TypeScript application using
  `adapter-static`.
- Generate the Fetch client and TypeScript types from FastAPI OpenAPI with
  `@hey-api/openapi-ts`; commit deterministic artifacts and a drift check.
- Use the generated client for every ordinary request. Add one small handwritten
  EventSource adapter using the generated durable-event types; Slice 12E extends
  it for live chart and stream-health frames.
- Render launch inputs from JSON Schema with Ajv feedback and only the widget
  kinds owned by the catalog contract. Bot-managed/absent selectors are
  explanatory and omitted from submission.
- Implement the home, launch, and run-detail product outcomes. Until Slice 12E,
  run detail may show durable progress text/tables and a simple chart placeholder.

Do not add SSR, SvelteKit server routes/actions, auth/account/payment UI,
handwritten HTTP models, generalized form/plugin systems, charts, delete/rerun/
schedule/pause/resume controls, or frontend state persistence beyond the run
cursor.

Acceptance:

- One metadata-driven form test covers an ordinary field, exact decimal string,
  bot-managed omission, and wallet widget submission.
- Adding a test catalog definition composed of supported fields/widgets requires
  no launch-page branch.
- Reload hydrates HTTP state before SSE continuation and every public lifecycle
  state has a readable label/action state. It loads only the newest event page,
  fetches older pages on demand, and does not retain an SSE connection after a
  terminal lifecycle state.
- CI regenerates the client, fails on drift, and type-checks with no handwritten
  ordinary fetch contract.

## Slice 12E: Browser Dashboard Parity

Status: implemented; depends on Slices 12B through 12D.

Minimum deliverable:

- Follow the existing terminal-observability behavior and the architecture's
  single Chart Data Flow contract.
- Add the canonical `LiveChartEvent` variants, ephemeral
  `LiveStreamHealthEvent`, their `LiveRunEvent` union, and the `chart.sample`
  durable event. Extend the SSE route's OpenAPI schemas and the Slice 12D
  EventSource adapter, and send live frames without an SSE cursor.
- Extend `RunRead` with nullable `latest_equity` and `equity_status` derived
  from the latest durable `chart.sample`; do not persist summary columns.
- Expose nullable `latest_runtime_failure` from the latest durable
  `run.failure` so bounded run summaries can present the same failure evidence
  without fetching each run's event history; do not persist a run summary
  column.
- Extract only pure constants/functions/models that now have both terminal and
  web consumers into dependency-light `polybot` owners. Keep equity valuation
  in `polybot.performance`; keep Rich and ECharts out of shared code.
- Publish chart frames every 250 ms, publish only the latest stream-health state
  every second, and append the durable chart sample every second. Never persist
  individual or periodic live-health frames; retain the existing one terminal
  durable health summary. Graceful shutdown also appends one final chart sample
  before that health summary and the terminal lifecycle event.
- On reload, chart only the durable samples present in the bounded event pages
  the browser has loaded. Older-page requests may expand history, but retain at
  most the shared `MAX_CHART_HISTORY_POINTS` (currently 720) newest durable
  samples and never auto-fetch the complete run.
- The backend owns one SQL event-selection policy for history and SSE. Default
  activity selects order outcomes, errors/warnings, lifecycle changes, and
  settlements with paper positions. Diagnostics selects other non-chart events.
  Apply selection before LIMIT, not to an already-paginated result.
- Load dashboard history independently with a dashboard view. Chart samples never
  occupy activity pages. One SSE connection delivers activity and named dashboard-only
  durable frames alongside live dashboard updates, with shared reconnect IDs.
- Pages include a run-wide snapshot watermark. Hydration replays from the smaller
  activity/dashboard watermark and suppresses already-hydrated deliveries by channel.
  Diagnostics switches rehydrate the selected view before replacing the active stream;
  failed switches retain the previous feed and chart history stays intact.
- Bound retained activity to loaded activity pages times the API default page size.
  Streaming evicts the oldest overflow and advances the older-page cursor. Reserve
  capacity during older-page requests and release it on failure. Dashboard history
  has separate older-page requests and its existing chart bounds. Persistence and
  retention are unchanged; no view auto-fetches complete run history.
- Add one thin `EChart.svelte` lifecycle wrapper and focused market, equity,
  and wallet option builders. The combined component only composes layout and
  the market/wallet toggle.
- Implement the terminal-equivalent visible and keyboard controls and responsive
  layout.

Do not create a generic chart-policy/service hierarchy, independently copy
terminal formulas into TypeScript, move rendering code into shared modules, add
alternative chart libraries, auto-drain all event pages for chart hydration, or
build history compaction/retention. When Python and TypeScript must execute the
same renderer-neutral arithmetic, both implementations consume the generated
machine-readable policy and a shared boundary fixture locks their parity. The
accepted v0 durable-chart budget is at most 86,400 scheduled sample rows per
continuously active run-day; retention is post-v0.

Acceptance:

- One shared synthetic-event scenario proves equivalent terminal/web semantic
  output for token admission, stale/gap state, markers, settlement removal,
  executable equity, and wallet buckets.
- A controlled-clock test proves chart/live-health cadence, the
  architecture-owned persistence classification, terminal-only durable health,
  bounded reload history, and live continuation.
- The run-contract test keeps the row-backed fields aligned with the table
  while proving the computed summary fields are not database columns.
- Component tests cover the thin ECharts lifecycle, toggle/navigation controls,
  and narrow/wide layout.
- Web rendering or delivery failure cannot affect the paper bot.

## Slice 12F: Compose Deployment and End-to-End Handoff

Status: implemented alongside Slice 16; depends on Slices 12A through 12E.

Minimum deliverable:

- Add the architecture-owned Docker Compose services and a one-shot Alembic
  migration command.
- Expose one same-origin frontend/API entrypoint and keep PostgreSQL, Redis, and
  Taskiq private.
- Run FastAPI with multiple Uvicorn workers and the architecture-owned default
  Taskiq concurrency.
- Add one typed startup settings model for only the deployment values named in
  the architecture.
- Document startup, migration, development, client regeneration, tests, clean
  shutdown, the private-network restriction, and capacity planning for the
  Slice 12E maximum durable chart-sample rate.

Do not add Kubernetes/ECS/Terraform, cloud discovery, auth proxies, production
TLS automation, monitoring stacks, autoscaling, backup/restore, or CI deployment
pipelines.

Acceptance:

- One Compose smoke scenario covers migration ordering, health, multi-worker API
  access to the same run, concurrency queueing, progress, Stop, reload/SSE
  reconnect, and worker-loss interruption.
- The smoke check confirms only the same-origin entrypoint is published.
- A small settings test rejects nonpositive concurrency/intervals and a lease
  that does not exceed the heartbeat.
- Existing CLI, recorder, backtester, and terminal dashboard tests remain
  independent of all control-plane services.
- The documented standalone extraction checks pass.

Delivered September 9, 2026: Compose provides the static same-origin frontend,
multi-process API, bounded Taskiq concurrency, private PostgreSQL/Redis and a
one-shot forward migration. Startup settings and the disposable Compose/browser
rehearsal cover the acceptance above. Worker-loss acceptance invokes the existing
lease reconciler explicitly at that checkpoint; Slice 18 now supplies the recurring recovery scheduler.
Slice 16 owns the additional TLS/release work and the combined review record below.

## Slice 13A: Framework-Derived Trigger Nodes

Status: implemented historically and superseded by Slice 13B; depends on Slices
12A through 12E. This section records the trigger-only Slice 13A contract. The
current alpha contract is Slice 13B, which removes version fields, admits marked
computed outputs, functional nodes, and edges, and requires recreating the
disposable control-plane database.

Minimum deliverable:

- Keep one `node-based-bot` catalog definition whose launch schema contains
  user-configured market slugs and a typed `node_graph` widget. Extend only this
  definition's descriptor with a generated `GraphNodeCatalog`; `input_schema`
  remains exclusively the launch-input schema.
- Discover every async `BaseBot` method beginning with `on_`, in class-definition
  order. Resolve postponed annotations, require `BotContext` plus zero or one
  dataclass payload, fail catalog construction on unsupported signatures, and
  ignore hook return annotations. Do not include stream-planning or backtest
  query methods.
- Derive payload-field descriptors from existing dataclass annotations through
  Pydantic `TypeAdapter`. Recurse into ordinary nested dataclasses, stop at list
  and tuple boundaries, and preserve scalar type, enum schema, nullability, and
  collection information. Do not maintain a Python or TypeScript field list or
  expose methods and computed properties.
- Expose the opaque context output as `context`. Persist selected event outputs
  as structured field-path segments; derive handles as
  `field:<dot-joined-path>` and labels as
  `<PayloadType>.<dot-joined-path>`. Do not expose a whole-event output.
- Replace graph v1 with trigger nodes only. Node data contains a supported
  `hook_name` and unique `selected_output_paths`; each hook may occur once.
  Payload-less hooks accept no selections. Keep `edges` in the graph snapshot
  but require it to be empty. Reject unknown hooks, paths, duplicate selections,
  payload mismatches, transient fields, invalid positions, and excessive nodes
  at launch ingress.
- Seed the starter graph with one `on_book` trigger and `BookSnapshot.bids`
  selected.
- Build the Svelte Flow palette, trigger labels, context handle, selectable
  field handles, and node renderer entirely from catalog metadata. Disable hooks
  already present, preserve complete graph-node data while stripping only
  Svelte Flow state, and disable connection creation until processing nodes
  exist.
- Validate once at launch ingress and persist the exact immutable graph in the
  existing `PaperRunConfig` JSONB snapshot. Add no table, column, endpoint,
  evaluator, compiler, broker integration, or worker behavior.
- Continue running the paper worker with a plain non-trading `BaseBot`. The
  catalog shows `on_fill` because it is a framework lifecycle hook, but no graph
  trigger is dispatched and no graph node can submit or influence an order.
- Regenerate OpenAPI and frontend types from the Pydantic contracts. Update the
  architecture, control-plane specification, README, and bot-author guide to
  describe all lifecycle hooks and `on_book`'s dispatch-control return.

Do not add graph execution, loop/filter or other processing nodes,
collection-element paths, edges, trading semantics, live mode, auth, tenancy,
sharing, reusable user definitions, graph editing after launch, or destructive
cleanup.

Acceptance:

- Backend tests cover deterministic hook discovery, postponed annotation
  resolution, opaque context, ignored return values, unsupported signatures,
  and exact derived fields for book, gap, wallet-trade, fill, and resolution
  payloads. Collections expose `bids` and `asks`, never element fields such as
  `bids.price`.
- Graph validation covers the starter graph, unique node and hook identities,
  valid and invalid paths, duplicate selections, payload-less hooks, forbidden
  edges, transient fields, bounded positions, and graph-size limits. Generated
  parity cases keep the browser's save/response validator aligned with the
  Python topology owner for valid branches, input cardinality, scalar
  compatibility, and terminal-action reachability.
- Catalog, API, and PostgreSQL tests prove graph metadata appears only on the
  node-based definition, exact snapshots survive launch and JSONB round trips,
  invalid hooks or paths enqueue no work, and worker behavior remains
  graph-independent and non-trading.
- Frontend tests prove the palette and labels are metadata-driven, used hooks
  become unavailable, field selection creates the expected structured paths and
  handles, context is always present, no whole-event output exists, transient
  Svelte Flow state is removed without dropping trigger data, submissions and
  definition resets are exact, schema feedback remains intact, and connections
  are disabled.
- `uv run pytest`, `npm run generate:check`, `npm run check`, `npm test`, and
  `npm run build` pass.

## Slice 13B: Alpha Graph Contracts and Functional Nodes

Status: implemented; depends on Slice 13A. This slice supersedes the definition-
version and graph-schema-version requirements in earlier control-plane slices.
The control plane is still an alpha product with a disposable database, so it
keeps one current code-owned contract instead of compatibility layers.

Minimum deliverable:

- Remove definition versioning from the complete control-plane boundary:
  `DefinitionVersion`, catalog-entry and descriptor versions,
  `LaunchRequest.definition_version`, run-row and `RunRead.definition_version`,
  stale-version handling, generated frontend fields, and their tests. Remove
  `NodeGraph.schema_version` as well. Rewrite the alpha Alembic history and
  recreate the disposable control-plane database; do not add a compatibility
  migration, legacy graph decoder, or dual-version union.
- Keep `definition_id` as the sole stable catalog identity. A queued run still
  persists its complete immutable `PaperRunConfig`, including its exact graph,
  but code and stored alpha data are expected to move together until a future
  stabilization slice deliberately reintroduces versioning.
- Add framework-owned `BookSnapshot.best_bid` and `BookSnapshot.best_ask`
  computed properties. `best_bid` is the highest bid and therefore the
  executable SELL side; `best_ask` is the lowest ask and therefore the
  executable BUY side. Each returns `BookLevel | None` without changing the
  stored `bids` or `asks` source of truth.
- Introduce one narrow, explicit framework marker for graph-safe computed event
  outputs. Extend trigger discovery to include only marked, zero-argument,
  annotated computed properties in addition to dataclass fields. Expose
  `best_bid.price`, `best_bid.size`, `best_ask.price`, and `best_ask.size` through
  the existing recursive field descriptor logic, propagating parent nullability
  to each nested path. Do not automatically expose every property or method, and
  do not expose `midpoint()` or collection element paths.
- Expand the code-owned `GraphNodeCatalog` and graph-node discriminated union
  with exactly four node kinds: trigger, constant, comparison, and broker
  action. Keep the frontend palette, labels, handles, controls, and validation
  driven by this catalog and generated OpenAPI types; do not add a parallel
  TypeScript registry.
- Supersede Slice 13A's `selected_output_paths` trigger-node state. Render every
  catalog-described scalar trigger handle continuously and use drawn edges as
  the sole persisted record of which outputs a graph consumes. Collection
  fields remain visible metadata but cannot connect until collection processing
  is introduced.
- Support typed scalar constants for boolean, integer, decimal, and string
  values. Preserve decimals as exact strings at the wire boundary. A constant
  has one typed output and no inputs.
- Support binary comparisons with `equal`, `not_equal`, `less_than`,
  `less_than_or_equal`, `greater_than`, and `greater_than_or_equal`. Equality
  operators accept compatible equal scalar types; ordering operators accept
  matching integer or decimal inputs. A comparison has exactly two required
  inputs and one boolean output. Present comparison as one frontend palette
  item with a catalog-driven operator select on the node. A null input makes
  the comparison `False` rather than being coerced or guessed.
- Publish the broker action catalog from an explicit allowlist containing only
  `Broker.submit(OrderRequest) -> FillEvent`. Derive its field metadata from the
  broker signature, `OrderRequest`, `Side`, and their annotations rather than
  copying order fields into graph-only contracts. Do not discover or expose
  `cancel_all` merely because it is a broker method.
- Present BUY and SELL as two fixed-side variants of the same submit-order
  action. Each action has a required boolean `enabled` input plus required
  `token_id`, `price`, and share `size` inputs; the existing optional
  `market_slug`, `condition_id`, `source_id`, and `reason` inputs remain
  optional. The action is a sink in this slice; do not expose `FillEvent`
  outputs yet.
- Extend `GraphEdge` with explicit source and target handle IDs. Validate once
  at launch ingress that node IDs, edge IDs, nodes, handles, input cardinality,
  scalar types, nullability metadata, and directions are valid;
  each non-optional input has exactly one source; the graph is acyclic; and
  every action has exactly one upstream trigger ancestry. Constants may be
  shared within that trigger branch. A nullable source may feed a required
  input, but its missing runtime value must fail closed as specified in Slice
  13C. Reject disconnected processing/action nodes and cross-trigger joins.
- Enable Svelte Flow connections and add focused renderers/editors for the
  three new node kinds. Keep the starter graph non-trading, but add one complete
  test fixture and frontend scenario for
  `on_book.best_ask.price <= constant -> BUY`, with token ID and limit price
  taken from the same `BookSnapshot` and order size supplied by a decimal
  constant.
- Persist the validated graph exactly in `PaperRunConfig`. The worker remains
  non-executing in this slice; Slice 13C first interprets it.

Do not add graph evaluation, loops, collection iteration, arithmetic, string
composition, state, position reads, cooldown/debounce, action-result outputs,
live mode, user code, plugins, reusable graph definitions, or graph editing
after launch.

Acceptance:

- Contract, API, PostgreSQL, OpenAPI, and frontend tests prove no definition or
  graph schema version field remains and the recreated alpha schema has no
  `definition_version` column.
- Framework tests prove best bid/ask selection for sorted and unsorted levels,
  empty-side nullability, and no duplicated stored quote state. Catalog tests
  prove only explicitly marked computed outputs are exposed.
- Catalog and ingress tests cover every constant/comparison/action descriptor,
  exact decimals, BUY/SELL derivation from `Side`, rejection of unallowlisted
  broker methods, handle existence, type compatibility, required input
  cardinality, cycles, disconnected nodes, and cross-trigger joins.
- Frontend tests construct, connect, persist, reload, and reset the threshold
  BUY fixture entirely from backend metadata without losing node data or
  retaining transient Svelte Flow state.
- Worker tests continue to prove that a stored action graph submits no order in
  Slice 13B.

## Slice 13C: Event-Driven Graph Evaluation and Paper Actions

Status: implemented; depends on Slice 13B.

Minimum deliverable:

- Implement a concrete `NodeBasedBot(BaseBot)` for the node-based catalog entry.
  Compose a focused graph evaluator inside this bot; do not add evaluator state
  or graph-specific behavior to `BaseBot` and do not make `polybot` import the
  control-plane package.
- Let the node-based catalog entry construct its bot from the already-decoded
  `PaperRunConfig` so the immutable graph reaches `NodeBasedBot` without adding
  graph fields to the general `BotConfig` or branching on definition IDs in the
  worker.
- Compile the already-validated graph once when the bot is constructed into
  dependency indexes and a deterministic topological order. Runtime evaluation
  trusts this internal compiled shape and does not repeat Pydantic request
  validation.
- For each accepted `BaseBot` hook invocation, create one ephemeral evaluation
  frame containing `BotContext` and that hook's payload, then evaluate only the
  downstream branch for the matching trigger. Resolve selected dataclass and
  marked computed-property paths, evaluate each reachable pure node at most
  once, and invoke each reachable action at most once in deterministic graph
  order.
- Treat evaluation as a bounded event-driven DAG pass. Do not loop until values
  stabilize and do not model the evaluator as a state machine. Constants and
  comparisons are pure; the only MVP side effect is the terminal broker action.
- Run an action only when `enabled` is exactly `True` and every required order
  input resolves to a non-null value. A missing best bid/ask or other nullable
  required value skips the action with a stable graph skip reason; it never
  substitutes zero, a stale value, or another book side. Construct the existing
  `OrderRequest` and await `ctx.broker.submit()` so all paper validation,
  fill-time books, slippage, fees, portfolio transitions, observability, and
  future paper/live contract parity stay behind the broker boundary.
- Execute on every matching accepted event. If the comparison remains true for
  ten accepted book updates, a reachable action may submit ten orders. Do not
  add rising-edge memory, implicit dedupe, position checks, cooldowns, or
  in-flight suppression; those are explicit future graph nodes and policies the
  operator must add when they exist.
- Keep hook semantics unchanged. `on_book` returns `None` after graph handling;
  graph actions do not fabricate a `DispatchSkipReason`. A returned
  `FillEvent` remains broker/observer output and does not recursively dispatch
  the graph's `on_fill` trigger in this slice, matching the current paper
  runtime contract.
- Keep the web node-based bot paper-only. Change its catalog presentation from
  non-trading observer to paper-trading bot only when this evaluator lands;
  preserve every existing web trust-boundary restriction and all live-execution
  gates.

Do not add fixed-point evaluation, cycles, persistent evaluator state,
position/cash query nodes, once/cooldown/debounce nodes, concurrency between
actions, compensation, order cancellation, fill-output chaining, live mode,
backtest controls, or a generic workflow framework.

Acceptance:

- Unit tests prove deterministic topological evaluation, lazy per-trigger
  branches, one evaluation per reachable node, exact path extraction for
  `best_bid`/`best_ask`, and stable skips for nullable required inputs.
- Comparison tests cover every operator, exact decimal behavior, false
  conditions, and null inputs evaluating `False` without coercion.
- Broker-action tests prove exact `OrderRequest` construction for BUY and SELL,
  optional identity propagation, broker rejections remaining ordinary
  `FillEvent` results, and no direct PaperBroker or Polymarket SDK dependency in
  the evaluator.
- A repeated-event test proves two matching accepted book events produce two
  broker submissions. A false event between them adds no hidden rearming
  semantics because the evaluator retains no cross-event state.
- Worker and PostgreSQL integration tests launch the node-based definition from
  its persisted graph, observe a paper order/fill through the existing event
  path, and prove non-node definitions remain unchanged.
- Safety tests prove missing/stale/malformed/crossed books are still rejected by
  existing runtime or broker boundaries, missing graph values cannot submit,
  web launches cannot select live mode or credentials, and live gates remain
  unchanged.
- `uv run pytest`, `npm run generate:check`, `npm run check`, `npm test`, and
  `npm run build` pass.

## Slice 13D: Saved Bots and Complete Run Snapshots

Status: implemented; persistence simplified with user approval on September 10.
Supersedes the original template-copy and immutable graph-revision design.

- Each `bots.config` JSONB document contains paper settings and the complete graph.
- Each run stores an independent deep copy in `runs.config_snapshot` at creation.
- Keep the bot foreign key for ownership, soft deletion and retained history.
- Remove template/revision tables, references, resource accounting and edit caps.
- Rewrite the sole undeployed migration `0001`; the user authorized losing all local
  data. No backfill, compatibility migration, or automatic deployed reset is added.

## Slice 13E: Atomic Saved-Bot APIs and Snapshot Execution

Status: implemented; updated by the same configuration simplification.

- Create and update accept complete inputs plus graph and commit them atomically.
- Lock the saved bot while copying its complete config into a run; commit before
  enqueueing. Retain launch idempotency, admission and account ownership.
- Workers read the run snapshot, including its graph, without graph-revision lookup.
- Missing, malformed, required or forbidden graph state fails closed.
- Remove template and revision endpoints; regenerate OpenAPI and frontend contracts.

## Slice 13F: Unified Node-Bot Browser Workflows

Status: implemented; updated by the same configuration simplification.

- Create a bot directly from settings and graph in one request; starter examples
  and copying another bot's graph remain independent draft operations.
- Save settings and graph together; keep Run disabled while changes are unsaved.
- Show the executed graph from the run snapshot without revision numbering.
- Fit graphs after all nodes are measured when entering a bot or run. Historical
  graphs support pan, zoom and Fit View while remaining locked against edits.
- Present run configuration in the builder's field order and responsive layout,
  with plain values and readable selection lists instead of graph JSON.
- Split run detail into Live data (initially selected) and Configuration tabs.
  Live data presents executable equity, market prices, Events, and timing;
  Configuration presents the immutable executed graph and settings, initially
  expanded. Both tabs preserve disclosure state and streaming continues when
  viewing settings; hidden chart shortcuts are inactive.
- Events starts collapsed and opens to the right of the charts, including stream
  health and paginated progress events; charts narrow to accommodate it. On
  mobile Events opens below the charts.
- Show active, queued and saved-bot allowances only; no template counter or limit.

Acceptance covers exact JSON and decimal preservation, independent copied bots,
queued-run isolation from edits, atomic invalid-save rejection, concurrent
edit/launch serialization, duplicate launches, worker failures, soft deletion,
account isolation, fresh migration parity, frontend workflows and generated contracts.

Documentation-drift audit: current README, architecture, product specification,
author guide, graph authoring and lifecycle documentation describe one bot
configuration and independent run snapshots. Historical acceptance notes for later
slices record their original verification; references there to templates or graph
revisions are superseded by this simplification. No Polymarket protocol changes.

## Market Search and Multi-Selection Follow-Up

Status: implemented; extends the existing saved-bot creation/edit workflows.

- Add typed, bounded market search and exact selected-slug lookup endpoints,
  backed by a lifespan-owned official async SDK adapter and internal dataclasses.
- Normalize SDK metadata at the adapter boundary, preserve search relevance,
  exclude unavailable suggestions, and fail closed on conflicting metadata.
- Validate newly selected markets before saving without requiring unchanged
  historical selections to remain available. No database migration or runtime
  trading behavior changes.
- Replace market-slug free text with the accessible multi-select in both forms,
  including debouncing, request cancellation, selection hydration, keyboard
  controls, clear recovery states, and generated frontend contracts.
- Verify adapter, endpoint, save-validation, response-validation, and component
  contracts, plus the existing backend/frontend regression suites and build.

Documentation verification exception: the user explicitly authorized official
web docs and pinned SDK source instead of the unavailable PolymarketDocs MCP.
See `docs/api-notes.md` for evidence and the live-request TLS limitation.

Documentation-drift audit: README, package architecture, API notes, bot-author
guide, web architecture/specification, endpoint inventory, and generated
OpenAPI/client fixtures describe the selector consistently. Earlier numbered
slice scopes remain historical; this follow-up does not alter them.


## Saved-bot deletion follow-up

Status: implemented September 10, 2026; extends Slices 13D–13F with the approved
soft-delete behavior.

- Require all runs to be terminal before deletion; include queued and stopping
  states in the rejection guard. Never implicitly stop a run when deleting.
- Include nullable `bots.deleted_at` in the sole initial migration `0001`.
  The approved undeployed/local consolidation requires recreating old databases.
  During normal use, soft deletion retains configurations and run snapshots.
- Add owned `DELETE /bots/{bot_id}` with `204` success, `409` for nonterminal runs
  and `404` for missing, foreign or already deleted configurations. Serialize
  deletion with launches and edits on the bot row; reject stale launch snapshots.
- Hide deleted bots from configuration reads/lists, editing, graph copying,
  and launches. Exclude them from saved-bot usage.
- Keep historical run reads/lists, graphs and events under their existing ownership
  and retention rules. Expose `RunRead.bot_deleted` for the historical-page label.
- Add a confirmation/cancel flow on bot detail, explain active-run conflicts, block
  conflicting UI actions while deleting, and return to the workspace after success.

Acceptance covers every run state, ownership isolation, hidden configurations,
preserved graph/event history, saved-bot usage, launch/delete races in both orders,
fresh schema creation, repeat upgrades on populated data, cancellation, errors/retry
and the generated client’s
empty deletion response. Chromium acceptance exercises the real session, queued-run
rejection, stop, confirmation, hidden configuration and retained history after reload.
No Polymarket protocol behavior changes or MCP checks apply.

Run focused backend coverage with `uv run pytest
backend/tests/control_plane/test_bot_deletion.py
backend/tests/control_plane/test_initial_migration.py` and disposable PostgreSQL/Redis
settings from the README. Run browser acceptance with `npm --prefix frontend run
test:e2e -- --grep "deleting a bot requires"` and its separate disposable browser
service settings. Frontend regressions use `npm --prefix frontend test`.

Documentation-drift audit: README, architecture, bot-author guide, web specification,
web architecture, generated OpenAPI/client and this plan describe the same behavior.
Historical slice scopes above remain historical; this follow-up supersedes their
bot-deletion exclusions.

## Slice 14: Paper graph MVP in two phases

The [MVP checklist](graph-mvp-plan.md) is the single source of completion status.
Its individually assignable units are executed in order: phase 1 owns backend
catalog/schema declarations, frontend representation/persistence, and the
unsupported-execution boundary; phase 2 owns evaluation, portfolio integration,
event controls, diagnostics and decision preview. Check a unit only after its
implementation, relevant tests and documentation updates pass.

This slice supersedes the four-node/scalar, null-comparison-false, action-only
terminal, stateless-evaluator and unavailable-context constraints recorded in
Slices 13A–13C. Complete configurations and immutable run snapshots follow the revised Slices 13D–13F.
The graph interface now has Number, Boolean and Text, with exact decimal strings
for Number. See [graph behavior and authoring](graph-node-mvp.md) for the complete
operation set, arithmetic policy, context API, signal-consumption rules, bounds,
preview isolation and example strategies. Existing development data is disposable;
no compatibility decoder or version migration is introduced. Public deployment,
tenancy and live execution are not part of this slice.

### Random debugging starting point follow-up

The graph catalog now includes a **Random** example and **Random Number** operation.
The node uses `ctx.rng` once per enabled, eligible evaluation, preserves seeded
sequences, and shares its Number across consumers. The example combines it with
existing per-token cooldown, portfolio, comparison and broker nodes: five-share
entries while flat and exits of actual held shares, with an editable 50% trade
probability and five-second cooldown. Paper execution and chart events use their
existing paths. This adds no external protocol, live trading or migration.

Validation covers seeded/gated draws, invalid books, missing portfolios, complete
and partial paper fills, graph-contract parity and frontend metadata rendering.
Documentation-drift audit: graph authoring, bot-author guide, catalog examples and
generated backend/frontend contracts describe the same operation and defaults.

## Main-module review follow-up — September 2026

This maintenance pass applies the reconciled main-module style review across the
existing framework, recording/replay, graph, worker, and frontend slices. It adds
no product slice, database migration, archive-format version, live capability,
or external transport. Generated contracts and supporting tests are updated only
where those existing contracts changed.

The implementation groups related fixes around shared contract owners, explicit
archive/replay collaborators, adapter normalization, graph ingress, event
projection, and presentation ownership. Correctness changes cover settlement and
continuity during paper latency and final input reads, recording capture acquisition
and pre-baseline termination gaps, failed worker
monitoring, graph-save response validation, preview semantic validation, wallet
identity, contradictory terminal metadata, duplicate timeline delivery, and
Decimal-context-independent fees. Regression coverage also includes fully closed
followed-wallet P&L, event/settlement invariants, selector cardinality and union,
global-gap baseline invalidation, and run-page stop/stream/pagination behavior.

Documentation-drift audit: architecture, API notes, control-plane architecture,
and graph authoring now describe the changed owners and behavior. Numbered slices
remain historical; their public entrypoints and paper/live parity are preserved.
See the repository tests and generated contract checks for executable evidence.

## Slice 15: Users, Authentication, and Resource Ownership

Status: implemented. Uses the existing saved-bot/run workflows in
Slices 13D-13F and preserves the current Slice 14 graph behavior.

This slice adds a simple, application-wide user boundary to the paper control
plane. Email/password registration without email verification is agreed scope.
The [product extension](web-control-plane-spec.md#slice-15-users-and-private-ownership)
owns user-visible behavior; the
[architecture extension](web-control-plane-architecture.md#slice-15-identity-and-authorization)
owns the implemented technical contracts and approved policy decisions.
This slice supersedes the earlier control-plane exclusions of users and auth;
historical slice descriptions remain historical scope.

Implement 15A, then 15B, then 15C. These are incremental development units, not
independently releasable multi-user products: retain the current private access
boundary until all three pass. Do not scaffold marketplace or social-login
features in any unit.

### Slice 15A: Email/Password Accounts and Sessions

Status: implemented.

Minimum deliverable:

- Resolve and record the architecture's bounded auth-policy checkpoints before
  runtime implementation. Use maintained password/email libraries and the
  existing application database; keep identity out of `polybot`.
- Add user/session persistence, migrations, and narrowly owned auth contracts.
  Implement registration, login, logout, and current-user routes as specified
  by the architecture. Registration signs in immediately without sending email.
- Establish the shared current-user dependency and authentication gate for all
  application routes except the architecture's explicit public allowlist.
- Implement server expiry/revocation, cookie handling, CSRF protection,
  throttling, safe errors/logging, and appropriate async password hashing.
- Regenerate OpenAPI and the frontend client for the new auth surface.

Acceptance:

- Registration/login use the same email normalization; concurrent equivalent
  registrations cannot create two accounts. Invalid and excessive inputs are
  rejected without storing or leaking secrets.
- Correct passwords authenticate; wrong passwords and unknown emails produce
  the same login failure contract. Only password hashes and token digests are
  persisted; public responses contain neither.
- Registration sends no email, calls no identity provider, and grants no
  verified-email claim. Successful signup requires no email service settings.
- Sessions work across API instances; expired, revoked, missing, and malformed
  tokens grant no access. Logout is idempotent. Auth infrastructure failure
  fails closed, and CSRF/throttling cover signup and login too.
- Route-inventory tests prove the public allowlist is explicit and all other
  application routes require authentication. This unit alone does not claim
  per-user resource isolation.

### Slice 15B: Private Bot and Run Access

Status: implemented; depends on 15A.

Minimum deliverable:

- Resolve the existing-data checkpoint before migrations: an explicitly
  authorized alpha reset or an explicit owner backfill, as defined in the
  architecture. Preserve existing bot/run foreign-key invariants.
- Add bot ownership and scoped queries. Assign ownership only from the authenticated user; no owner-edit or
  ownership-transfer endpoint exists.
- Apply one ownership rule through all bot/run and event
  paths, including copy, reference lookup, launch, stop, summary, pagination,
  and SSE. Authenticate catalogs, preview, and market endpoints too.
- Keep trusted worker execution independent of user sessions and preserve
  immutable run snapshots. Add bounded auth rechecks to SSE delivery without
  changing the durable/live stream contract.
- Regenerate affected contracts and update fixtures for private resources.

Acceptance:

- A two-user integration scenario proves private lists and denial of guessed
  foreign IDs on every read/mutation/event path. Inaccessible IDs return the
  same outcome as missing IDs; no private data or queued work escapes first.
- A user cannot read or copy another user's bot configuration, launch/stop its
  runs, or subscribe/replay its events. Configuration and graph are owned together.
- Spoofed owner fields cannot assign or change ownership.
- Runs/events inherit ownership correctly, without child user IDs.
  Authorized background runs continue after logout, while stream access ends
  within the specified bound and reconnects require a valid session.
- Migration tests cover the selected existing-data policy; ownership is
  non-null and never assigned by first signup. Historical config/graph
  snapshots, transaction locking, and paper-only launch constraints still pass.

### Slice 15C: Browser Account Flow and Complete Verification

Status: implemented; depends on 15B.

Minimum deliverable:

- Add email/password registration and login pages, current-user restoration,
  and logout in the existing application shell using generated contracts.
- Load private bots/runs only after authentication. Handle session expiry,
  resource denial, and account switching consistently across forms, copies,
  run pages, and streams. Keep account email private to the current-user UI.
- Preserve the unified bot editor, starter graphs, saved-bot launches, and
  historical run display within the user's owned resources.
- Document local account creation, auth settings, chosen migration policy,
  private deployment requirements, and the absence of password recovery.

Acceptance:

- Browser tests cover signup without a verification step, login errors,
  reload restoration, logout/expiry, safe return paths, and switching between
  two accounts without retaining private data or streams from the first.
- A complete two-account API/browser scenario proves create/edit/copy/run/stop
  and historical access stay private. Backend checks remain effective when
  requests bypass the frontend.
- Run `uv run pytest`, `npm --prefix frontend run generate:check`,
  `npm --prefix frontend run check`, `npm --prefix frontend test`, and
  `npm --prefix frontend run build`. Use disposable PostgreSQL and Redis test
  services for service-dependent acceptance; skipped integration tests do not
  establish multi-user isolation.
- Complete the documentation-drift audit across README, control-plane spec,
  architecture, this plan, and generated contracts before marking delivered.

Explicit exclusions: verification mail, password recovery, account editing,
social login/account linking, MFA, organizations, role/permission frameworks,
billing, quotas, ownership transfer/deletion, marketplace tables/UI, new live
capabilities, and public deployment. A later marketplace slice may publish and
copy snapshots; it must not widen this slice's private-run access policy.

Implementation: `api.auth` owns identity, secrets, sessions, ingress protection
and bounded SSE rechecks. Mandatory bot owner keys scope private resources;
run/event ownership remains inherited. The static browser restores users
before loading private pages and clears views/streams on logout, expiry or account
switch. Auth settings and the one-time local database reset were explicitly approved.
The consolidated initial migration creates mandatory ownership directly; it does
not backfill or guess owners for old local data.

Verification: real PostgreSQL/Redis acceptance covers two accounts, every private
resource route, guessed/nested foreign IDs, concurrency, session rotation/revocation,
CSRF, throttling, infrastructure failures and the migration policy. Chromium covers
registration without verification, login failures, reload, create/edit/copy/launch/
stop/history, account switching, session expiry and safe return paths. Its only
service fixtures are market discovery and execution delivery; identity/persistence/
SSE/stop behavior use application code. Existing worker and snapshot regressions
remain part of the full suite. The style-review follow-up gives tokens, cookies,
auth ingress, persistence, SSE replay/subscription and browser session lifecycle
explicit owners. Generated contracts include auth error responses and shared
runtime HTTP policy. Added regressions cover config rejection, stale restoration,
malformed stored hashes, active-stream revocation and schema parity; acceptance
CI uses real services and rejects skipped tests. The final review also centralizes
typed browser session state, HTTP outcome adapters, owned snapshot queries and
terminal stream completion, and validates aware SSE timestamps. Disposable harnesses validate
local targets and clear only authentication throttle keys.

Final documentation-drift audit: README, product specification, both architecture
references, this plan, OpenAPI and generated frontend/runtime contracts describe
implemented Slice 15 behavior. Earlier numbered slice exclusions remain historical.
The identity change adds no Polymarket protocol or transport behavior and requires
no PolymarketDocs verification. No marketplace, live mode, recovery mail, account
editing, public deployment or organization features were added.

## Public Paper-Trading Beta Roadmap

Status: Slices 16–23 delivered; operational public-opening gates remain. The user approved the eight readiness areas below as the next
direction, replacing the marketplace proposal. These slices deliver a public
paper-only service; they do not authorize deploying it or changing production
state as part of this planning task. Marketplace work is deferred.

Complete Slice 12F, then Slices 16–23 in order. Each slice names its dependencies;
independent work may proceed once those prerequisites are met, but open signup
requires acceptance for all eight. Keep incomplete deployments behind the existing
private access boundary. Live trading, billing and the later product ideas at the
end are not launch prerequisites and must not be scaffolded by these slices.

This plan owns scope, minimum deliverables and acceptance. During each slice,
record adopted user behavior in `web-control-plane-spec.md` and technical
contracts in `web-control-plane-architecture.md` before code depends on them.
Earlier slice exclusions describe historical scope; they do not prohibit the
explicitly planned extensions below. Preserve standalone `polybot` isolation,
private per-user resources and paper-only execution.

Exact hosting/provider choices, resource limits, retention periods, recovery
targets and account policies remain implementation checkpoints. Resolve only the
choices needed by the active slice; do not interpret approval of this roadmap as
approval of a particular paid service, destructive migration or public deployment.
Use forward migrations that preserve existing accounts and history.

## Slice 16: Production Deployment

Status: implemented; depends on Slice 12F and Slice 15.

Minimum deliverable:

- Build on 12F's Compose, same-origin entrypoint, private infrastructure and
  migration foundation. Add the production configuration needed for HTTPS,
  trusted proxy handling, secure cookies and server-side secret injection.
- Establish a repeatable release process with immutable build identifiers,
  migration ordering, health checks and a documented rollback procedure. Keep
  existing test CI and add deployment checks rather than replacing it.
- Separate development/test and production configuration. Reject unsafe public
  settings and keep PostgreSQL, Redis and workers inaccessible from the Internet.
- Document the selected hosting topology and capacity assumptions. Gate public
  access until all readiness slices pass; deployment infrastructure alone does
  not make the product ready for open signup.

Acceptance:

- A staging smoke test covers HTTPS login, resource isolation, launch, Stop,
  refresh and SSE reconnect through the real reverse proxy.
- Startup fails clearly on missing/invalid required configuration; secrets do
  not enter frontend builds, images, exported contracts or logs.
- A release and rollback rehearsal verifies application/schema compatibility;
  rollback never assumes a destructive database downgrade is safe.
- Only the intended entrypoint is reachable, and database migration failure
  prevents activation of an incompatible release.

Explicit exclusions: Kubernetes, autoscaling and multi-region deployment unless
a demonstrated requirement is approved. Backups belong to Slice 21; operational
alerts to Slice 20. This slice extends 12F's intentionally private deployment
scope without rewriting its original deliverable.

Delivered September 9, 2026. The selected single-host Compose topology and
capacity assumptions, runtime secret files, exact schema compatibility policy,
immutable release manifests, private TLS entrypoint, release/rollback procedure
and local development separation are recorded in `beta-deployment.md`.
Release activation waits for API and proxy readiness. A failed migration keeps
application processes and ingress stopped; rollback checks compatibility and
never downgrades the database. Existing infrastructure containers are preserved.
No hosting provider was purchased and no public or production deployment occurred.

Verification: disposable PostgreSQL/Redis, real Taskiq delivery and Caddy TLS
passed release/rollback and migration-failure rehearsals, multi-user isolation,
worker concurrency/queueing, queued and active Stop, reload, monotonic SSE
reconnection, worker-loss interruption and credential-log checks. The separate
acceptance image replaces only market discovery/runtime inputs. Chromium also
passed the private HTTPS workflow. The ordinary Python, frontend, generated
contract, package build and multi-account browser checks passed. Test commands
remain in README and the deployment runbook.

The rehearsal exposed and fixed a hydration race: a lifecycle event committed
between the run read and event-page read could leave stale status behind the
reconnect cursor. A focused browser-state regression covers the refreshed status.

Review exception explicitly approved by the user: all 51 reviewer roles were
launched; 15 completed and 36 failed when workspace credits ran out. The user
authorized finishing with parent review and tests without further subagents.
Both reported findings were fixed (blocking secret-file IO and the duplicated
heartbeat test literal), and the parent completed the remaining review and
documentation/contract audit. The full 51-agent review is not claimed complete.

Final documentation-drift audit: README, product specification, both architecture
references, this plan and the deployment runbook match the delivered private
behavior. API/exported contract shapes did not change and generated-client checks
passed. No Polymarket protocol, transport or SDK boundary changed, so no new
PolymarketDocs check was required. At the end of Slice 16, Slices 17–23 remained planned work and open signup
stayed gated; subsequent delivery is recorded in each slice below.

## Slice 17: Per-User Resource Limits

Status: implemented; depends on Slice 15 and the capacity settings from Slice 16.

Minimum deliverable:

- Define a small paper-beta allowance policy: concurrent runs, queued runs,
  maximum run duration, markets/subscriptions per run and saved-resource limits.
  Add a global run/queue capacity ceiling. Choose initial values from a bounded
  load test and document them in one owning policy contract.
- Enforce admission and capacity reservations atomically across API/worker
  instances. Derive the account from authenticated ownership, never request data.
  Apply shared infrastructure limits to expensive requests and open streams too.
- Provide bounded queueing with a documented fair admission rule. Explain
  allowance/capacity failures in the browser, and show users their own usage.
- Enforce run-duration expiry server-side and release reservations on terminal
  transitions through one accounting boundary. Slice 18 adds worker-loss recovery.
- Define the per-account retained-history allowance for Slice 21 to enforce;
  do not build a second retention/deletion mechanism here.

Acceptance:

- Concurrent requests and multiple API processes cannot exceed per-user or
  global reservations; one account cannot occupy unbounded queue/worker capacity.
- Stop, invalid queued snapshots and normal completion release capacity exactly once; delivery outages preserve queued reservations (Slice 18).
  Duration limits work without an open browser.
- Missing shared admission infrastructure fails closed. Responses distinguish
  invalid configuration, user allowance and temporary global capacity outcomes.
- Tests prove ownership, bounded requests/streams and correct browser feedback;
  worker-loss recovery is completed with Slice 18.

Explicit exclusions: subscriptions, billing, enterprise plans and a generic
entitlements framework. Resource controls are required even for a free beta.

The user approved initial policy values on September 9, conditional on a bounded
load test. `api.limits.policy.PAPER_BETA` owns all numeric allowances and exports
them through `/usage`; the product and architecture describe their semantics.
Queued status consumes queue capacity, and starting/running/stop-requested/stopping
statuses consume active capacity. PostgreSQL lifecycle rows are the reservations;
FIFO among eligible accounts avoids head-of-line blocking. Existing accounts and
history are preserved without a schema change. History cleanup remains Slice 21.

Bounded load rehearsal: `PYTHONPATH=backend/tests uv run python -m
control_plane.limits_load` with the disposable test-service variables. The initial
15-second run exercised the approved active-run/market/stream ceilings, synthetic
graph book hooks, real PostgreSQL durable writes/readback and Redis delivery.
It processed 22,100 books, 221 durable writes, 235 reads and 1,768 stream frames.
P95 I/O was 171.51 ms and event-loop lag 8.44 ms, both below the acceptance
thresholds owned by `control_plane.limits_load`,
and process peak RSS was 112,672,768 bytes on macOS arm64. PostgreSQL was limited
to two CPUs/1 GiB and Redis to one CPU/256 MiB; the Python process ran on the host.
This is a bounded synthetic acceptance test, not a measured vendor or production
throughput guarantee. Rehearse on the actual host before broadening these limits.
The runtime duration and future history age/count in `PAPER_BETA` remain conservative product
allowances rather than conclusions from a short throughput benchmark.


Delivered September 9, 2026. PostgreSQL lifecycle rows provide atomic account and
global reservations, with FIFO admission among eligible accounts. Shared Redis
budgets bound requests and authorized stream leases; bounded response cleanup
covers expiry, disconnect and slow clients. Run duration includes startup time;
already-expired claims cannot invoke bot hooks. Dynamic wallet-market admission
precedes strategy execution, and runtime cap failures expose a stable explanation.
The browser shows private usage and specific admission failures; bot-save retries
reuse the already-saved graph draft. Owned history reads preserve active/queued
runs alongside bounded terminal history; no history deletion was added.

Verification: all 51 registered read-only reviewers completed, reports were
reconciled holistically, and affected rules received focused follow-up reviews.
The full suite passed 1,203 Python tests, 234 frontend tests and both multi-account
browser scenarios. Type checks, generated-client consistency and Python/frontend
builds passed. The repeated bounded load rehearsal also passed (p95 I/O 163.25 ms,
event-loop lag 5.98 ms). Tests include synchronized worker processes beyond the
active ceiling, duplicate delivery, terminal release, startup expiry, dynamic
market/position caps, service failures, stream lease cleanup and browser feedback.
Use README's disposable service settings with `uv run pytest`; frontend checks
are `npm --prefix frontend test`, `npm --prefix frontend run check` and the
configured `npm --prefix frontend run test:e2e` acceptance harness.

Final documentation-drift audit: README, product specification, architecture,
bot-author guide, API notes, deployment assumptions, this plan and exported
contracts match the delivered behavior and single policy owner. PolymarketDocs
verified the existing subscription boundary; no SDK/transport exception or live
execution change was introduced. Existing accounts/history remain intact. Launch
retry idempotency and worker-loss recovery are delivered by Slice 18; retention/deletion
remains Slice 21. Open signup stays gated by the remaining roadmap.


## Slice 18: Reliable Run Lifecycle

Status: delivered; builds on Slices 16–17 and the existing run/worker lifecycle.

Minimum deliverable:

- Make user launch retries idempotent: one logical launch creates at most one
  run and capacity reservation, even after a lost response or concurrent retry.
  A deliberate new run remains possible.
- Close the gap between persisted queued runs and worker delivery. Define
  bounded recovery of stranded queue entries and safe handling of duplicate
  delivery using the existing execution claim.
- Schedule reconciliation of expired worker leases; the existing helper alone
  is not a production scheduler. Terminal state, durable lifecycle events and
  capacity release must remain consistent under retries.
- Handle worker termination, graceful deployment shutdown and dependency outages
  with explicit bounded outcomes. A dead worker cannot leave a run permanently
  displayed as running.
- End lost paper runs as interrupted. Preserve their committed history and
  explain the interruption; restarting creates an explicit new run.

Acceptance:

- Failure-injection scenarios cover API death around enqueue, lost launch
  responses, duplicate jobs, worker kill, Redis/database outages and deployment
  shutdown. Verify states/events/reservations after recovery.
- A stale worker cannot continue making accepted progress after losing execution
  ownership; recovery never creates two active executors for one run.
- Queued Stop, duration expiry and reconciliation races converge on one terminal
  outcome. Other users cannot trigger or observe private lifecycle operations.
- Browser reload and SSE reconnect show the authoritative recovered outcome.

Explicit exclusions: transparent portfolio/graph-state restoration, automatic
strategy restarts and live-trading recovery. The beta promises accurate
interruption reporting, not uninterrupted execution.

Delivered implementation and verification:

- The consolidated initial migration includes bot-scoped launch keys,
  execution tokens and delivery-attempt timestamps. Browser launch identity survives
  lost responses and reload; unkeyed legacy callers explicitly request a fresh run.
- PostgreSQL queue obligations are retried by the separately deployed recovery
  process. Conditional claims, lease-fenced writes/fills/settlements and one atomic
  terminal writer preserve state/event/capacity consistency. Interrupted runs never
  resume portfolio or graph state automatically.
- Failure-injection tests cover launch/claim concurrency, missed delivery, terminal
  rollback, expired ownership, Stop races, duration and cleanup bounds. Real database
  tests exercise successful and rejected paper fills and settlements. Browser tests
  exercise lost launch responses and deliberate subsequent launches.
- The disposable HTTPS deployment rehearsal passed PostgreSQL outage plus worker
  kill, Redis recovery, bounded graceful shutdown, single terminal history,
  reconnect/reload, release, rollback and migration refusal. No public deployment
  was performed. The complete Python and frontend suites and builds passed.
- The explicit 51-rule code-style review was reconciled holistically, with focused
  reruns after refinements. Final documentation drift audit synchronized the
  roadmap, architecture, author guide, product spec and deployment runbook;
  policy/service documentation is checked against code. No protocol behavior or
  Polymarket adapter changed, so no protocol-sensitive MCP check was required.

## Slice 19: Account Recovery and Management

September 10 local-development follow-up: explicit
`POLYBOT_ENVIRONMENT=development` seeds the verified `a@a.a` / `a` account during
API startup after schema migration. Missing environment and production do not
seed; concurrent startup is idempotent and existing account state is preserved.
Login/current-password validation accepts existing secrets of 1–128 characters;
new passwords retain 15–128 characters. Normal registration and verification
policy remain in place. OpenAPI, browser contracts and local setup docs reflect
this exception; no migration or Polymarket integration change is required.

Status: delivered September 10, 2026; depends on Slice 15 and Slice 16's HTTPS/email-link origin.

Approved September 10 policy: configurable SMTP relay; new accounts verify before
launching runs; existing accounts retain access and remain unverified. Single-use links follow the checked account policy below; password reset/change
revoke all sessions and require sign-in.
See [the account runbook](account-recovery.md) and the Slice 19 contracts in the
control-plane specification and architecture.

Minimum deliverable:

- Add password-reset request/completion, authenticated password change and
  revocation of other/all sessions with explicit reauthentication semantics.
  Keep account secrets and identity in `api.auth`.
- Select a transactional email delivery path and define the verification policy
  for unrestricted signup. Record when verification is required, resend behavior,
  and treatment of existing unverified accounts; never silently mark them verified.
- Use expiring single-use tokens stored as digests, bounded reset/resend attempts,
  safe same-origin links and generic account-discovery responses. Keep tokens
  out of logs and browser persistence.
- Define credential-change/reset effects on sessions and active streams.
  Preserve the distinction between revoking browser access and stopping an
  already-authorized paper run; explicit Stop and operator suspension are separate.
- Add browser flows with clear pending, expired, invalid and delivery-failure
  states. Document account ownership/recovery limits and the email dependency.

Acceptance:

- Reset/change flows work end to end; token replay, expiry, concurrent redemption
  and invalid credentials cannot change another account.
- Reset requests do not disclose account existence; email failure is handled
  without revealing account-specific results or falsely completing recovery.
- Revoked sessions and open streams lose access within the documented bound;
  passwords/tokens never appear in responses, logs or generated fixtures.
- Existing accounts survive the forward migration, and the selected verification
  transition cannot lock users out without a recovery path.

Explicit exclusions: social login, account linking, organizations and MFA.
Account deletion belongs to Slice 21. Follow the current
[OWASP recovery guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
when selecting the exact token and delivery policies.

Delivered implementation: `api.auth` owns SMTP configuration/delivery, digest-only
account links, user-serialized credential transactions and session revocation.
The consolidated initial migration requires verification for new-account
launches by default. The browser supplies account settings and recovery/verification forms,
erases link fragments before account restoration, and requires normal sign-in
after credential replacement. Generated API/runtime contracts and deployment secrets
remain synchronized. Explicit resends replace the old digest before SMTP, including
when delivery fails; relay acceptance never promises inbox delivery.

Validation: all 51 requested code-style reviewer roles completed; verified findings
were reconciled and affected rules rechecked. The full Python suite, frontend unit
and browser suites, type/build/generated-client checks, forward migration, and
isolated HTTPS Compose release/rollback rehearsal passed. Documentation drift was
audited across README, both architecture documents, the specification, deployment
runbook and account policy. SMTP setup and mailbox access are documented external
requirements; no Polymarket protocol behavior changed or MCP check was required.

## Slice 20: Operational Visibility and Controls

Status: delivered. Depends on Slices 16–19.

Minimum deliverable:

- Add structured, redacted operational logs and measurements for API errors,
  worker availability, queue depth/age, stuck runs, admission rejections,
  storage growth and existing market-feed health signals.
- Configure actionable alerts with an owner, thresholds and short response
  instructions. Monitor worker/job progress separately from API/database health.
- Provide a narrowly authorized operator command or protected endpoint to
  suspend an account, revoke its sessions, reject new work and stop its queued
  or active jobs. Make the effect on running jobs explicit and bounded.
- Record operator mutations with actor, target, action and outcome. Keep operator
  credentials/authorization separate from ordinary self-registered accounts.
- Add a service-wide stop/admission control for incidents and a runbook for
  dependency outages, failed deployments and resuming admissions.

Acceptance:

- Injected worker, queue, storage and feed failures produce useful alerts with
  no private payload/credential leakage; infrastructure failure cannot report
  a misleading healthy/empty result.
- Ordinary accounts cannot invoke operator actions or read operational account
  data. Suspension races with launch/login cannot grant fresh execution/access.
- Account suspension and global incident controls reach the documented outcome,
  are retry-safe, and preserve committed history.
- An operator can diagnose and stop a failing run using the runbook without
  editing production database rows manually.

Explicit exclusions: a full administration dashboard, generalized RBAC and
monitoring every internal function. Reuse existing runtime health observations;
changes to Polymarket adapters require the normal MCP checkpoint.

Delivered an OS-authorized operator CLI, atomic suspension/incident controls,
lease-fenced feed observations, independent worker presence, typed redacted logs,
and bounded operational probes. All 51 style reviewers completed; accepted
findings were reconciled and affected rules rechecked. Acceptance: 1,328 Python
tests passed with disposable PostgreSQL/Redis, followed by 32 focused auth/fence
checks after the final shared predicate change; 262 frontend tests, generated
contract parity, Svelte checks, production and Python package builds, five browser
scenarios, and the isolated HTTPS release/rollback/worker-loss rehearsal passed.
The HTTPS browser rehearsal now waits for authentication redirects to complete.
Documentation-drift audit updated README, product/architecture contracts, this
plan, deployment/operations runbooks and generated error contracts. No Polymarket
protocol behavior changed. Public operator/support identity remains the approved
placeholder and public signup remains closed.

## Slice 21: Backups and Data Lifecycle

Approved beta policy: encrypted backups every 24 hours, retained 14 days; recovery point ≤24 hours and isolated restore ≤2 hours; up to 100 terminal runs per account for 30 days; immediate deletion quiescence and eligible erasure within 24 hours; minimal completed deletion receipts and operator audits retained 90 days.

Status: delivered; depends on Slices 16–20 and Slice 17's history allowance.

Operator/support identity
may remain explicitly marked placeholders until the public-opening checklist.
See [beta-data-lifecycle.md](beta-data-lifecycle.md).

Minimum deliverable:

- Configure automated protected database backups and document recovery-point,
  recovery-time and backup-retention targets. Define separate handling for any
  non-database files actually needed by the hosted service.
- Implement bounded, retry-safe cleanup of retained events/history using the
  approved per-account and global storage policy. Preserve active runs and
  required bot/run references; disclose expired history in the browser.
- Add an authenticated account/data deletion request and an explicit lifecycle:
  block new work, revoke access, stop/quiesce jobs, then remove eligible data in
  dependency order. Set the policy for minimal retained operational records and
  backup expiry before implementing deletion.
- Document export/support handling, deletion timing and what remains in backups.
  Prevent restoring deleted/suspended access or restarting old jobs accidentally
  when restoring a database snapshot.

Acceptance:

- Restore a real backup into an isolated environment and verify accounts,
  ownership, bot configurations and retained history with no accidental job launch.
- Cleanup respects retention boundaries, active jobs and foreign keys; repeated
  runs and interruption/retry do not corrupt data or bypass account isolation.
- Deletion races with queued/running jobs cannot recreate removed data or permit
  new execution. Users cannot delete another account's resources.
- Browser history-expiry and deletion states match the documented policy, and
  measured restoration meets the selected recovery targets.

Explicit exclusions: indefinite history, transparent archival search and a
general-purpose data warehouse. Never apply destructive verification to the
production database.

Implementation uses a supervised bounded maintenance loop, one retained-history
selection policy, reauthenticated deletion with execution fencing, and private
restore quarantine with explicit per-account reconciliation. Daily mounted-storage
systemd units run the encrypted backup and hourly recovery-point check; deployment
installation and separate key custody remain operator release prerequisites.

Acceptance: 1,377 Python tests and six browser scenarios passed with disposable
PostgreSQL/Redis; 267 frontend tests, Svelte diagnostics, generated client parity,
frontend build and Python packaging passed. Additional final refinement tests cover
unmarked age/count recovery, returned launch errors, pinned Docker commands,
quarantine retries and archive/pipeline failures. A real encrypted backup restored
into a separate project in 7.2 seconds, preserving accounts, ownership, bots,
revisions and retained history with no old jobs started; an authenticated invalid
database dump failed without application startup. Evidence is under git-ignored
`data/beta/` and `data/reviews/slice21/`.

Documentation-drift audit synchronized README, product and architecture contracts,
this plan, lifecycle/recovery guidance and exported API/runtime fixtures. Policies,
scheduler budgets and documented command/status contracts have parity checks.
Public opening remains gated; support/operator identity is explicitly provisional.
No Polymarket protocol changes or blocked MCP checks were introduced.

## Slice 22: First-Use Experience

Status: delivered; depends on Slices 17–19 and the existing node editor/catalog.

Minimum deliverable:

- Add a guided path from signup through choosing an existing example, selecting
  available markets, reviewing paper settings and saving a private bot.
- Explain the example's conditions and expected behavior, then require an explicit
  Run action. Reuse catalog-owned examples, graph validation and market selection.
- Guide users through reading run status, simulated balances, orders/fills and
  existing skipped/rejected-action information. Make waiting for a condition
  distinguishable from failure or unavailable data.
- Provide useful empty/loading/error states, allowance feedback and recovery
  links. Keep the basic path usable with keyboard navigation and on smaller screens.

Acceptance:

- A new account can complete its first saved bot and paper run through the UI,
  inspect results and Stop without CLI use or knowledge of graph internals.
- Deterministic browser fixtures demonstrate both an action and a legitimate
  no-action case; real-service smoke tests do not assume a market must trade.
- Expired sessions, unavailable markets and capacity rejection explain the next
  action without losing another account's isolation.
- Onboarding never launches automatically, promises returns or bypasses normal
  input/market validation and paper-only gates.

Explicit exclusions: new strategy engines, a marketplace, a tutorial CMS and a
full graph execution debugger. Rich diagnostics remain a later product feature.

Delivered approach: the private guided route reuses catalog examples, market search,
`LaunchForm`, shared private-draft saving and the saved-bot page's explicit Run.
Run guidance distinguishes reported usable books, waiting, reconnecting and failed
execution, with simulated balances and loaded-history counts. Confirmed writes are
reused during an editor retry; unknown outcomes block resends from that draft and
direct the user to inspect existing bots. Reload starts a new blank create intent.

Acceptance: all 51 style-rule reviewers and affected closing reviewers completed;
accepted findings were reconciled across ownership, dependency direction, retry
safety, accessibility and tests. The backend suite passed 1,389 tests using real
disposable PostgreSQL/Redis; all eight browser scenarios passed, including search
failure/retry, deterministic action and no-action runs, Stop and reload. The
HTTPS deployment/failure/rollback rehearsal passed without assuming a market trade.
All 305 frontend tests, zero-diagnostic Svelte checks, generated-client parity, frontend
and Python package builds passed. Final documentation-drift audit covered README,
product spec, both architecture documents, this plan, author/API notes and operator
runbooks; no protocol change or public deployment was introduced.

## Slice 23: Launch Information, Support and Public-Beta Acceptance

Status: delivered; the separate operational open-signup gate depends on configured
operator/support ownership and the release checklist after Slice 12F and Slices 16–22.

Minimum deliverable:

- Add a public landing/help surface explaining visual strategy building, paper
  execution, current features, beta limits and the difference between simulated
  results and actual execution. Keep authenticated bot/run pages private.
- Publish service-appropriate privacy/terms information and a visible support or
  feedback channel. Align descriptions of data collection, retention, deletion,
  email and account recovery with the actual implemented policies.
- Make any new anonymous page/API allowlist explicit and minimal. Public
  navigation must never preload private resources.
- Run the complete production-like acceptance scenario: signup/verification as
  configured, recovery, onboarding, launch/limits, Stop, failure recovery,
  account isolation, operator controls and retention/deletion. Include the
  deployment, alert and backup-restore rehearsals owned by earlier slices.
- Record capacity results, known beta limits, support ownership and the release
  checklist. Opening public signup is a deliberate operational action after
  acceptance; completion of a documentation or coding task does not publish it.

Acceptance:

- Landing/help claims match delivered functionality, and all support/recovery
  links work. No marketplace, live-trading or performance guarantee is advertised.
- Multi-account API/browser acceptance uses real disposable PostgreSQL/Redis
  services and rejects skipped service-dependent tests.
- Run `uv run pytest`, `npm --prefix frontend run generate:check`,
  `npm --prefix frontend run check`, `npm --prefix frontend test`,
  `npm --prefix frontend run build` and `npm --prefix frontend run test:e2e`.
  Use README's disposable service settings, plus the staging/load/failure checks
  specified by the active slices.
- Complete the final documentation-drift audit across README, product spec,
  architecture, this plan, operator runbooks and generated contracts. Regenerate
  changed API artifacts before checking them. Mark each slice delivered only
  after its own acceptance passes.

Explicit exclusions: billing, paid acquisition, marketplace features and live
execution. These eight slices add no planned Polymarket protocol behavior; any
implementation that needs to change it must first verify with PolymarketDocs
and stop that protocol-sensitive work if the MCP is unavailable.

Delivered approach: five static public information pages with an exact, encoded-path
aware navigation boundary; no account/usage lookup or private preload on those
pages, including while already signed in. Public copy uses generated allowance,
lifecycle and recovery contracts. SMTP and browser branding share the application
identity owner. Placeholder operator/contact status is explicit on overview and
support; configuring the contact updates both through one component. No new
anonymous API, strategy engine or live path was introduced.

Acceptance on 2026-09-10: all 51 registered style reviewers completed, followed by
holistically applied fixes and focused closing reviews. All 1,389 backend tests ran
against real disposable PostgreSQL/Redis with no skipped service tests; all 314
frontend tests and all 11 browser scenarios passed. Svelte reported zero errors or
warnings; generated-client parity, frontend and Python package builds passed.
The complete HTTPS rehearsal passed guided setup, verification/login, launch/Stop,
reload/SSE, account isolation, queueing, worker/dependency faults, operator controls,
release/rollback and failed-migration refusal. The encrypted backup/restore
rehearsal passed in 7.2 seconds, preserving accounts/ownership/bots/revisions/history,
quarantining access and launching no old jobs; invalid authenticated dumps were
refused before app activation.

The 15-second bounded synthetic load rehearsal passed at the configured global
limits: 22,160 books, 221 durable writes, 247 reads, 1,768 stream frames and 247
budgeted requests; p95 I/O was 154.83 ms and event-loop lag 5.84 ms. These are local
fixture measurements, not vendor or production-host capacity claims. The
[release checklist](beta-launch.md) records rerun commands, named-owner prerequisites,
known beta limitations and the deliberate ingress-opening action. Local evidence
is in `data/reviews/slice23` and `/tmp/polybot-s23-*` logs.

Final documentation-drift audit completed across README, product spec, both
architecture documents, this plan, deployment/operations/lifecycle/launch runbooks,
author/API notes and generated contracts. Framework/protocol behavior is unchanged,
so no PolymarketDocs check was required. Support/operator placeholders remain an
approved exception to launch readiness, not authorization to publish. No public
ingress, account invitation or production deployment was performed.

## Full-repository review follow-up (2026-09-11)

This maintenance pass follows all 51 repository style rules across existing code;
it does not add a product slice. Coherent owners now cover writer processing,
replay queues and workflow, order accounting, stream dispatch, event projection,
wallet report normalization, deployment commands and frontend form/schema work.
Shared contracts and primitive validation rules are reused at their owning
boundaries. Wallet source keys now persist through PostgreSQL JSONB, malformed
wallet-report reads surface failures, and paper accounting rejects invalid fees
before state changes. Database recreation requires exact target-name confirmation. Catalog schemas and
synthetic preview identities are validated at ingress; failed capture shutdown
marks the archive failed, and rejected performance samples preserve cached marks.

Validation includes official-SDK adapter branches, real PostgreSQL event round
trips and schema gates, frontend/backend response parity, chart-history retries,
authentication destinations, browser onboarding, packaging and the affected style
reviewer reruns. The documentation-drift audit covers README, architecture/API
notes, web architecture, graph migration guidance and exported contracts. No live
trading, public ingress or deployment is part of this maintenance pass.

## Later Product Features

After the public paper beta, consider browser backtesting over available
recordings; strategy-version comparison on matching data/settings; deeper
performance analysis; explanations of blocked/skipped graph actions; run
notifications; and reusable market selection for recurring markets. Live trading
remains a separate expansion requiring per-user wallet authorization, execution
risk controls and order/fill reconciliation; it is not a paper-beta prerequisite.
