# Web Control Plane v0 Product Specification

Status: planned. This document owns product scope and user-visible outcomes.
`web-control-plane-architecture.md` owns technical contracts. The implementation
plan references those contracts instead of restating them.

## Purpose

Build a small private control plane that lets one trusted operator launch and
observe multiple paper bots. It is a useful local/private product, not a partial
implementation of authentication, billing, tenancy, or live trading.

## Goals

- Show a trusted server-owned catalog of bot definitions.
- Maintain editable reusable graph templates.
- Save reusable bot configurations before running them.
- Render bot forms from backend-provided metadata.
- Let the trusted operator compose and run a validated paper-trading graph from
  framework-described lifecycle triggers, event outputs, typed constants,
  comparisons, and BUY/SELL broker actions.
- Launch multiple paper runs and queue work above worker capacity.
- Stop queued or running runs.
- Persist run state and useful progress in PostgreSQL.
- stream progress and live chart updates to a SvelteKit browser UI;
- restore durable progress after reload or reconnect; and
- match the existing terminal dashboard's information and controls, including
  the `v`-toggled followed-wallet timeline.

## Non-goals

- Authentication, users, tenants, organizations, payments, plans, or quotas.
- Public-internet exposure without an external access boundary.
- Live trading or web collection of wallet/CLOB credentials.
- Pause, resume, automatic restart, or restoration of bot-local paper state.
- Scheduling, deletion, retention management, or bulk actions.
- Template revision history, template-to-bot propagation, graph deduplication,
  or retained template provenance.
- Recorder or backtest controls.
- User-supplied Python paths, arbitrary code, plugins, unbounded loops, or
  node-defined network/protocol operations. Graphs use only the finite
  code-owned node catalog.
- ECS implementation. v0 keeps only the narrow launcher seam described in the
  architecture; it adds no ECS fields or adapters.

If a feature is not in Goals, it is not implied by “SaaS,” “future,” or
“extensible.” Add it in a later slice when it has a real consumer.

## Trust Boundary

v0 has one trusted operator and no identity model. It must run on a local or
private network or behind access control supplied outside this application.

Every web launch is paper-only. The browser cannot select live mode or submit
credentials. Existing live-execution gates remain unchanged; the control plane
does not wrap, duplicate, or weaken them. Do not add placeholder identity,
billing, entitlement, credential, or tenant fields.

## Bot Catalog

A bot definition is a trusted, code-owned mapping from a stable public ID to a
private Python factory and one typed launch-input model. The API never returns
or accepts factory/import paths. During alpha there is no public definition or
graph schema version; code, generated clients, and the disposable database move
together and the database is recreated after incompatible contract changes.

The descriptor tells the frontend whether market and wallet selection are
user-configured, bot-managed, or absent. A bot-managed definition remains
launchable and shows an explanation instead of an irrelevant editor. The
backend launch model is the sole field definition; its JSON Schema and small
typed widget annotations drive the generic frontend form.

The initial catalog is exactly:

| Definition ID | Factory | Market | Wallet | Label |
| --- | --- | --- | --- | --- |
| `btc-five-minute-winner` | `polybot.examples.winner_trading_bot:create` | bot-managed | absent | standard |
| `btc-five-minute-momentum-example` | `polybot.examples.example_btc_five_minute_momentum:create` | bot-managed | absent | example |
| `btc-five-minute-contrarian` | `polybot.examples.meh_trading_bot:create` | bot-managed | absent | standard |
| `btc-five-minute-market-watcher` | `polybot.examples.btc_5m:create` | bot-managed | absent | non-trading |
| `dynamic-random-hold-example` | `polybot.examples.example_dynamic_random_hold:create` | bot-managed | absent | example |
| `dynamic-wallet-filter-copy-example` | `polybot.examples.example_dynamic_random_hold_wallet_filter_copy:create` | bot-managed | user-configured | example |
| `node-based-bot` | `polybot_control_plane.catalog.node_based.bot:NodeBasedBot` | user-configured | absent | standard |

`polybot.my_bot:create` is an alias of the winner strategy and is not another
catalog entry.

## Saved Bot and Run

A saved bot has an immutable definition ID and editable paper configuration. A
graph-capable bot is created from a selected graph template, but receives an
independent immutable revision 1 copy and retains no template reference. Saving
later graph edits appends a new bot-owned revision; earlier revisions never
change and may be shared by multiple runs of that same bot.

Each Run action creates a new UUID-backed run with an immutable definition ID,
resolved paper configuration snapshot, saved-bot ID, and exact graph revision
reference when applicable. Alpha deployments recreate their disposable
control-plane database when the catalog or graph contract changes; they do not
retain or reinterpret older incompatible runs.

The public lifecycle is:

```text
queued -> starting -> running -> stop_requested -> stopping -> stopped

queued | starting | running | stop_requested | stopping -> failed
starting | running | stop_requested | stopping -> interrupted
```

- A worker obtains ownership with one atomic database claim.
- Duplicate delivery cannot start a claimed or terminal run again.
- Stop is idempotent. A queued stop goes directly to `stopped`; a running stop
  uses the existing cooperative `run_bot()` cleanup path.
- A missing heartbeat beyond the deployment lease produces `interrupted`.
- Restart or redelivery never resumes an interrupted run. Running the saved bot
  again creates a new run, paper portfolio, and source-event claim lifetime.

## User Experience

### Home, templates, and saved-bot creation

The home page shows the catalog, saved bots, active/queued runs, and recent
terminal runs. Run rows show the run name, definition, lifecycle, timing, and
latest equity when available. The graph-template page creates, selects, edits,
and saves reusable source graphs. The definition configuration UI renders typed
fields, selects a template when required, gives immediate client feedback,
saves the bot without running it, and opens bot detail. Decimal inputs remain
decimal strings across the API boundary.
Frontend validation is only feedback; backend ingress is authoritative.
Failed saves preserve the operator's edits. Backend field violations appear
under their owning controls, while graph violations appear in a focused summary
beside the canvas with the server message and any available node or connection
location. Transport failures remain page-level notices.
The graph-template and saved-bot detail pages render a Svelte Flow canvas. Its
trigger palette is derived from `BaseBot` lifecycle hooks, and each trigger exposes the
outputs derived from that hook's annotated event dataclass and explicitly
marked computed outputs. Drawn edges determine which outputs the graph uses.
`BookSnapshot.best_bid` and `best_ask` provide nullable
top-level price/size fields without duplicating the underlying books. The same
backend catalog describes typed constants, binary comparisons, and fixed-side
BUY/SELL actions derived from `Broker.submit(OrderRequest)`; the frontend
contains no parallel hook, event-field, or broker-action registry.

The template canvas stores the editable catalog graph. Selecting it for a bot
copies its exact validated graph into an immutable bot-owned revision.
For each accepted event, the node bot evaluates the matching acyclic branch once
and submits each reachable enabled action at most once through the existing
paper broker. Evaluation has no implicit cross-event state: while a condition
remains true, every matching accepted event may submit another order. The
operator is responsible for adding explicit position, cooldown, once, or other
state nodes when those capabilities are introduced; the MVP does not silently
invent them.

### Bot and run detail

Bot detail edits non-graph settings, loads the latest graph revision into the
canvas, appends a revision on explicit graph save, and runs the latest fully
saved state. Run is disabled while either editor has unsaved changes. The UI
states clearly that template and bot edits never propagate across the copy
boundary.

The detail page shows lifecycle/timing, immutable configuration, bootstrap and
activity progress, portfolio/equity, orders/fills/failures/settlements, stream
health, the dashboard charts, the saved bot, the exact graph revision and graph,
and Stop while the run is stoppable. Running
stream health is ephemeral and the final graceful-shutdown summary is durable.
Terminal runs remain readable. Rerunning happens from saved-bot detail and uses
the latest saved revision; historical run detail never changes.

## Dashboard Parity

`docs/architecture.md` section **Terminal Observability** is the behavioral
source for accepted-book freshness, price gaps/stale spans, stable token
admission, trade markers, settlement removal, executable equity, followed-wallet
lanes/buckets, time navigation, and the `z`/`x`/`r`/`v`/`j`/`k` controls.

The web implementation must present those same meanings with browser-native
ECharts and visible controls. It may improve layout, tooltips, and pointer
interaction; it must not invent a second valuation or chart policy.

The technical chart cadence, persistence, and stream contract is owned by
`web-control-plane-architecture.md`.

## Availability

Committed progress survives reload and reconnect; ephemeral frames are not
recoverable. Reload immediately restores only the newest bounded event page,
and the operator explicitly requests older progress. Chart rendering retains a
bounded terminal-equivalent history rather than automatically loading the
complete run. `web-control-plane-architecture.md` owns the storage and delivery
mechanism.

Web observability failure must not change paper-bot execution. The technical
invariant and mechanism are owned by `web-control-plane-architecture.md`
section **Execution and Lifecycle**.

## Acceptance

v0 is complete when one trusted operator can:

- save and launch at least two registered paper bots concurrently and see excess work
  remain queued;
- stop queued and running runs without duplicate execution;
- see worker loss become `interrupted` without automatic resume;
- reload or reconnect, recover the newest committed progress in order, and load
  older committed pages on demand;
- use market, equity, and followed-wallet views with terminal-equivalent
  semantics and controls;
- add a trusted definition using an already-supported field/widget kind without
  editing the launch page; and
- create a template, copy it into a saved node-based bot, append a bot graph
  revision, and launch a paper bot that compares a computed best bid/ask value with
  a constant, submits the configured BUY or SELL through the existing broker,
  reports its order/fill through the existing progress path, reloads its exact
  graph snapshot, and stops cooperatively.

No endpoint may violate the **Trust Boundary**, and the existing CLI must remain
usable without control-plane services.
