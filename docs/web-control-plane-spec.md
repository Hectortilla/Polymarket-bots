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
- Render a launch form from backend-provided metadata.
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
- Scheduling, cloning, comparison, deletion, retention management, or bulk
  actions.
- Recorder or backtest controls.
- User-supplied Python paths, arbitrary code, plugins, or node programming.
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

A bot definition is a trusted, versioned, code-owned mapping from a stable
public ID to a private Python factory and one typed launch-input model. The API
never returns or accepts factory/import paths.

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

`polybot.my_bot:create` is an alias of the winner strategy and is not another
catalog entry.

## Run

Each Start action creates a new UUID-backed run with an immutable definition
ID/version and resolved paper configuration. A changed catalog definition must
not reinterpret an existing run. A stale version submitted from an old browser
view is rejected so the browser can reload the catalog.

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
- Restart or redelivery never resumes an interrupted run. Launching again
  creates a new run, bot, paper portfolio, and source-event claim lifetime.

## User Experience

### Home and launch

The home page shows the catalog, active/queued runs, and recent terminal runs.
Each row shows the run name, definition, lifecycle, timing, and latest equity
when available.

The launch UI renders the selected descriptor's typed fields, gives immediate
client feedback, submits definition ID/version plus its input object, and opens
the created run. Decimal inputs remain decimal strings across the API boundary.
Frontend validation is only feedback; backend ingress is authoritative.

### Run detail

The detail page shows lifecycle/timing, immutable configuration, bootstrap and
activity progress, portfolio/equity, orders/fills/failures/settlements, stream
health, the dashboard charts, and Stop while the run is stoppable. Running
stream health is ephemeral and the final graceful-shutdown summary is durable.
Terminal runs remain readable. There is no edit, delete, resume, or rerun
action.

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

- launch at least two registered paper bots concurrently and see excess work
  remain queued;
- stop queued and running runs without duplicate execution;
- see worker loss become `interrupted` without automatic resume;
- reload or reconnect, recover the newest committed progress in order, and load
  older committed pages on demand;
- use market, equity, and followed-wallet views with terminal-equivalent
  semantics and controls; and
- add a trusted definition using an already-supported field/widget kind without
  editing the launch page.

No endpoint may violate the **Trust Boundary**, and the existing CLI must remain
usable without control-plane services.
