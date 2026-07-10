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
the `bots.polymarket` boundary and normalize them into package-owned contracts.
Pin the chosen dependency version and cover the adapter with contract tests.
The unified SDK's beta status requires version and compatibility discipline; it
does not by itself justify bypassing the SDK.

This package pins `polymarket-client==0.1.0b17`. Its internal adapter source
directory is named `polymarket_adapter/` but installs as `bots.polymarket`; this
prevents it from shadowing the official SDK's top-level `polymarket` import at
the repository root. Wallet-analysis scripts use synchronous `PublicClient`
methods and normalize SDK models before analysis code sees them.

## API Surfaces

Gamma API: `https://gamma-api.polymarket.com`

- Market and event discovery.
- Slugs, questions, outcomes, token IDs, active/closed state.
- Public, no authentication.
- Relevant docs: `/api-reference/introduction`, `/market-data/fetching-markets`.

Data API: `https://data-api.polymarket.com`

- Public positions, trades, activity, analytics.
- Useful for wallet state and backtesting inputs.
- Public wallet-following fallback through `/trades?user={address}` and
  `/activity?user={address}`.
- Public, no authentication.
- Relevant docs: `/market-data/overview`, `/api-reference/core/get-trades-for-a-user-or-markets`.

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

## Wallet Following

The public docs expose wallet-scoped Data API endpoints:

- `GET /trades?user={address}`
- `GET /activity?user={address}`

These endpoints are scoped to one user parameter per request. A multi-wallet
adapter therefore fans out through the official client per configured address,
then normalizes, merges, deterministically sorts, and dedupes the resulting
events. It must apply bounded concurrency and the documented Data API rate
limits rather than issuing an unbounded request burst.

`/trades` rows include wallet, side, asset/token ID, condition ID, size, price,
timestamp, and transaction hash. `/activity` rows include similar fields plus
activity type and combo flags.

The docs reviewed here do not document a general arbitrary-wallet WebSocket.
The framework therefore keeps `WalletActivityStream` abstract. Implementations
should prefer the lowest-latency source that can normalize a stable
`WalletTradeEvent`, then use Data API polling for bootstrap and reconciliation.

Before adding either path directly, re-check the unified SDK and specialized
official clients for a supported wallet activity method or stream. A source not
covered by an official Polymarket library is an explicit exception to the
official-library rule and must be documented here with the selected provider
and rationale.

Data API polling is not considered the target live wallet-following path. It is
a fallback/degraded path unless no correct streaming source exists. If no
official Polymarket arbitrary-wallet stream is available, implementation work
should evaluate on-chain or indexer WebSocket sources before settling for
polling.

## Market Slugs

Gamma market discovery is the owner of slug-to-market metadata resolution.
Multi-market and dynamic-market bots should produce slugs, then resolve those
slugs through Gamma/CLOB metadata before subscribing or trading.

For consecutive time-bucket markets, the framework expects the bot to generate
candidate slugs through `current_markets()` and `next_markets()`. The adapter
layer should then resolve the slug as soon as the market exists. Missing future
markets are normal for ephemeral markets and should be retried without blocking
the current market's hot path.
