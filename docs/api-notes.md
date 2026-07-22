# Polymarket API Notes

These notes summarize the Polymarket docs relevant to this isolated bot package.

## Official Python Libraries

Use official Polymarket libraries wherever they support the required
capability. Current official choices are:

- [`polymarket-client`](https://docs.polymarket.com/dev-tooling/python): the
  unified Python SDK for discovery, market data, trading, account data, and
  realtime streams. It provides matching async and sync clients; this framework
  uses `AsyncPublicClient` and `AsyncSecureClient`. Realtime subscriptions are
  async-only. The SDK is currently beta.
- [`py-clob-client-v2`](https://docs.polymarket.com/api-reference/clients-sdks):
  the official specialized Python client for the full CLOB API, including
  market data, order management, and authentication.
- [`py-builder-relayer-client`](https://docs.polymarket.com/api-reference/clients-sdks):
  the official Python relayer client for supported gasless transaction and
  wallet flows.

Selection order:

1. Use the unified async SDK when it supports the operation or stream.
2. Use a specialized official Python client when the unified SDK lacks the
   capability or official documentation designates the specialized client.
3. Implement direct HTTP/WebSocket access only when no official library can
   satisfy the required capability, correctness, or latency. Document the
   missing capability and evidence in this file and the relevant implementation
   slice before writing it.

Never hand-roll authentication, signing, order serialization, or protocol
models already provided by an official library. Keep all SDK/client types at
the `polybot.polymarket` boundary and normalize them into package-owned contracts.
Pin the chosen dependency version and cover the adapter with contract tests.
The unified SDK's beta status requires version and compatibility discipline; it
does not by itself justify bypassing the SDK.

This package pins the `polymarket-client` version declared in `pyproject.toml`. Its internal adapter source
directory is named `polymarket_adapter/` but installs as `polybot.polymarket`; this
prevents it from shadowing the official SDK's top-level `polymarket` import at
the repository root. Wallet-analysis scripts use synchronous `PublicClient`
methods and normalize SDK models before analysis code sees them.

Slice 3 uses the pinned SDK's `AsyncPublicClient.get_market(slug=...)`,
`list_markets(slug=...)`, `get_order_book(token_id=...)`, and
`subscribe(MarketSpec(...))` methods. The
market stream consumes full `MarketBookEvent` snapshots and applies each
`MarketPriceChangeEvent` atomically to adapter-owned depth before emitting a
sorted internal `BookSnapshot`. A zero-sized price change removes that level,
as specified by the market-channel documentation. The adapter treats `market`
as the condition ID and accepts only `BUY` or `SELL` price-change sides; it
rejects updates whose token or condition identity disagrees with resolved
metadata. REST remains the bootstrap and reconciliation path; the SDK market
subscription is the live signal path.

Slice 11 sets `custom_feature_enabled=True` on the same union `MarketSpec`.
Official market-channel documentation states that this enables
`market_resolved`, whose payload includes the condition/market ID, both asset
IDs, winning asset, winning outcome, and timestamp. The pinned SDK exposes that
payload as `MarketResolvedEvent`; the adapter validates it against Gamma market
metadata before producing `MarketResolutionEvent`. Gamma's two outcome slots
retain their public labels, which may be values such as `Up` and `Down`; after
validating that label against the winning asset, the adapter preserves it on the
internal event. Settlement uses the winning asset ID, not a special set of
outcome-label strings. No direct WebSocket implementation is required.

The official SDK names its two positional outcome fields `yes` and `no` even
when their labels are unrelated values. Those SDK field names stop at the Gamma
adapter. Internal `Market` metadata stores the two `MarketOutcome(label,
token_id)` values as its source of truth and exposes their generic token-ID
pair; no internal token slot is assigned label semantics.

The pinned SDK's open subscription handle cannot add token IDs. Registry
additions are therefore batched at the interval owned by
`MARKET_ADDITION_BATCH_SECONDS` in `polybot.cli.tracked_markets` and replace the
one union handle.
Gamma reconciliation runs immediately after replacement and then at the interval
owned by `polybot.cli.resolution.RESOLUTION_RECONCILIATION_SECONDS`.
It accepts a resolution only when Gamma reports a final resolution/closed state
and the binary outcome prices are exactly `1` and `0`.

In the pinned `polymarket-client` version, CLOB market subscriptions construct a
1,024-entry `AsyncSubscriptionHandle` queue. That SDK queue uses drop-oldest
backpressure and exposes its own `dropped` counter. Those upstream SDK losses
are distinct from the CLI's intentional per-token pending-book coalescing and
are not included in the CLI book-drop ratio. The CLI policy requires no direct
network integration and introduces no exception to the official-library rule.

## API Surfaces

Gamma API: `https://gamma-api.polymarket.com`

- Market and event discovery.
- Slugs, questions, outcomes, token IDs, active/closed state.
- The official SDK's `AsyncPublicClient.list_markets(slug=...)` maps to the
  keyset market-list endpoint and accepts multiple slugs in one request.
- Public, no authentication.
- Relevant docs: `/api-reference/introduction`, `/market-data/fetching-markets`.

Data API: `https://data-api.polymarket.com`

- Public positions, trades, activity, analytics.
- Useful for wallet state and possible future wallet-aware backtesting inputs;
  Slice 9B consumes only Slice 9A's market archive.
- Public wallet-following fallback through `/trades?user={address}` and
  `/activity?user={address}`.
- Public, no authentication.
- Relevant docs: `/market-data/overview`, `/api-reference/core/get-trades-for-a-user-or-markets`.

Slice 11 bootstraps newly followed wallets through the official SDK binding for
`GET /positions`. Absolute wallet follows call
`AsyncPublicClient.list_positions(user=..., size_threshold=0)` without a market
restriction. Filtered wallet follows resolve their stream-rule slugs to
condition IDs first, then pass those IDs through the endpoint's `market` filter;
they never bootstrap positions from unrelated markets. Only normalized open
positions are accepted. Each response row must match the requested normalized
wallet and, when present, the requested condition-ID scope. Duplicate token
rows, missing wallet-market-token identity, or invalid numeric values fail
closed.
The API's `outcome` field is an arbitrary string (for example, `Up` or `Down`),
so position, wallet-trade, book, market, and resolution normalization preserve
any non-empty string rather than restricting it to `Yes`/`No` labels. Outcome
labels are display and selection metadata; token IDs are authoritative identity.
Closed-position history and API lifetime PnL fields are deliberately ignored.
Bootstrap CLOB marks are best-effort: a CLOB 404 or a book without an executable
side stores the position with an unknown baseline and does not block market
tracking. A later valid book can populate that baseline. The adapter does not
substitute the Data API's indicative `cur_price` for an executable mark; position
identity and malformed market data still fail closed.

CLOB API: `https://clob.polymarket.com`

- Order books, prices, spreads, market fee info.
- Order placement, cancellation, heartbeat.
- Read endpoints are public.
- Trading endpoints require authentication.
- Relevant docs: `/trading/overview`, `/trading/orders/create`, `/trading/orders/cancel`.

Market WebSocket:

- Public real-time order-book, price, and market lifecycle updates.
- Relevant docs: `/api-reference/wss/market`.

User WebSocket:

- Authenticated own order and trade updates.
- Required for live fill confirmation.
- Relevant docs: `/api-reference/wss/user`.

## Historical Market Data Boundary

The official prediction-market APIs expose several historical-looking surfaces,
but only one contains L2 depth and it is live/current:

- CLOB `GET /book` and batch `POST /books` return current full aggregated books.
  The CLOB OpenAPI does not expose historical book snapshots, historical depth
  deltas, or a book replay endpoint.
- CLOB `GET /prices-history` returns `{t, p}` price points for one outcome token.
  It accepts an absolute `startTs`/`endTs` range or a relative interval, plus a
  fidelity in minutes. These points are a price series, not bids and asks.
- Data API `GET /trades` returns executed public trade rows. Market/event-scoped
  requests retain an approximately three-year floor and need time-window paging
  beyond the endpoint's offset budget. Executions do not reveal the orders that
  were placed and cancelled between trades.
- Gamma can return closed market/event metadata with `closed=true`, but it is a
  current metadata record rather than a revision history.

Prediction-market orders are created and matched offchain, with matched trades
settled onchain. Polygon settlement data therefore cannot reconstruct cancelled
or unfilled orders and is not an alternative historical L2 source. Neither the
price-history endpoint nor public trades can repair a missing book interval.

The public market WebSocket emits a full `book` when first subscribed and after
a trade affects the book, `price_change` updates for placements and
cancellations, `last_trade_price`, `tick_size_change`, and optional lifecycle
events. Documented payloads include timestamps; full books and price changes
also include hashes. The docs do not define:

- a monotonic sequence number or cross-message ordering contract;
- the hash as a revision cursor or parent-linked hash chain;
- replay of missed events; or
- a reconnect/resume cursor.

Consequently a new or reopened condition capture needs a fresh source full-book
baseline for every token before its subsequent updates form a replayable
segment. Source timestamps are stored alongside a local nondecreasing observed
timestamp and a recorder-owned arrival order; equal or nonmonotonic source
times are not guessed into a new exchange order. A documented hash is preserved
for diagnostics but is never promoted to a sequence number.

Slice 9A uses the pinned unified SDK's Gamma reads and the package-owned
`polybot.polymarket.recording_feed.MarketRecordingFeed`, which keeps
`AsyncPublicClient.subscribe(MarketSpec(...))` internal. A per-condition
`MarketCapture` emits package-owned baseline, delta, public-trade, tick-size,
and resolution values; `BookDepthProjector` rebaselines on full books and
rejects deltas before a baseline. No direct-network exception is required.
The market channel describes `price_change` values as individual level updates,
and live traffic can deliver one logical revision in consecutive frames sharing
the same timestamp and per-token hashes. If an intermediate fragment would
cross the projected book, the recording adapter accepts only same-condition,
same-timestamp continuations that preserve every token/hash fingerprint required
by the first fragment. A continuation may additionally name other token hashes;
those additions need not recur, but any that do recur must keep their first-seen
hash. It validates the ordered changes as one transaction. Missing, changed,
unrelated, late, dropped, or still-crossed continuations are quarantined and
retain fail-closed coverage-gap behavior. The public SDK handle's cumulative
drop-oldest counter is checked during read-ahead as well as normal capture; the
SDK does not expose a supported manager-wide malformed-message counter.
WebSocket resolution is committed before closing its condition handle. Gamma
metadata is reconciled immediately and retried until its final resolved state
is available, without delaying persistence of the source resolution event.

The SQLite recording archive stores sessions, metadata revisions,
chronological recorded events, book checkpoints, and coverage gaps. The
recorder treats a disconnect, interrupted condition capture, or increase in
`MarketCaptureDiagnostics.dropped_count` as a detected continuity break. A
continuing segment requires new full books for all affected tokens; a terminal
resolution can end the gap interval without repairing the missing interval.
Each condition has its own SDK subscription handle, so adding another condition
does not interrupt existing captures or create a gap by itself. Integrity can
therefore report `no detected gaps`, never `exchange-complete`. Recorder
downtime between resumed sessions is stored as an explicit target-wide gap;
restored unresolved conditions then resume their own condition-scoped capture.
Recovery writes same-boundary common token checkpoints immediately instead of
waiting for the periodic checkpoint cadence. The additive schema-v2 capture
anomaly journal preserves normalized failure evidence without altering replay
event order. Its feature-activation boundary distinguishes legacy sessions with
unavailable diagnostics from enabled sessions that observed zero anomalies.

Archive durability is local and does not change the Polymarket integration.
Each writer acknowledgement follows a committed WAL transaction with
`synchronous=FULL`. A market capture can retain a bounded FIFO of
unacknowledged writes while draining an SDK burst; admission assigns the global
sequence but only transaction completion acknowledges durability. Queued events
may therefore be group-committed and common checkpoint pairs are atomic.
Periodic and recovery checkpoint sets use one fresh observation timestamp and
one archive-wide batch, independent of the order in which group-committed event
tasks resume. Before replay, an exclusive archive lease refuses a live writer,
recovers an abandoned active session at its last committed observation, and
checkpoints any surviving WAL. This preserves recorded input but cannot recover
an event that the process consumed without committing or an upstream message
the recorder never received.

This hardening cannot promise gap-free recording. The official market-channel
contract still provides no sequence number, replay endpoint, hash lineage, or
resume cursor. REST price/trade history and advertised best bid/ask values are
diagnostic signals, not enough information to reconstruct missing L2 changes,
so neither is used to erase a gap.

The Slice 9A source set is limited to public prediction-market data. Public
`last_trade_price` has no wallet identity, aggregated levels have no maker or
queue identity, and the user WebSocket exposes only the authenticated account.
Arbitrary-wallet activity, private order/fill state, and RTDS Binance,
Chainlink, Pyth, sports, or other reference feeds are not recorded. A later
slice must add each missing source before a strategy depending on it can be
faithfully replayed.

The `polybot.recording.trim` utility is local schema-v2 SQLite maintenance. It
selects the longest gap-free all-market interval already present and rewrites a
self-contained archive; it does not fetch history, reconstruct a missing event,
instantiate an official client, or change any Polymarket protocol behavior.

The `polybot.recording.inspect` utility is also entirely local. It reads one
immutable SQLite snapshot and reports archive, session, event-kind, market,
checkpoint, gap, and capture-anomaly statistics without constructing an SDK
client or decoding the complete canonical event stream. It does not recover an
active session or certify a selection as replayable; those mutating recovery and
strict validation steps remain behind the inactive-archive replay boundary.

Slice 9B adds no Polymarket API or SDK path. It accepts only the current
schema-v2 SQLite artifact, snapshots an immutable archive sequence cutoff when
opening it, and reconstructs package-owned `Market`, `BookSnapshot`, and
`MarketResolutionEvent` values locally. Archive-wide recorder sequence orders
events, including equal source or observation timestamps; `observed_at_ms`
drives the virtual clock and source time remains diagnostic.

Replay validates an inactive schema-v2 archive, metadata and common two-token
book checkpoint/baseline coverage, the inclusive selected bounds, and selected
markets before invoking strategy hooks. Complete sessions are eligible in
full; failed and recovered sessions default to their last durable boundary and
are labeled partial sources. Its default strict policy rejects an affecting gap
rather than using price history, public trades, onchain settlement, or data
outside the selection to guess the missing book. Because recovery and the
virtual runtime are entirely local, backtesting constructs no official client,
makes no network call, and does not introduce an exception to the
official-library rule.

Slice 9B.1 adds an explicit local `blackout` replay policy; it does not add a
Polymarket API surface. The policy uses the archive's existing typed gap scope
and exact recorded start boundary to make affected books unavailable while
unaffected markets continue. It restores a closed affected market only from the
canonical fresh full-book baselines for both outcome tokens in one subscription
generation. Open gaps remain unavailable through the selected end. It never
uses `/prices-history`, public trades, advertised best prices, hashes, onchain
data, or a network lookup to interpolate price, depth, spread, liquidity, or
fills. Orders whose simulated latency crosses an affecting interval reject
instead of filling against the recovered future book.

This approximate mode does not weaken the upstream limitation: the official
market channel still documents no monotonic sequence, missed-message replay,
hash lineage, or reconnect cursor, and the public APIs still expose no
historical L2 replay source. Blackout preserves surrounding local state; it
cannot determine which market changes or strategy decisions were missed and
does not repair or relabel the source archive. Strict remains the default for
results that require a wholly gap-free selected interval.

Wallet activity, authenticated orders/fills, maker identity and queue position,
and external reference sources remain unsupported replay inputs. Wallet rules
or code that requests those archive-incompatible inputs fail closed instead of
falling back to a live API during backtesting.

## Authentication

CLOB trading uses two levels:

- L1: private-key EIP-712 signature.
- L2: API key, secret, and passphrase derived from L1.

Even with L2 credentials, order creation still signs the order payload. Use the
official unified SDK or official CLOB client rather than hand-rolling
signatures.

Relevant docs: `/api-reference/authentication`.

## Orders

Polymarket orders are limit orders. Market orders are represented by marketable
limit orders.

Supported order types include:

- `GTC`: rests until filled or canceled.
- `GTD`: expires at a configured time.
- `FOK`: fills entirely immediately or cancels.
- `FAK`: fills available liquidity immediately and cancels the rest.

Paper mode should model marketable orders by sweeping the fill-time order book.

## Fees

Polymarket charges taker fees on certain markets. Makers are not charged fees.
Some markets are fee-free. Fee parameters are market-specific and available from
CLOB market info.

Formula:

```text
fee = shares * fee_rate * price * (1 - price)
```

Fees are rounded to 5 decimal places. The fee is symmetric around price `0.50`.

Relevant docs: `/trading/fees`.

## Rate Limits

Cloudflare throttling queues/delays over-limit traffic instead of always
returning clean rejections, so rate-limit mistakes show up as latency.

Important limits from docs:

- Gamma `/markets`: 300 requests per 10 seconds.
- Data `/trades`: 200 requests per 10 seconds.
- Data `/positions`: 150 requests per 10 seconds.
- CLOB `/book`: 1,500 requests per 10 seconds.
- CLOB `/books`: 500 requests per 10 seconds.
- CLOB `POST /order`: 5,000 requests per 10 seconds burst.

Relevant docs: `/api-reference/rate-limits`.

`GammaClient.find_many()` uses the SDK market-list paginator with a sequence of
slugs and a page size of 100, preserving the caller's order and duplicate
slugs after the response is normalized. It splits the sequence at a
60,000-character encoded-query budget because the pinned SDK's `httpx`
transport rejects query components longer than 65,536 characters. This avoids one
Gamma request per market during bootstrap while keeping long slug collections
safe. It also caps each slug-filter array at 100 values, matching Gamma's API
validation. Because the list endpoint defaults to `closed=false`, unresolved
slugs are retried together with `closed=true` so open wallet positions in closed
or resolved markets can still be normalized. Batches are sent sequentially and
the SDK paginator handles pagination inside each batch. Single-slug and list
responses must match the requested slug scope; the adapter rejects unrequested
rows and conflicting repeated rows instead of allowing ambiguous metadata into
the runtime. A fixed inter-request delay is not needed for this path.

## Wallet Following

The public docs expose wallet-scoped Data API endpoints:

- `GET /trades?user={address}`
- `GET /activity?user={address}`

These endpoints are scoped to one user parameter per request. A multi-wallet
adapter therefore fans out through the official client per configured address,
then normalizes, merges, deterministically sorts, and dedupes the resulting
events. It must apply bounded concurrency and the documented Data API rate
limits rather than issuing an unbounded request burst.

Wallet and selector responses are checked against the requested user and
condition-ID scope before normalized events leave the adapter. Out-of-scope
rows fail closed rather than being silently attributed to the request.

`/trades` rows include wallet, side, asset/token ID, condition ID, size, price,
timestamp, and transaction hash. `/activity` rows include similar fields plus
activity type and combo flags.

The pinned unified SDK does not expose a general arbitrary-wallet trade
WebSocket. `WalletActivityStream` therefore uses SDK-backed Data API polling as
the authoritative wallet-identified source. Public market `last_trade_price`
events are only wake-up hints because they omit a wallet. Optional compatible
push sources may be merged with polling and are deduplicated by canonical trade
identity.

The Data API's omitted `start` uses a broad default window (about three years).
Polling must set `start` to the runtime freshness window, with a one-second
overlap for timestamp boundaries, and discard rows outside that window before
queueing them.

Before adding either path directly, re-check the unified SDK and specialized
official clients for a supported wallet activity method or stream. A source not
covered by an official Polymarket library is an explicit exception to the
official-library rule and must be documented here with the selected provider
and rationale.

`/trades` is limited to 200 requests per sliding 10 seconds. The runner keeps a
shared process budget below that limit, including pagination requests; no quota
or `Retry-After` response-header contract is documented.

## Market Slugs

Gamma market discovery is the owner of slug-to-market metadata resolution.
Multi-market and dynamic-market bots should produce slugs, then resolve those
slugs through Gamma/CLOB metadata before subscribing or trading.

Gamma's `orderMinSize` and `orderPriceMinTickSize` are nullable. The adapter
preserves null values as unknown `Market.minimum_order_size` and
`Market.minimum_tick_size`; it does not invent a zero-size minimum or a price
increment. The CLOB order-book response remains the authoritative source when
an execution path needs concrete trading limits.

For consecutive time-bucket markets, the framework expects the bot to generate
candidate stream rules through `current_stream_rules()` and `next_stream_rules()`. The adapter
layer should then resolve the slug as soon as the market exists. Missing future
markets are normal for ephemeral markets and should be retried without blocking
the current market's hot path. `GammaClient.wait_for_slug()` provides that
cancel-safe async retry primitive; stream-plan orchestration schedules it in a
separate task when consuming `MarketPlan.next`.
