# Web Control Plane v0 Product Specification

Status: planned. This document specifies future implementation work; none of
the web control plane described here exists yet.

## Purpose

Build the smallest private web control plane that can start multiple paper bot
runs, retain their lifecycle and useful progress, and present that progress in a
SvelteKit interface. The web UI must preserve the information and interaction
semantics of the existing terminal dashboard.

This is a single-operator control panel, not a complete SaaS product. It creates
a clean control-plane boundary without adding accounts, tenants, login,
payments, subscriptions, or live trading.

## Product Boundary

### Goals

- List a trusted server-owned catalog of available bot definitions.
- Render each definition's launch inputs from server-provided metadata.
- Start several paper bot runs concurrently.
- Queue launches when configured worker capacity is full.
- Stop queued or running bots gracefully.
- Persist immutable launch configuration, lifecycle, selected progress events,
  and chart history in PostgreSQL.
- Stream new progress to the browser over Server-Sent Events (SSE).
- Restore a run detail view after a page reload or SSE reconnect.
- Preserve terminal-dashboard chart behavior, including the followed-wallet
  timeline toggled with `v`.
- Keep the API independent from the process that executes a bot.
- Make the execution launcher replaceable so a later launcher can create one
  standalone Amazon ECS task per run.

### Non-goals

- Authentication, authorization, accounts, users, organizations, or tenants.
- Payments, plans, quotas tied to a customer, or metering for billing.
- Public-internet deployment without an external access boundary.
- Live trading or collection of wallet/CLOB credentials through the web UI.
- Editing, pausing, resuming, or automatically restarting a run.
- Restoring bot-local state, paper positions, or source-event claims after a
  worker process exits.
- Scheduling, run cloning, comparison, deletion, or bulk actions.
- Recorder and backtest controls.
- User-supplied Python paths, arbitrary code, plugins, or a node-programming
  engine.
- Exact terminal appearance or ASCII rendering in the browser.

## Trust and Safety Model

v0 has one trusted operator and no identity model. It must be bound to a local
or private network, or protected by infrastructure outside this application.
The documentation and deployment defaults must state that direct public
exposure is unsupported.

The web launch contract always creates `paper` runs. Web requests cannot set
`BOT_MODE=live`, enable live execution, or supply sensitive credential fields.
The existing live-execution gates remain unchanged and outside this product.

No placeholder `user_id`, `tenant_id`, entitlement, subscription, or billing
model is added. Those concepts require deliberate product work later.

## Core Concepts

### Bot definition

A bot definition is a trusted, versioned, server-owned catalog entry. It maps a
stable public ID to a Python factory internally and describes the launch inputs
that the UI may collect. The browser never receives or submits an import path.

Each definition exposes:

- stable `id` and immutable `version`;
- display name and description;
- example/non-trading labels where applicable;
- whether market selection is `user_configured` or `bot_managed`;
- whether wallet selection is `user_configured` or `bot_managed`;
- a JSON Schema Draft 2020-12 launch-input schema generated from its typed
  backend launch model;
- defaults and a small set of UI hints for domain widgets; and
- only non-sensitive, paper-compatible configuration.

The JSON Schema is an output contract, not a second hand-maintained definition.
The backend's typed launch model performs authoritative validation and emits the
schema and field metadata consumed by the catalog API. The UI renders ordinary
schema fields generically and owns specialized widgets
for market slugs, wallet addresses, and stream rules. A bot-managed market
definition remains selectable but shows an explanation instead of a market
editor. Adding a trusted definition that uses supported field types must not
require a launch-page code change.

The initial catalog contains the six distinct callable factories currently in
the repository. The duplicate default alias is not a separate catalog entry.
Examples and the non-trading market watcher must be labeled clearly.

| Public definition ID | Internal factory | Market input | Wallet input |
| --- | --- | --- | --- |
| `btc-five-minute-winner` | `polybot.examples.winner_trading_bot:create` | bot-managed | none |
| `btc-five-minute-momentum-example` | `polybot.examples.example_btc_five_minute_momentum:create` | bot-managed | none |
| `btc-five-minute-contrarian` | `polybot.examples.meh_trading_bot:create` | bot-managed | none |
| `btc-five-minute-market-watcher` | `polybot.examples.btc_5m:create` | bot-managed | none |
| `dynamic-random-hold-example` | `polybot.examples.example_dynamic_random_hold:create` | bot-managed | none |
| `dynamic-wallet-filter-copy-example` | `polybot.examples.example_dynamic_random_hold_wallet_filter_copy:create` | bot-managed | user-configured |

`polybot.my_bot:create` currently aliases the winner strategy and is therefore
not another public definition. Factory references above are private catalog
implementation data and never appear in API responses.

### Future visual bot definitions

A future node editor may produce a declarative, versioned bot definition that
is validated and published by the backend. That future definition could enter
the same catalog and launch flow. v0 does not define graph nodes, edges,
compilation, execution, storage, or publishing, and it must not accept
arbitrary executable code in anticipation of that feature.

### Run

Every Start action creates a new run with a UUID and an immutable snapshot of:

- bot-definition ID and version;
- operator-provided run name, if any;
- normalized launch inputs;
- resolved paper `BotConfig`; and
- creation timestamp.

Changing a catalog definition later cannot reinterpret an existing run. A
stale definition version submitted by the browser is rejected with a stable
conflict response so the UI can refresh the catalog.

### Progress event

A progress event is a stable public projection of runtime activity. Public
events are not serialized Python class names and do not expose SDK objects or
raw database rows. Durable progress includes:

- lifecycle transitions and bootstrap progress;
- bot-authored activity;
- orders, fills, broker failures, and settlements;
- portfolio snapshots;
- followed-wallet timeline events and dispatch acceptance;
- sampled stream health and counters;
- runtime failures; and
- one-second durable chart samples.

Raw order-book frames and every dispatch callback are not durable progress.
They may update counters and the in-worker chart projection without being
written individually.

## Run Lifecycle

The public finite state set is:

```text
queued
  -> starting
  -> running
  -> stop_requested
  -> stopping
  -> stopped

queued | starting | running | stop_requested | stopping
  -> failed

starting | running | stop_requested | stopping
  -> interrupted
```

Rules:

- `queued` means the run is durable but no worker owns it yet.
- Worker ownership is acquired with an atomic database claim.
- A repeated or redelivered execution message cannot start a claimed or
  terminal run again.
- Stop is idempotent.
- Stopping a queued run transitions it directly to `stopped`; a later broker
  delivery becomes a no-op.
- Stopping a running run requests cooperative cancellation and waits for the
  existing `run_bot()` cleanup path.
- `failed` retains a stable failure code plus a sanitized diagnostic message.
- A missing worker heartbeat beyond the configured lease marks a non-terminal
  run `interrupted`.
- Backend or worker restart never resumes or automatically relaunches a run.
- A new launch after an interruption creates a new run, bot instance, paper
  portfolio, and source-event claim lifetime.

The default deployment admits four concurrent bot runs. This is an environment
setting owned by worker deployment. Additional runs remain `queued` rather than
being rejected.

## User Experience

### Home

The home page contains:

- the available bot catalog;
- active and queued runs; and
- recent terminal runs.

Run rows show name, bot definition, state, creation/start time, elapsed time or
terminal duration, and the latest available equity summary.

### Launch

The launch page or modal:

- loads the selected catalog descriptor;
- renders its schema-defined inputs;
- uses explicit controls for decimals rather than binary floating-point
  coercion;
- validates locally for immediate feedback;
- submits one definition ID, definition version, optional run name, and input
  object; and
- navigates to the new run after a successful `202 Accepted` response.

The backend repeats all normalization and validation. Frontend validation is
never authoritative.

### Run detail

The run detail page contains:

- lifecycle state, timestamps, elapsed time, and last heartbeat;
- immutable definition/configuration details;
- bootstrap progress;
- current paper cash, fees, positions, equity, and PnL quality;
- terminal-dashboard-equivalent charts;
- bot activity, orders, fills, broker failures, and settlements;
- stream health and dispatch counters;
- a sanitized failure reason when applicable; and
- a Stop action for queued or non-terminal runs.

Terminal runs remain readable. v0 provides no edit, delete, resume, or rerun
action.

## Chart and Wallet-Timeline Parity

The existing terminal dashboard is the behavioral reference. Browser-native
graphics may add tooltips and clickable controls, but they must preserve these
semantics:

### Market view

- Plot no more than twenty outcome-token price series.
- Admit tokens in stable order; repeated market snapshots cannot rotate the
  visible selection or erase history.
- Use normalized order-book midpoint prices on a fixed `0` to `1` price axis.
- Carry the last plotted price across an unavailable current book only as a
  visibly stale segment.
- Represent a never-available value as a gap, not zero.
- Mark completed buys in green and sells in red on the traded token's line.
- Remove both outcome-token series, labels, markers, and cached chart state
  after successful settlement, matching terminal behavior.

### Executable equity

- Display executable paper wallet value beneath either primary view.
- Use the shared `polybot.performance` valuation rule: long positions mark at
  fresh best bid and shorts at fresh best ask.
- Clearly distinguish fresh, stale last-executable estimates, and unavailable
  valuation.
- Use variance-padded bounds rather than a forced zero baseline.
- Share the primary chart's visible time range.

### Followed-wallet view

- `v` switches between market prices and the followed-wallet timeline.
- Show one lane per configured or observed normalized wallet.
- Green means buy, red means sell, and yellow means a mixed time bucket.
- Marker size communicates relative aggregate notional.
- A bucket containing only skipped events is visually dimmed.
- Wallet paging remains available through `j` and `k` as well as clickable
  controls.
- The wallet view shares the price view's time window and equity chart.

### Time interaction

- `z` zooms in, `x` zooms out, and `r` resets the time window.
- Equivalent visible buttons are required so keyboard input is optional.
- The visible start and end timestamps are shown.
- Data is resampled to available browser width without reordering samples or
  losing the meaning of stale spans and trade markers.
- Layout responds to available width, using stacked panels on narrow screens.

### Sampling and persistence

- The worker updates and publishes the live chart projection every 250 ms,
  matching the terminal refresh cadence.
- Live 250 ms samples are ephemeral and carry no durable SSE cursor.
- One sample per second is appended durably for reload and reconnect.
- The worker persists derived midpoint/equity samples, not raw order books.
- The browser keeps the detailed live window in memory and may combine it with
  older one-second samples without presenting the older data as 250 ms input.
- Durable history is retained for the full run in v0. No compaction or deletion
  policy is introduced until observed volume requires one.

## Reconnection and Multiple Views

- Every durable event has an ordered database ID used as its SSE ID.
- Initial page load reads current run state and durable history over ordinary
  HTTP.
- SSE then continues after the last durable event ID.
- On reconnect, missed durable events are replayed before live delivery.
- Ephemeral chart frames do not advance the durable cursor.
- Redis is a low-latency wake-up and ephemeral fan-out path only. PostgreSQL is
  the durable source of truth.
- Multiple tabs may observe the same run without changing worker ownership.

## Availability Semantics

Runtime telemetry remains fail-open with respect to paper strategy execution,
matching the existing observer boundary. A chart-rendering, SSE, Redis publish,
or web-observer error cannot alter an order, fill, or bot callback. Failures are
logged and surfaced when possible.

The product does not claim uninterrupted observability during a PostgreSQL
outage. Heartbeat reconciliation may temporarily classify a run incorrectly
until storage recovers. This trade-off is acceptable for paper-only v0 and must
be reconsidered before web-managed live trading.

## Acceptance Summary

v0 is acceptable when:

- a trusted operator can launch two or more registered paper bots concurrently;
- launches beyond configured capacity remain visibly queued;
- duplicate execution delivery cannot start the same run twice;
- queued and running runs can be stopped idempotently;
- a killed worker produces `interrupted`, never an implicit resume;
- any API worker can list, inspect, stop, and stream any run;
- reload and SSE reconnect restore durable progress without duplicates;
- live charts update at 250 ms while durable chart history uses one-second
  derived samples;
- market, equity, wallet-timeline, stale-state, marker, settlement-removal, and
  keyboard-control behavior matches the terminal dashboard contract;
- adding a trusted bot definition using existing field/widget kinds needs no
  launch-page change;
- no endpoint accepts a Python path, secret, live mode, or arbitrary code; and
- the framework remains usable through the existing CLI without importing the
  control plane.
