# Web Control Plane v0 Architecture and API

Status: planned. This document defines the implementation contract for the
product in `docs/web-control-plane-spec.md`; it does not describe currently
implemented code.

## Architectural Principles

- Keep `polybot` framework, execution, Polymarket adapters, recording, and
  backtesting independent of FastAPI, SQLModel, Taskiq, Redis, and SvelteKit.
- Put the control plane in a separate inward-dependent package. The control
  plane may import `polybot`; `polybot` must not import the control plane.
- Keep official Polymarket clients and models inside existing
  `polybot.polymarket` adapters. This slice adds no new Polymarket endpoint or
  transport.
- Keep API processes stateless with respect to live bot ownership.
- Treat PostgreSQL as the source of truth for run commands, state, durable
  events, and durable chart samples.
- Treat Taskiq as an initial delivery/execution mechanism, not a public run
  state machine.
- Treat Redis Pub/Sub as notification and ephemeral fan-out, not durable
  history.
- Preserve the existing fail-open `RuntimeObserver` boundary.
- Reuse shared valuation and dashboard semantics instead of implementing a web
  PnL formula.

## System Context

```text
trusted operator
  -> same-origin static SvelteKit application
  -> FastAPI control-plane API
  -> PostgreSQL

FastAPI
  -> RunLauncher
  -> Taskiq / Redis broker
  -> Taskiq worker
  -> execute_run(run_id)
  -> existing polybot runtime and official Polymarket adapters

execute_run observer
  -> PostgreSQL durable state/events
  -> Redis Pub/Sub wake-ups and 250 ms chart frames
  -> FastAPI SSE
  -> SvelteKit run detail
```

API workers and bot workers scale independently. No Uvicorn worker stores the
only reference to a bot task, cancellation event, or progress queue.

## Planned Repository Boundaries

```text
src/
  polybot/                    # Existing standalone bot framework.
  polybot_control_plane/      # Planned FastAPI/control-plane package.
    api/                      # Routes, dependencies, and public errors.
    catalog/                  # Trusted bot definitions and launch descriptors.
    contracts/                # Pure Pydantic API/SSE/chart contracts.
    database/                 # Engine, sessions, SQLModel rows, and migrations.
    events/                   # Runtime-event projection and durable writer.
    execution/                # RunLauncher, Taskiq task, run entrypoint.
    runs/                     # Lifecycle transitions, claims, stops, heartbeat.
    charts/                   # Presentation-neutral chart projection/sampling.
web/                          # Planned SvelteKit TypeScript application.
```

Package `__init__.py` files are not barrel exports. Modules remain named by
their responsibility. The static web build and API are deployment peers; the
frontend is not imported by Python code.

## Backend Stack

- Python 3.12.
- FastAPI and Pydantic.
- SQLModel over SQLAlchemy 2, using PostgreSQL through `asyncpg`.
- Alembic for schema migrations; application startup never calls
  `metadata.create_all()` in production.
- Taskiq with the official Redis broker integration.
- Redis Pub/Sub through the async Redis client.
- FastAPI `StreamingResponse` for `text/event-stream`.

All new dependencies must be pinned according to repository policy when the
implementation slice selects versions.

## Model Ownership and Reuse

Use SQLModel's data-model-first inheritance pattern:

```text
non-table SQLModel fields
  -> table=True SQLModel row
  -> create/read/update API SQLModel where semantics are identical
```

Never inherit an API model from a table model. Database-only identifiers,
leases, diagnostics, execution references, and internal timestamps remain off
public models unless explicitly required. Do not force semantically different
database and API fields into one base merely to avoid spelling them twice.

Use pure Pydantic `BaseModel` contracts for shapes that are not database rows,
including catalog descriptors, JSON Schema/UI metadata, SSE envelopes, chart
frames, and health responses.

Finite states and event kinds use typed enums defined once in the smallest
owning control-plane module. Database, API, worker, and tests import those
definitions rather than copying string literals.

## Persistent Model

### Run

The run table owns:

- UUID primary key;
- optional operator-visible name;
- bot-definition ID and version;
- immutable normalized launch-input JSON;
- immutable sanitized `BotConfig` JSON;
- typed public status;
- created, claimed, started, stop-requested, stopped, and updated timestamps;
- latest heartbeat timestamp;
- execution-backend kind and opaque execution reference;
- stable failure code and sanitized failure detail; and
- latest public portfolio/health summary needed by list and detail pages.

Credential fields are neither accepted nor stored. Decimal values serialize as
canonical decimal strings. Timestamps are timezone-aware UTC values at the API
and storage boundary.

### Durable run event

One append-only table owns all durable public progress and durable chart
samples:

- globally ordered bigint ID;
- run UUID;
- typed event kind;
- source occurrence timestamp when available;
- database persistence timestamp; and
- versioned JSONB payload.

The bigint ID is the durable SSE cursor. Index `(run_id, id)` and the queries
needed for run history. A uniqueness rule prevents an internally retried
projection from appending the same idempotency key twice where the source event
provides one.

The payload is decoded through the public Pydantic event union before leaving
the repository boundary. API callers never receive a raw JSONB dictionary.

### Bot definitions

Bot definitions are code-owned constants in v0, not database rows. A definition
contains its private factory reference, a concrete Pydantic launch-input model,
and public versioned descriptor. The backend validates through that model and
derives JSON Schema with `model_json_schema()`; it does not maintain an
independent JSON Schema validator or second field declaration. Catalog startup
validation rejects duplicate IDs/versions, unsupported schema/widget kinds,
sensitive fields, live mode, or an invalid factory.

## Catalog and Launch Validation

`GET /api/v1/bot-definitions` returns public descriptors only. The launch input
schema generated from the definition's Pydantic model uses JSON Schema Draft
2020-12. UI annotations use a small versioned control-plane extension
vocabulary; they do not change validation semantics.

`POST /api/v1/runs` performs this boundary sequence:

1. Resolve the trusted definition by public ID.
2. Require the submitted definition version to match.
3. Validate the input document against the definition contract.
4. Normalize wallet addresses, stream rules, decimals, and standard config.
5. Construct and validate a paper-only `BotConfig`.
6. Persist the immutable run in `queued`.
7. Commit before invoking the launcher.
8. Ask the configured `RunLauncher` to start the run by UUID only.
9. Store its opaque execution reference when available.
10. If launch delivery fails, transition the run to `failed` with the stable
    `launch_failed` code; do not leave an invisible in-memory launch.

The launcher never receives a client-provided factory path or configuration
object. The worker reloads the durable run and revalidates its catalog identity
before constructing the bot.

## RunLauncher Boundary

The launcher has one narrow responsibility: request execution of a durable run
UUID and return an opaque reference. Public endpoints and run state do not use
Taskiq-specific statuses.

### Initial Taskiq launcher

- Enqueue `execute_run(run_id)` through the Redis-backed Taskiq broker.
- Use Taskiq worker process and async-task limits for deployment capacity.
- Do not use Taskiq result storage as run history.
- Do not use Taskiq task termination as the Stop API.
- Treat redelivery as normal and require an idempotent database claim.

### Future ECS launcher

A later `EcsRunLauncher` may call ECS `RunTask` for one standalone task and
store the task ARN as its opaque reference. The container invokes the same
`execute_run(run_id)` application entrypoint. It retrieves configuration from
PostgreSQL; only the run UUID and deployment configuration cross the launch
boundary.

The future stop path first uses the same durable cooperative stop request and
then may call ECS `StopTask` after a grace period. ECS task-state events are
reconciliation evidence, not the public run state source. No ECS implementation
is part of v0.

## Worker Claim and Lifecycle

`execute_run(run_id)`:

1. Atomically lock and inspect the run.
2. Exit without side effects if it is stopped, terminal, or actively claimed.
3. Verify capacity/ownership rules and transition `queued -> starting`.
4. Resolve the exact bot definition version and construct the normalized
   paper-only config and bot.
5. Start heartbeat and cooperative-stop watchers.
6. Attach the web runtime observer and call existing `polybot.runtime.run_bot`.
7. Translate runtime state changes into the public lifecycle.
8. On requested cancellation, drain observer output and end in `stopped`.
9. On an ordinary exception, persist `failed` without exposing secrets.
10. On process loss, allow lease reconciliation to mark `interrupted`.

The database claim, not broker delivery, prevents concurrent duplicates.
Heartbeat interval, lease timeout, and configured worker concurrency are owned
constants/environment settings with validation that keeps the timeout safely
larger than the heartbeat interval.

A stop request is a durable state transition. Redis may wake the worker
immediately, while a database poll ensures a missed Pub/Sub message cannot make
Stop ineffective. User stop and infrastructure interruption remain distinct:
only a confirmed user stop produces `stopped`.

## Runtime Event Projection

The existing `RuntimeObserver.emit()` call is synchronous and fail-open. The web
observer therefore performs only bounded in-memory projection/enqueue work in
`emit()` and delegates database/Redis I/O to owned async tasks.

Event handling has two lanes:

- Lossless durable lane for lifecycle, bootstrap, activity, orders, fills,
  broker failures, settlements, portfolio, wallet timeline, failure, and
  sampled health events.
- Latest-state/coalescing lane for raw books and other chart inputs. These
  update in-worker projection state but are never queued as an unbounded raw
  event stream.

Shutdown drains accepted durable events before marking a graceful stop. A
database or observer failure is reported and logged but remains fail-open for
paper bot execution, matching the current runtime contract.

The public projection must reuse:

- existing package-owned event contracts at ingress;
- `polybot.performance.valuation.value_portfolio` for equity;
- existing accepted-book, stale-mark, stable-token-selection, settlement
  removal, trade-marker, and wallet-timeline rules; and
- the existing terminal chart constants where they represent product policy.

Presentation-neutral policy should move to the smallest shared owner needed by
both terminal and web projectors. FastAPI, SQLModel, Redis, ECharts, and HTTP
types must not enter the shared projection.

## Chart Data Flow

```text
RuntimeEvent
  -> in-worker chart projector
  -> current accepted books / portfolio / labels / wallet timeline
  -> every 250 ms: public ephemeral ChartFrame -> Redis Pub/Sub
  -> every 1 s: durable ChartSample -> PostgreSQL -> Redis wake-up
```

An ephemeral frame has no SSE `id`. A durable chart sample is an ordinary
durable run event and advances the cursor. A failure to publish Redis cannot
erase the committed durable event.

The server does not render charts. It sends exact decimal strings, timestamps,
stable token/wallet identity, stale/unavailable status, and marker data. The
frontend decides pixels, resampling, and responsive layout while preserving the
specified semantics.

## SSE Delivery

`GET /api/v1/runs/{run_id}/events/stream`:

- accepts the standard `Last-Event-ID` cursor and an equivalent `after`
  query parameter for explicit first connection;
- replays durable rows after the cursor in ascending ID order;
- subscribes to the run's Redis channel only as a wake-up/live-frame path;
- rechecks PostgreSQL after subscribing so the replay-to-live handoff has no
  race;
- sends committed durable envelopes with `id: <database event id>`;
- sends ephemeral chart frames without an `id` field;
- sends periodic SSE comments to keep intermediaries from closing an idle
  connection;
- never lets a slow browser backpressure the bot runtime; and
- closes after the terminal state has been delivered and no later committed
  event remains, or when the client disconnects.

If Redis notification is temporarily unavailable, the SSE adapter polls
PostgreSQL at a degraded cadence. Redis recovery restores low-latency delivery
without changing the durable cursor.

## HTTP API

All routes are under `/api/v1`. Ordinary endpoints are described completely in
FastAPI OpenAPI and consumed through the generated Hey API client.

### Catalog

- `GET /bot-definitions`
  - Return all public descriptors in stable display order.
- `GET /bot-definitions/{definition_id}`
  - Return one descriptor or typed not-found problem.

### Runs

- `POST /runs`
  - Body: definition ID/version, optional run name, launch-input object.
  - Return: `202 Accepted` with the durable run.
- `GET /runs`
  - Cursor pagination and optional public-status filter.
  - Default ordering: newest creation first.
- `GET /runs/{run_id}`
  - Current state, immutable configuration, latest summaries, and links/cursors.
- `POST /runs/{run_id}/stop`
  - Idempotently request or complete stop and return current run state.
- `GET /runs/{run_id}/events`
  - Cursor-paginated durable public event envelopes in ascending event order.
- `GET /runs/{run_id}/events/stream`
  - SSE replay plus live continuation.

### Operations

- `GET /health/live`
  - Process liveness only.
- `GET /health/ready`
  - Database and Redis readiness without starting or mutating a run.

Use one typed problem response containing an HTTP status, stable application
code, human-readable detail, and optional field errors. Validation errors must
identify launch-input paths without returning internal exceptions.

## Public Event Contract

Every durable envelope includes:

- numeric durable `id`;
- run UUID;
- typed `kind`;
- contract `version`;
- UTC occurrence and persistence timestamps; and
- a discriminated typed payload.

Initial event kinds cover:

- `run.lifecycle`
- `run.bootstrap`
- `bot.activity`
- `broker.order_submitted`
- `broker.fill_completed`
- `broker.failed`
- `market.settled`
- `portfolio.snapshot`
- `wallet.timeline`
- `stream.health`
- `run.failed`
- `chart.sample`

The ephemeral SSE kind is `chart.live`. Event kind and state strings have one
backend source of truth and generated frontend types. Tests import those
definitions instead of copying literals.

## Frontend Architecture

- SvelteKit with TypeScript and `adapter-static`.
- Client-side rendering; no SvelteKit server routes, actions, or SSR in v0.
- Same-origin deployment: static application at `/`, FastAPI at `/api/`.
- Ajv validates the definition-provided JSON Schema for immediate form feedback.
- FastAPI remains authoritative for all validation.
- Apache ECharts is wrapped by a thin `EChart.svelte` lifecycle component.
- Domain components own market, equity, and wallet-timeline option construction.
- Pages and stores never call `echarts.init`, `setOption`, `resize`, or
  `dispose` directly.

The generic ECharts wrapper owns client-only initialization, cleanup, a
`ResizeObserver`, theme, accessibility label, and efficient option updates.
`MarketPriceChart.svelte`, `EquityChart.svelte`,
`WalletTimeline.svelte`, and `RunCharts.svelte` own domain behavior.

## Generated Frontend Client

FastAPI OpenAPI is the HTTP contract source. A deterministic backend command
exports the OpenAPI document without requiring a running server. The frontend
pins `@hey-api/openapi-ts` and generates Fetch SDK functions plus TypeScript
types into a generated directory that is never edited by hand.

CI:

1. exports OpenAPI;
2. regenerates the Hey API client;
3. fails when the committed OpenAPI/client artifacts drift;
4. type-checks the frontend against the generated result.

The handwritten SSE adapter is the sole transport exception because the
browser `EventSource` lifecycle is not an ordinary request/response SDK call.
Its durable payload type is still generated through the HTTP event-history
response contract. It owns reconnect, cursor tracking, event parsing, and
dedupe; it contains no copied domain models.

## Deployment

The v0 Docker Compose topology contains:

- static frontend/reverse-proxy service;
- FastAPI service, allowed to run multiple Uvicorn workers;
- Taskiq worker service;
- PostgreSQL;
- Redis; and
- an explicit one-shot Alembic migration command/job.

Only the same-origin web entrypoint is exposed to the operator. PostgreSQL,
Redis, and the Taskiq broker remain on the private application network. Secrets
come from deployment environment/files and never enter the frontend build.

The initial worker deployment permits four concurrent runs. Scaling API
workers does not change bot capacity; scaling Taskiq workers or their async
capacity does. Deployment must account for Polymarket rate limits across all
worker processes.

## Testing Strategy

### Backend unit tests

- Catalog startup validation and schema/UI metadata.
- Definition-version conflicts and launch normalization.
- SQLModel shared-field, table, and public-response boundaries.
- Run state transitions, idempotent stop, lease expiry, and terminal guards.
- Atomic worker claim and duplicate Taskiq delivery.
- Runtime-event normalization and secret sanitization.
- Chart parity for stable token selection, stale/unavailable samples, equity,
  markers, settlement removal, and wallet dispatch state.
- SSE replay-to-live race closure, cursors, dedupe, heartbeat, slow clients,
  Redis degradation, and ephemeral frames without IDs.

### Backend integration tests

- PostgreSQL migrations and indexes.
- API create/list/detail/stop/history behavior.
- Taskiq launch through an injected test broker.
- Two concurrent fake bots with independent state/event streams.
- Worker loss followed by heartbeat reconciliation to `interrupted`.
- No network calls in tests except explicit adapter contract tests already
  owned by existing slices.

### Frontend tests

- Metadata-driven field rendering and domain widgets.
- Generated-client usage with no handwritten ordinary fetch calls.
- Run-list and run-detail state transitions.
- SSE reconnect, durable dedupe, and live/durable chart merging.
- ECharts option builders for terminal-parity semantics.
- Keyboard and clickable `z`, `x`, `r`, `v`, `j`, and `k` controls.
- Responsive narrow/wide layout.

### End-to-end tests

- Launch a deterministic fake bot, observe state and chart events, stop it, and
  reload its terminal detail.
- Queue above capacity and stop a queued run before worker claim.
- Disconnect/reconnect SSE without losing or duplicating durable events.
- Verify that arbitrary factories, live mode, and credential-shaped inputs are
  rejected.

## Intentional Exceptions and Deferred Work

- SSE uses a handwritten browser adapter; all request/response HTTP remains
  generated by Hey API.
- Live 250 ms chart frames are intentionally ephemeral. Only one-second samples
  are durable.
- PostgreSQL event retention is unbounded in v0. Compaction, archival, and
  deletion are deferred until measured volume requires a policy.
- Taskiq has no authority over public run status or cancellation. Application
  state, claim, heartbeat, and stop logic are deliberate control-plane
  responsibilities.
- ECS, EventBridge reconciliation, authentication, tenancy, payments, node
  programming, and live trading are future slices, not partial v0 scaffolding.
