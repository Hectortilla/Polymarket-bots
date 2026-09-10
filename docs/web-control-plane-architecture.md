# Web Control Plane v0 Architecture and API

Status: Slices 12A–12F, 13A–13F and 14–21 are implemented.
This document is the single technical contract for the product in
`web-control-plane-spec.md`.

The [public paper-beta roadmap](implementation-plan.md#public-paper-trading-beta-roadmap)
continues with planned Slices 22–23 after the delivered deployment, resource-limit, reliable-lifecycle, account-recovery, operations and data-lifecycle foundation. It covers production
operation, resource limits, reliability, recovery, data lifecycle and launch
workflows. Adopt each slice's technical contracts here during implementation;
current private access, ownership and paper execution remain unchanged until the
specified readiness gates pass. Marketplace work is deferred.

## How to Implement This Plan

When a task names one implementation slice, that slice is the whole scope.
Later slices explain direction; they do not authorize scaffolding for their
features.

Every addition must pass these budgets:

- **Field budget:** add a database or API field only when the current slice has
  a named writer and reader for it. Do not add IDs, flags, timestamps,
  provenance, versions, metadata, links, summaries, or future integration fields
  “just in case.” A later Alembic migration is cheaper than a speculative
  contract.
- **Abstraction budget:** do not add generic repositories, base services,
  managers, registries of registries, DTO mappers, provider frameworks, or
  wrapper layers. A boundary may be abstract only when this plan requires a
  second implementation (`RunLauncher`) or an existing package contract already
  supplies it (`RuntimeObserver`).
- **Module budget:** create a module for one present responsibility. Do not
  pre-create the package tree, empty modules, or barrel exports. Split a module
  only when the current slice gives the extracted part a distinct owner.
- **Validation budget:** validate external values once at HTTP, environment,
  database-JSON, Redis-message, or Polymarket adapter ingress. After a boundary
  returns a typed value, internal code trusts it. Do not repeat Pydantic,
  SQLModel, enum, range, `None`, or shape checks in orchestration functions.
- **Safety budget:** keep existing trading fail-safe rules and the few
  concurrency/reconnect guarantees named here. Do not add fallback transports,
  retry frameworks, recovery modes, caches, audit systems, or defensive branches
  that are not acceptance requirements.
- **Test budget:** test repository-owned behavior and important failure/race
  branches. Do not test FastAPI, Pydantic, SQLModel, Taskiq, Redis, ECharts, or
  generated-client behavior that this code does not customize.

Prefer a small function over a one-use class. Prefer direct SQLModel session
code in the owning run/event module over a generic repository. Prefer adding a
field or abstraction in the later slice that first consumes it.

If an implementation cannot point from a new field, branch, module, or layer to
a requirement and acceptance assertion in the active slice, leave it out. Ask
before expanding product or architecture scope.

## Authority Map

- Product scope and lifecycle outcomes: `web-control-plane-spec.md`.
- Technical contracts, routes, persistence, delivery, and cadence: this file.
- Existing dashboard behavior: `docs/architecture.md`, **Terminal
  Observability**.
- Slice scope, minimum deliverables, explicit exclusions, and acceptance:
  Slices 12A-12F, 13A-13F, 14, 15, 16 and 17 in `docs/implementation-plan.md`.

The implementation plan assigns architecture-owned work and acceptance to a
slice. It may use canonical contract terms when doing so, but it does not define
an independent shape or algorithm; this document controls if wording conflicts.

## Boundaries and Stack

- `polybot` remains independent of FastAPI, SQLModel, Taskiq, Redis, SvelteKit,
  and the new control-plane package.
- `api` may import `polybot`; the reverse import is forbidden.
- The static frontend and API are deployment peers. Python does not import the
  frontend.
- API processes hold no sole reference to a bot task, cancellation primitive,
  or progress queue.
- PostgreSQL owns durable runs, commands, and events.
- Taskiq with its Redis broker delivers run IDs to workers.
- Redis Pub/Sub wakes SSE connections and carries ephemeral live frames.
- SvelteKit uses TypeScript, `adapter-static`, and client-side rendering.
- FastAPI/Pydantic own HTTP contracts; SQLModel/SQLAlchemy with `asyncpg` own
  persistence; Alembic owns schema creation and change.

Add each dependency only in the slice that first imports it. Pin the selected
version according to repository policy.

## Contract Ownership

Public contracts use stable, discoverable modules. These names are required;
supporting private modules are not prescribed:

- `api.catalog.values`: dependency-light `DefinitionId`,
  `SelectionMode`, `WidgetKind`, label, and widget-key contracts;
  `api.catalog.contracts`: `BotDefinitionDescriptor`.
- `api.bots.contracts`: saved-bot request/read and immutable
  graph-revision contracts.
- `api.catalog.graphs.values`: dependency-light graph enums,
  limits, and semantic handle values;
  `api.catalog.graphs.types`: constrained identifiers, field
  paths, and handle contracts.
- `api.catalog.graphs.catalog`: public node descriptors,
  framework-derived `GraphNodeCatalog`, and the code-owned catalog snapshot.
- `api.catalog.graphs.contracts`: validated `NodeGraph`, node,
  and edge contracts plus their validation limits. The browser consumes the
  generated limits and catalog, while backend-generated valid and invalid
  graph cases lock its runtime topology validator to the Python contract.
- `api.catalog.graphs.starter`: the starter graph snapshot.
  Focused private supporting modules discover `BaseBot` hook signatures,
  traverse dataclass and explicitly marked computed outputs, describe the
  trusted broker action, and share graph-validation primitives. The package
  initializer remains empty rather than re-exporting these owners.
- `api.catalog.node_based.bot`: concrete `NodeBasedBot` hook
  handling.
- `api.catalog.node_based.evaluator`: orchestration for the
  compiled graph, with focused compiler, value, action, and result owners.
- `api.runs.status`: `RunStatus` and its lifecycle policy;
  `api.runs.contracts`: `PaperRunConfig` and `RunRead`.
- `api.events.kinds`: dependency-light durable and live event
  discriminators; `api.events.contracts`: `DurableEvent` plus
  their discriminated payloads. Slice 12E adds `LiveChartEvent`,
  `LiveStreamHealthEvent`, their `LiveRunEvent` union, and the `chart.sample`
  durable variant when it first implements live observability cadence.
- `api.execution.launcher`: the `RunLauncher` protocol.
- `api.graph_templates`: editable catalog contracts, row, and
  persistence operations.
- `api.bots`: saved-bot and immutable graph-revision
  contracts, rows, and persistence operations.

Finite wire values are `StrEnum`s. The generated frontend types come from these
Pydantic models through FastAPI OpenAPI. Tests import the enums; they do not copy
contract strings.

Graph identifier limits are owned by
`api.catalog.graphs.values` and flow into the constrained
types and OpenAPI schema.
Edge IDs intentionally have a larger bound so Svelte Flow's descriptive IDs
can include both endpoint and handle identities without weakening every
identifier.

Use non-table SQLModel bases only where a group of fields has identical database
and API meaning. Never inherit an API model from a table model, and do not make a
base merely to avoid repeating one or two fields. Non-row wire shapes remain
plain Pydantic models.

## Catalog and Launch Contract

`SelectionMode` has exactly `user_configured`, `bot_managed`, and `absent`.
`WidgetKind` contains only schema-driven form widgets: decimal, market slugs,
wallet addresses, and stream rules. Graph canvases use the separate
`graph_catalog` and `starter_graph` descriptor fields rather than pretending a
graph is part of `PaperRunConfig`.

`BotDefinitionDescriptor` has exactly:

- `definition_id`
- `display_name`
- `description`
- `label` (`standard`, `example`, or `non_trading`)
- `market_selection`
- `wallet_selection`
- `input_schema`
- `graph_catalog` (omitted for definitions without a node graph)
- `graph_examples` (omitted when no examples are provided)
- `starter_graph` (omitted for definitions without a node graph)

`BotCreate` has exactly:

- `definition_id`
- `inputs`
- `graph_template_id` (nullable)

Graph-capable definitions require the template ID; other definitions forbid it.

`BotUpdate` has exactly:

- `inputs` (the complete non-graph launch inputs)

The bot name remains a field in the definition's schema rather than a second
top-level copy. External request and definition launch models reject unknown
fields.

Each catalog entry owns one Pydantic launch-input model and a conversion to
`PaperRunConfig`. `model_json_schema()` is the only JSON Schema definition.
Typed `x-widget` annotations select the small domain-widget set; ordinary JSON
Schema fields use ordinary controls. Do not add a parallel field registry or
frontend field model.

Catalog construction imports the entries in the product-spec table. Normal
Python imports, enum construction, and Pydantic model construction provide the
checks; do not add a second startup-validation framework. Definition IDs are
unique by construction in one code-owned mapping.

`PaperRunConfig` is the complete persisted paper snapshot and contains only the
non-sensitive `BotConfig` inputs used by web runs:

- `name`
- `stream_rules`
- `data_trades_budget_per_10s`
- `max_order_size`
- `max_slippage_pct`
- `paper_latency_ms`
- `paper_latency_jitter_ms`
- `event_max_age_ms`
- `paper_portfolio_usdc`

Graph JSON is deliberately absent. Templates and immutable bot-owned revisions
are the only graph persistence owners.

Decimal values serialize as canonical decimal strings. Fields prohibited by the
product specification's **Trust Boundary** are absent rather than accepted and
then rejected. Conversion to the existing `BotConfig` supplies paper mode and
credential-free values itself.

During alpha, bot definitions and node graphs have no public version field. The
code-owned catalog and generated client move together. Slice 15 ends the implicit
disposable-database policy: databases containing accounts require explicit forward
migrations and preservation of owned resource snapshots. The approved pre-auth
reset is a one-time transition, not a standing authorization to delete account data. A future stabilization slice may deliberately
introduce versioning when persisted compatibility becomes a product requirement.

The current graph MVP contract and execution semantics are specified in
[Graph MVP architecture and authoring](graph-node-mvp.md). The backend publishes
trigger, constant, comparison, broker-action, operation and parameter node kinds.
Number replaces Integer/Decimal at graph ports; exact values remain decimal strings
on the wire. Context ports support own-portfolio reads, keyed signal controls and
diagnostics. Action outputs and diagnostic-only branches are supported. Missing
comparison inputs remain unavailable through Boolean operations.

The compiler checks executable capabilities before any action. The frontend consumes
backend catalog metadata and generated schemas, including operation descriptors and
synthetic preview samples. Catalog definitions also provide independently copyable
example graphs. The default starter remains non-trading. See the
[two-phase implementation checklist](graph-mvp-plan.md) for delivery units.

The saved-bot boundary performs the only request normalization:

1. Parse `BotCreate` or `BotUpdate`.
2. Resolve its code-owned definition ID.
3. Parse `inputs` with that definition's launch model.
4. Convert once to `PaperRunConfig`.
5. For a graph-capable create, copy the selected template into revision 1 in
   the same transaction as the new bot.

Starting a bot locks its row, copies the current config into a queued run,
references its latest graph revision, commits, and only then calls
`RunLauncher.launch(run_id)`.

Delivery failures preserve the committed queued row for Slice 18 recovery.
Queued Stop still commits its terminal state and lifecycle event atomically.
A lost post-commit Redis wake is recovered by periodic PostgreSQL SSE replay.

## Persistence Contract

### Graph template row

`graph_templates` has exactly:

- `owner_user_id` (required, indexed user foreign key)
- `id` (UUID primary key)
- `name` (unique per owner, trimmed)
- `graph` (validated `NodeGraph` JSON)
- `created_at`
- `updated_at`

Templates are mutable and are never referenced by bots or runs.

### Saved bot and graph revision rows

`bots` has exactly:

- `owner_user_id` (required, indexed user foreign key)
- `id` (UUID primary key)
- `definition_id` (immutable)
- `config` (editable resolved `PaperRunConfig` JSON)
- `created_at`
- `updated_at`
- `deleted_at` (nullable soft-deletion timestamp)

`bot_graph_revisions` has exactly:

- `id` (UUID primary key)
- `bot_id` (owning saved-bot foreign key)
- `revision` (positive and sequential per bot)
- `graph` (exact validated `NodeGraph` JSON)
- `created_at`

`(bot_id, revision)` is unique. Revisions are append-only and may be referenced
by many runs of their one owning bot. No template provenance is retained.

### Run row

The final v0 run row has exactly:

- `id` (UUID primary key)
- `bot_id` (required saved-bot foreign key)
- `definition_id`
- `config` (`PaperRunConfig` JSON)
- `bot_graph_revision_id` (nullable)
- `status` (`RunStatus`)
- `created_at`
- `started_at` (nullable)
- `ended_at` (nullable)
- `heartbeat_at` (nullable)
- `launch_key` (nullable UUID)
- `execution_token` (nullable UUID)
- `delivery_attempted_at` (nullable timestamp)
- `failure_detail` (nullable, sanitized)
- `history_expired_at` (nullable timestamp; hidden, partially purged terminal history)

The composite `(bot_id, bot_graph_revision_id)` foreign key prevents a run from
using another bot's revision. Graph-capable definitions require a revision and
other definitions require null; this rule is owned by the catalog. Do not add
separate launch-input/config copies, updated/claimed/stop timestamps,
latest-summary columns, vendor execution-backend fields or user IDs. Slice 18
adds only its internal launch identity, execution token and delivery timestamp.
Current summaries come from durable events. ECS can add its own reference when
an ECS slice actually exists.

The September 10 user-approved consolidation replaces the undeployed, disposable
migration history with one initial revision, `0001`. It creates all current tables,
constraints and indexes, including identity, events, reliability, recovery,
operations and lifecycle state, and seeds the required operations singleton.
Databases from the former chain must be explicitly recreated with the existing
recreation command. Downgrade to `base` drops all control-plane tables. This is a
local reset exception; future retained deployments use forward migrations/backups.
The initial revision also includes nullable `bots.deleted_at`. The user approved
folding the former soft-delete migration into `0001` because there are no
deployments and local data will be removed. Databases built from the previous
initial schema or the former `0002` head must be recreated, not stamped.

The persistence boundary decodes `config` into `PaperRunConfig` once before it
returns a run to API or worker code. Orchestration never handles raw JSON and
never re-runs request validation.

### Durable event row

The append-only event row has exactly:

- `id` (globally ordered bigint primary key and SSE cursor)
- `run_id` (UUID foreign key; indexed with `id` for per-run cursor reads)
- `kind` (`EventKind`)
- `occurred_at` (UTC)
- `payload` (JSONB)

There is no second persistence timestamp, schema-version field, source-key
column, generic metadata, or speculative dedupe key in v0. Pre-persistence
writes use the optional-ID `DurableEvent` union; append results and reads decode
the committed row through the same persistence boundary into the required,
browser-safe-ID `PersistedDurableEvent` union.

The canonical durable event kinds are:

- `run.lifecycle`
- `run.bootstrap`
- `bot.activity`
- `broker.order`
- `broker.fill`
- `broker.failure`
- `market.settlement`
- `portfolio.snapshot`
- `wallet.timeline`
- `stream.health`
- `run.failure`

Slice 12E extends this list with `chart.sample`; Slice 12B does not advertise a
wire kind whose payload contract is not implemented yet.

Raw book events and individual dispatch callbacks are not durable. Individual
stream-health inputs are also retained only in memory; on graceful observer
shutdown, the latest state is appended once as the run's final `stream.health`
summary before the terminal lifecycle event. A run that observes no stream
health, or loses its process before graceful observer shutdown, has no such
summary. Through Slice 12D, a running browser therefore receives no live health
updates. Slice 12E publishes the latest state once per second as an ephemeral
`LiveStreamHealthEvent`; it never persists those live frames. The terminal
durable summary remains the reload contract.

The web observer maps runtime events to the durable list above and enqueues
those records; raw books only replace the latest in-memory chart input. Keep
that mapping in one owning function/table, not a generic policy class or
repeated `isinstance` lists. Pure projection and database/Redis I/O must not
become one monolithic module.

## Execution and Lifecycle

`RunLauncher` is the one deliberate v0 seam for a future ECS implementation:

```python
class RunLauncher(Protocol):
    async def launch(self, run_id: UUID) -> None: ...
```

The Taskiq adapter enqueues the UUID. It does not expose Taskiq status, results,
or cancellation through public contracts. A future ECS adapter can launch the
same worker entrypoint and add task-reference persistence then; no ECS code or
fields exist in v0.

The Taskiq task is a thin adapter calling
`api.execution.worker.execute_run(run_id: UUID)`. A class
wrapper is unnecessary unless a later implementation creates a real second
caller with additional owned state.

The run store serializes admission with a PostgreSQL transaction advisory lock,
then conditionally claims the oldest queued run whose account has active capacity.
Lifecycle rows are the shared reservations; `PAPER_BETA` owns account/global caps.
A successful claim returns `ClaimedRunRead` with its required start timestamp.
Taskiq deliveries wake the database queue drain; stale deliveries are harmless.
Taskiq concurrency is a separate local process ceiling.

After a successful claim, `execute_run`:

1. resolves and validates the run's exact owned graph revision once;
2. converts the already-decoded `PaperRunConfig` to the existing `BotConfig`;
3. resolves the code-owned factory by definition ID and creates the bot with
   the decoded run config and resolved graph;
4. starts heartbeat and stop polling;
5. attaches the web observer and calls `polybot.runtime.run_bot()`; and
6. records the lifecycle outcome defined in the product specification.

These are trusted internal steps. Do not repeat request/config shape checks
inside them.

Stop is a durable status change. The worker polls PostgreSQL; no Redis-assisted
stop path is needed in v0. Lease reconciliation marks an expired non-terminal
owned run `interrupted`. It never relaunches it.

The API owns terminal completion when it stops a queued run. That conditional
`queued -> stopped` update and its terminal lifecycle event are one PostgreSQL
transaction, followed by a Redis wake-up after commit. A repeated stop observes
the existing terminal state and does not append another terminal event. A stop
of an owned run changes only the durable status to `stop_requested`; the worker
owns its later `stopping` and terminal transitions. Delivery failures preserve queued runs for scheduled recovery.

The web observer preserves the existing synchronous, fail-open
`RuntimeObserver.emit()` contract. `emit()` does bounded in-memory projection
and enqueue only. Owned async work writes PostgreSQL and publishes Redis. On
graceful stop it drains accepted durable events before the terminal lifecycle
event. Do not add retry queues or alternate persistence when those services
fail.

## Chart Data Flow

This section is the sole owner of chart cadence and durability:

```text
accepted runtime events
  -> presentation-neutral projections
  -> every 250 ms: LiveChartEvent -> Redis Pub/Sub -> SSE (ephemeral)
  -> every 1 s: LiveStreamHealthEvent -> Redis Pub/Sub -> SSE (ephemeral)
  -> every 1 s: chart.sample DurableEvent -> PostgreSQL -> Redis wake-up
```

`LiveRunEvent` is the discriminated union of `LiveChartEvent` and
`LiveStreamHealthEvent`. The event persistence section owns which inputs are
durable. The browser merges its detailed in-memory live window with loaded
durable samples but preserves their different resolution. On initial hydration
it uses only the newest bounded durable-event page. Explicit older-page requests
may expand chart history, but the chart retains at most the shared
`MAX_CHART_HISTORY_POINTS` (currently 720) newest durable samples and never
auto-drains the complete run history.

Each durable `wallet.timeline` payload stores the canonical projected chart
point, so reload does not reconstruct labels, source keys, or decimal notionals
for rendering in the browser. Browser ingress verifies the stored point against
its trade using the generated wallet-label and source-key policy, then renders
the canonical point unchanged. The terminal `stream.health` event is likewise the reload
fallback until a newer live health frame arrives.

The one-second durable cadence is an explicit v0 storage budget: at most 86,400
scheduled `chart.sample` rows per continuously active run-day, in addition to
semantic events. Graceful observer shutdown appends one final sample before the
terminal health summary and lifecycle event so terminal detail does not lose
the run's last partial second. v0 does not compact or delete samples. Capacity
planning for the scheduled rate is required in Slice 12F; retention remains
post-v0 scope.

Slice 12E extracts only the pure pieces actually needed by both terminal and
web from the current terminal implementation. Shared code belongs in a
dependency-light module under `polybot`, never under `api` or
a Rich/ECharts module. Keep the existing `polybot.performance` valuation owner.
Move the stable token cap, cadence, bounds/resampling helpers, market projection,
and wallet bucketing only as each gains its second consumer. Do not create a
generic `ChartPolicy`, `ProjectionManager`, or all-purpose chart service.

The shared terminal/browser wallet scenario locks integer-millisecond bucket
boundaries and exact-decimal notional tiers so renderer-specific glyph and
symbol choices cannot change the underlying grouping semantics.

Finite availability and wallet-bucket values used on the wire are typed enums;
reuse existing `Side` and valuation-quality types where their meaning is
identical. Render colors and glyphs remain frontend-specific.

## SSE Delivery

Through Slice 12D, the SSE route carries durable events only. It:

1. accepts an `after_event_id` query value within the generated browser-safe
   durable-event cursor range for the first connection;
2. prefers the standard validated `Last-Event-ID` header on browser reconnect;
3. rejects a missing run with the route's normal `404` before opening the
   streaming response;
4. replays later durable rows in ascending ID order;
5. subscribes to the run's Redis channel;
6. rechecks PostgreSQL once to close the replay/subscribe race; and
7. sends later durable events with their database ID.

Replay and recheck reads use the same bounded maximum batch size as HTTP event
pages. A long reconnect backlog can require multiple ordered PostgreSQL reads;
no individual query or decoded batch is unbounded.

Durable transport is at-least-once across reconnects. The frontend adapter
deduplicates durable database IDs so each committed event is presented once.
The terminal lifecycle event is written last; the stream closes after sending
it. The stream also sends idle comments and releases Redis resources on
disconnect. Redis is required for live continuation. Do not add a polling
fallback for Redis outages.

Slices 12B through 12D use one Redis run-channel frame: the durable event ID as
strict unsigned base-10 ASCII within the generated browser-safe cursor range.
It is a wake-up hint, not an SSE payload or source of truth; after a valid
frame, the subscriber reads PostgreSQL after its current cursor. Malformed
frames are logged and dropped at this Redis ingress boundary.

Slice 12E extends that same channel with JSON `LiveRunEvent` frames. The
subscriber distinguishes the existing strict decimal wake-up from a JSON frame,
validates JSON as `LiveRunEvent` once at ingress, and logs and drops malformed
input. Live events are sent without an SSE ID. Slice 12E also adds
`LiveChartEvent` and `LiveStreamHealthEvent` as explicit SSE-route schemas
alongside `PersistedDurableEvent` so OpenAPI generates every frontend payload
type.

## HTTP API

- `POST /auth/register` — create an unverified account and sign in; email verification is required before launching runs for new accounts.
- `POST /auth/login` — sign in with email and password.
- `POST /auth/logout` — revoke the current session and clear its cookie.
- `GET /auth/me` — restore the current user's safe account view.
- `GET /auth/account` — read verification status.
- `POST /auth/password/reset/request` — request a conditional reset link.
- `POST /auth/password/reset/complete` — redeem a reset link and replace credentials.
- `POST /auth/email/verification/request` — request or resend a verification link.
- `POST /auth/email/verification/complete` — prove mailbox ownership and replace credentials.
- `POST /auth/password/change` — reauthenticate, change password and revoke all sessions.
- `POST /auth/sessions/revoke` — reauthenticate and revoke other/all sessions.
- `POST /account/deletion` — reauthenticate the current account, quiesce work and revoke all access; return 202 before bounded erasure.

All remaining routes require a session except minimal health readiness.
Resource IDs are scoped to the current owner and return 404 when inaccessible.


- `POST /graphs/preview`: validate a draft graph and synthetic event, then return node results and intended orders without any broker submission, persistence, or network reads.

The route prefix `/api/v1` is defined here once. The current API has only:

- `GET /bot-definitions` — all public descriptors in display order.
- `GET /usage` — authenticated account allowances and current owned resource counts.
- `GET /markets/search?q=&limit=` — bounded active market suggestions via the official SDK.
- `POST /markets/lookup` — read-only exact metadata lookup for selected slugs.
- `POST /graph-templates` — create a reusable graph template.
- `GET /graph-templates` — list graph templates by name.
- `GET /graph-templates/{template_id}` — read one template.
- `PATCH /graph-templates/{template_id}` — update its name and/or graph.
- `POST /bots` — validate and save a bot; graph-capable bots copy a template.
- `GET /bots` — list non-deleted saved bots, newest updated first.
- `GET /bots/{bot_id}` — read one saved bot and its latest graph revision.
- `PATCH /bots/{bot_id}` — replace its validated non-graph configuration.
- `DELETE /bots/{bot_id}` — soft-delete an owned bot; return empty `204`, `409`
  while any run is nonterminal, or the normal `404` for missing, deleted or
  foreign-owned bots. All configuration/revision endpoints and new launches
  exclude deleted bots.
- `POST /bots/{bot_id}/graph-revisions` — append an immutable graph revision.
- `GET /bots/{bot_id}/graph-revisions/{revision_id}` — read an owned revision.
- `POST /bots/{bot_id}/runs` — snapshot and launch the latest saved bot.
- `GET /runs` — active runs plus retained terminal history from `HistorySelection`, newest first.
- `GET /runs/{run_id}` — one run; Slice 12E adds its event-derived summary.
- `POST /runs/{run_id}/stop` — idempotently request/complete stop.
- `GET /runs/{run_id}/events?before_event_id=&limit=` — the newest bounded
  durable-event page before an optional exclusive cursor, returned in ascending
  display order with the next older cursor.
- `GET /runs/{run_id}/events/stream` — durable replay/continuation SSE; Slice
  12E adds ephemeral live chart and stream-health frames.
- `GET /health` — database and Redis readiness for the private deployment.

Both event routes require the run to exist and return the normal small `404`
when it does not.

Market discovery uses a lifespan-owned async SDK adapter. Search accepts a
trimmed 2–200 character query and 1–20 results (default 12), fetches one upstream
page with a five-second timeout, and returns `{markets, has_more}`. Each market
contains `slug`, `condition_id`, `question`, nullable `event_title` and
`end_date`, and `is_open_for_trading`. Lookup accepts a nonempty `{slugs: [...]}` bounded by `MAX_SELECTED_MARKETS`,
deduplicates trimmed slugs, omits missing markets, and retains unavailable
markets for saved-selection display. Malformed requests return 422; upstream
failures return a safe 503. Newly selected slugs are resolved again on create
or configuration update; missing/unavailable additions return a field-level
422. Unchanged saved selections do not need to remain open to edit other
settings. Runtime market validation and live-trading gates are unchanged.

UUIDs, enums, cursors, headers, and bodies are typed at FastAPI ingress. Use
FastAPI's normal validation response and small `HTTPException` details for 404
and stale-definition 409. Do not build a custom problem-details framework,
generic pagination framework, status filtering, or links in v0. Durable events
use only the cursor page contract above because their append-only history can be
unbounded.

`RunRead` exposes the row fields, the parent bot’s `bot_deleted` flag, and the resolved graph revision number and
exact graph for historical display. It also carries nullable `latest_equity`
and `equity_status`, derived from the latest durable `chart.sample`, plus
nullable `latest_runtime_failure`, derived from the latest durable
`run.failure`. None of these computed views are persisted on the run row.

`GET /health` executes a PostgreSQL `SELECT 1` and Redis `PING`. It returns
`200` with exactly `{"status": "ok"}` only when both succeed; otherwise it
returns `503` with the small detail `service unavailable` and does not expose a
dependency error.

## Frontend

- Build a static, client-rendered SvelteKit TypeScript application at `/` with
  the API same-origin at `/api/`.
- Export OpenAPI deterministically and generate the Fetch client/types with
  `@hey-api/openapi-ts`. Generated files are never edited.
- Use the generated client for ordinary HTTP. Slice 12D's sole handwritten
  transport is a small EventSource adapter using generated persisted-event
  types; Slice 12E extends it with the generated `LiveRunEvent` variants.
- Validate successful generated-client responses by operation before exposing
  them to route state, including JSON content type, non-empty bodies, finite
  state values, nested stream rules, and discriminated graph nodes. The
  EventSource adapter performs the equivalent durable/live event validation.
- Hydrate run detail from the newest bounded durable-event page, open SSE after
  that page's newest ID for race-free continuation, and request older pages only
  from the exclusive cursor. Retain at most the loaded page count times the
  API default event-page limit, including hidden chart samples. Streaming evicts
  the oldest overflow and sets that cursor to the oldest retained event so
  evicted history remains accessible. Reserve a page during an older-page fetch,
  rolling back that capacity on failure; a response overtaken by streaming must
  not reset the advanced cursor or introduce a history gap. Terminal hydration
  does not open a stream, and receipt of a terminal lifecycle event closes the
  current stream.
- Use Ajv only for immediate form feedback against the catalog schema. Do not
  create a parallel TypeScript form contract.
- Render the market-slug widget as a multi-market combobox in create and edit
  forms: 300ms debounce, cancellation and stale-result protection, keyboard
  navigation, event/question/slug/date metadata, removable selected rows,
  loading/empty/error/retry states, and the policy-derived `MAX_SELECTED_MARKETS` selection cap. Query and selection
  limits come from generated backend fixtures. Existing selections hydrate by
  exact lookup and remain removable if closed, missing, or temporarily offline.
- Present the generated FastAPI validation response without duplicating its
  rules: field issues belong under their controls, graph issues belong beside
  the canvas, and failed saves preserve the edited state.
- The new-bot page selects the graph-capable server definition internally and
  presents configuration plus graph editing as one form. It starts from the
  descriptor's starter graph or another bot's latest graph.
- Bot creation uses the existing graph-template endpoint as an internal
  compatibility step before `POST /bots` copies revision 1. The frontend does
  not expose template selection or management, and the legacy template route
  redirects to the new-bot page.
- The bot detail page saves settings and graph changes from one workspace,
  appends graph revisions when needed, and runs only when there are no unsaved
  changes. Run detail always shows the exact historical revision.
- Wrap Apache ECharts in one thin `EChart.svelte` component that owns init,
  option updates, resize, and dispose. Pages and domain components do not call
  ECharts lifecycle APIs.
- Keep market, equity, and wallet option building in their respective domain
  components. The combined chart component owns layout/toggle composition only.

## Deployment Configuration

Docker Compose contains the static frontend/reverse proxy, multi-worker FastAPI,
Taskiq worker, PostgreSQL, Redis, and a one-shot Alembic migration command. Only
the same-origin entrypoint is exposed.

One typed settings model parses the database URL, Redis URL, worker concurrency,
heartbeat interval, and lease interval at process startup. Concurrency and
numeric intervals must be positive, and the lease must exceed the heartbeat.
The worker-concurrency default derives from `PAPER_BETA.global_active_runs`
through `DEFAULT_WORKER_CONCURRENCY`.

Multiple Uvicorn workers are supported because ownership and events are not
process-local. Scaling API workers does not change bot capacity.

Slice 16 extends this deployment boundary with runtime-only secret files, exact
schema compatibility, immutable release manifests and a TLS Caddy entrypoint.
The selected topology and release/rollback contracts live in
[`beta-deployment.md`](beta-deployment.md). Startup settings are owned by
`api.deployment.settings`; database/Redis adapters retain URL parsing ownership.
Public ingress remains closed pending all readiness slices.

Secret-file IO runs outside the API/worker event loop and each resource lifetime
reuses its parsed settings. The browser refreshes an older run snapshot when the
initial event page already includes a different lifecycle state, preventing that
state from being lost behind the SSE cursor. This also restores terminal status
correctly when a run ends during page hydration.

## Proportional Test Contract

Each slice's Acceptance section owns its required tests. Combine related
assertions into scenario tests. Add a separate edge-case test only when it covers
a distinct repository-owned branch that could regress; never add tests solely
to exercise framework/library behavior.

## Deferred Without Scaffolding

Organization tenancy, payments, ECS, EventBridge, retention/deletion,
scheduling, executable node programming, and live trading are later products. v0 creates
no fields, tables, interfaces, routes, feature flags, or placeholder modules for
them, except the explicitly required `RunLauncher` seam.

Slice 15 supplies authentication and individual-user ownership. Organization
tenancy and the other deferred products remain outside this slice.

## Slice 15: Identity and Authorization

Product decisions are recorded in the specification's
[users extension](web-control-plane-spec.md#slice-15-users-and-private-ownership).
The implemented technical contract follows. Its bounded policy and local data
reset were explicitly approved before runtime implementation.

### Approved implementation policy (September 8, 2026)

The user approved these values and an explicit local pre-auth database reset.
`api.auth.policy` owns the numeric policy below; a regression test checks this
inventory against the runtime constants. Passwords preserve exact input. The
pinned `argon2-cffi==25.1.0` library supplies Argon2id; `email-validator==2.3.0`
normalizes email without DNS or delivery, followed by case folding (dots/plus-tags
retained). Sessions store SHA-256 digests and use host-only HttpOnly SameSite=Lax
cookies. HTTPS is required unless `POLYBOT_AUTH_ALLOW_HTTP=true` explicitly permits
local HTTP. `POLYBOT_AUTH_ORIGIN` is validated and canonicalized at startup;
mutations require that browser Origin and JSON content type. Shared Redis limits
apply per client IP and return Retry-After on exhaustion.

<!-- auth-policy:start -->

| Policy | Value |
| --- | --- |
| Password length (Unicode characters) | 15–128 |
| Email maximum length | 254 |
| Argon2id memory (KiB) | 19456 |
| Argon2id iterations | 2 |
| Argon2id parallelism | 1 |
| Session entropy (bytes) | 32 |
| Absolute session lifetime (seconds) | 604800 |
| Maximum session recheck interval (seconds) | 15 |
| Authentication request maximum (bytes) | 4096 |
| Rate-limit window (seconds) | 900 |
| Login attempts per window | 10 |
| Registration attempts per window | 5 |

<!-- auth-policy:end -->

The password-length policy above applies when creating or replacing a password.
Login and current-password reauthentication accept 1–128 characters and verify the
stored Argon2 hash. Explicit `POLYBOT_ENVIRONMENT=development` enables a startup
seed in `api.auth.development`: create the verified `a@a.a` / `a` account if absent,
using the migrated schema and the normal password hasher. An unset environment
never enables seeding; production configuration forbids it. The unique email
constraint handles simultaneous API startup, and existing accounts are preserved
without resetting passwords, verification, suspension or ownership. This is local
seed data, not an Alembic migration or a special login endpoint. Seed failures
abort startup. Ordinary registration, cookies, CSRF, attempt limits and sessions
continue through the existing auth boundaries.


The application uses only
ASGI client addresses; deploy Uvicorn with proxy headers disabled by default, or
explicitly trust only a controlled reverse proxy that overwrites forwarded headers.
Never configure wildcard forwarded-address trust. Duplicate signup returns a
generic 409; wrong/unknown login shares a generic 401 and Argon2 work pattern.

The initial migration creates mandatory bot/template ownership on a fresh schema.
The September 10 local history consolidation and disposable-data reset are approved;
old databases use the explicit recreation script, never an implicit owner backfill.
Future resets of retained account data require explicit authorization.

### Identity and credentials

- Keep identity, credentials, sessions, and HTTP authorization in `api`, with
  focused owning modules. Do not introduce auth dependencies into `polybot`,
  bot configuration JSON, graph evaluation, or CLI workflows.
- Add `users` with a stable UUID primary key, unique normalized email,
  password hash, and creation timestamp. Ownership references the UUID.
  No provider registry, external-identity table, verification flag, role, or
  account-profile scaffolding is needed yet.
- Normalize emails at ingress using a maintained email-validation library,
  with one documented case-insensitive login policy shared by registration and
  login. Preserve dots and plus-tags; do not infer provider-specific aliases.
  Enforce normalized uniqueness in PostgreSQL, including concurrent signups.
  Syntax validation must not perform mailbox verification or send messages.
- Hash passwords through a maintained Argon2id library; never store or log
  plaintext passwords. Preserve password input exactly and reject oversized
  input without truncation. Pin the selected dependency, document password
  limits and hash settings, and keep expensive hashing off the async event loop.
  Unknown-email login uses the same password-verification work pattern and
  generic failure response as a wrong password.

### Sessions and HTTP boundary

- Use an opaque random session token in a host-only `HttpOnly`, `SameSite=Lax`
  cookie, with `Secure` for HTTPS deployment. Store only a token digest, user
  foreign key, and creation/expiry timestamps in PostgreSQL `sessions`.
  A local HTTP development exception must be explicit. Do not put auth tokens
  in browser storage, URL query parameters, or queue payloads.
- Issue a fresh session after registration/login. Validate expiry on the
  server; logout deletes the current session and clears its cookie. Sessions
  work across API processes. Database failure must never grant anonymous or
  fallback access. Auth responses and private API responses are not shared-cacheable.
- Keep the existing same-origin frontend/API deployment. Apply CSRF protection
  to all state-changing browser requests, including login and registration.
  The mechanism enforces the configured application Origin and JSON content
  type, rejecting missing/foreign origins for mutations; do not treat SameSite
  alone as sufficient. Do not enable permissive credentialed CORS.
- Add routes under the existing API prefix: `POST /auth/register`,
  `POST /auth/login`, `POST /auth/logout`, and `GET /auth/me`. Successful
  registration/login returns only the safe current-user view (`id`, `email`)
  and sets the cookie. `/auth/me` returns that view or `401`; logout is
  idempotent and clears even an expired cookie.
- Keep registration, login, logout, and minimal health readiness reachable
  without a valid session. Require authentication for every other application
  endpoint, including catalogs, market lookup/search, graph preview, and streams.
  Return `401` for absent/invalid sessions and `404` for inaccessible resource
  IDs. Do not expose password hashes, session digests, other users' emails, or
  credentials in response schemas, validation errors, or logs.
- Bound login/registration attempts using the existing shared infrastructure,
  not process-local counters; use `429` for throttling. Limits and proxy trust
  follow the approved policy above. Registration handles duplicate emails
  without a database error leak.

The password and session recommendations follow current
[OWASP password-storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
and [session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
The same-origin request policy follows
[OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
Sources and the pinned password/email library APIs were checked September 8, 2026.

### Resource ownership and execution

- Add a non-null, indexed `bots.owner_user_id` foreign key to users and an
  equivalent owner field on mutable `graph_templates`. Change template-name
  uniqueness from global to per-owner. Assign owners server-side and exclude
  ownership from accepted create/update bodies.
- Runs inherit through `runs.bot_id`; graph revisions through their `bot_id`;
  events and summaries through their run. Do not duplicate user ownership on
  these child rows. Owner changes remain unsupported. Soft deletion sets
  `bots.deleted_at` under the same bot-row lock used by edits and launches, after
  checking that no nonterminal run exists. Both HTTP launches and the run store
  lock and reject deleted bots. Saved-bot usage excludes deleted configurations.
  Run ownership, history selection and snapshot reads continue to join the retained
  bot row without filtering its deletion marker. `RunRead.bot_deleted` tells the
  browser to display a deleted-configuration label instead of an edit link; run
  details, immutable graphs and events remain subject to normal retention.
- Scope list and resource queries by the current user inside owning stores.
  Apply the same policy to bot config changes, revision reads/appends, template
  CRUD/copy, run creation/read/stop, summaries, durable event pagination, and
  SSE replay/live delivery. Authorize references as well as target IDs before
  copying data or committing/enqueueing side effects. Existing row locking and
  snapshot consistency still apply.
- Worker access remains a trusted internal path from persisted run IDs. It
  does not accept browser identity or session tokens. Login expiry/logout ends
  user access, not already-authorized background runs. Keep the existing worker
  lifecycle, paper broker, and live-execution gates unchanged.
- Authenticate SSE connections before reading history or subscribing. Bound
  the lifetime of an open stream with session rechecks so expiry/logout stops
  further private delivery within a documented interval; reauthenticate every
  reconnect. Browser logout closes its streams immediately. Preserve durable
  replay and cursor semantics without leaking whether another user's run exists.
- Continue exposing code-owned starter/example graphs as shared catalog data
  to authenticated users. Do not convert user-created templates into shared
  catalog entries or add public access paths yet.

### Frontend and completed implementation checkpoints

Keep static SvelteKit and the generated API client. Add registration/login,
current-user loading, and logout to the existing shell. Wait for authentication
before fetching private data. A `401` closes streams, clears private state, and
returns to login; a `404` remains an unavailable-resource outcome. Switching
accounts must not reuse the previous user's bot/run data or copy options. Any
post-login return path must stay within the application origin.

The policy checkpoint and local alpha reset were explicitly approved September 8,
2026. `api.auth` owns password hashing, credential ingress, PostgreSQL sessions,
Redis attempt limits, CSRF checks and stream authorization. `BotStore` and
`GraphTemplateStore` require an explicit current-user ID; `RunStore.read_owned`
and `list_owned` join through the bot, while trusted worker operations continue
using persisted run IDs. HTTP authorization happens before event reads, summaries,
stop transitions and launch delivery. No session token enters Taskiq payloads.

The shell restores `/auth/me` before mounting private pages. Account changes unmount
private components and close registered streams; cross-tab account changes trigger
fresh restoration. A bounded current-user refresh detects expiry even on idle or
historical pages. Redirect targets accept only local paths. Generated contracts
and the generated runtime fixture supply account response shapes and form limits.

The consolidated initial migration creates ownership and per-owner template-name
uniqueness directly. Downgrade to `base` removes the complete schema. The approved
local reset does not authorize future deletion of retained account data.

Verification lives in `backend/tests/control_plane/test_auth.py` and
`frontend/e2e/accounts.spec.ts`, plus the existing PostgreSQL snapshot/worker suite.
`api.auth.store` owns identity persistence and its token boundary; cookie
attributes have one owner. Auth ingress, private cache headers and service-failure translation have
independently registered middleware boundaries in `api.http.middleware.private_cache`
and `service_failures`; generated errors remain no-store. `api.http.sse` separates subscription, replay,
framing and authorized stream lifetime. Session rechecks are mandatory, including
during replay; infrastructure disconnects produce a visible reconnecting state.
The browser `AccountSession` owns one typed lifecycle state and derives account,
readiness and error views from it. Session request adapters normalize HTTP outcomes
before state transitions. It delegates private stream cleanup, cross-tab signals
and generated-client interception. Concurrent restoration
is coalesced and stale responses cannot undo logout or account switching. New
restoration cannot begin while revocation is pending. SSE response ingress rejects
naive, malformed and impossible calendar timestamps; structural guards are
independent of decimal arithmetic dependencies.

Account CI runs the complete Python suite and Chromium acceptance against real
PostgreSQL/Redis and rejects skipped tests. Test harnesses require explicit local
`*_test` databases and nonzero Redis databases with explicit ports; cleanup deletes
only authentication throttle keys. Active browser streams are checked across
logout, external session revocation and cross-tab switching.

The browser harness uses real PostgreSQL, Redis and auth/resource routes; only
market discovery and execution delivery use test fixtures. No Polymarket protocol
behavior changed, so a PolymarketDocs check is not required for this slice.

## Review follow-up — September 2026

The worker observes bot execution and its required heartbeat/stop monitor together.
A failed monitor interrupts the owned bot and records run failure; a disappeared
run row is an infrastructure failure. Both tasks are cleaned up on exit.

Graph models separate node and edge schemas from aggregate topology validation,
and catalog descriptors have trigger and functional owners. Preview validates
event semantics at HTTP ingress and validates intended orders before returning a
plan. Evaluation reasons are finite unions of existing graph, book, wallet, and
fill reason contracts, exposed in OpenAPI and the generated catalog fixture.
Preview cash and operation scalar defaults have named catalog contracts.

Backend event payload families and frontend durable-event validators separate
lifecycle, broker, portfolio, and chart responsibilities behind one event dispatch
boundary. Response validation distinguishes revision append (updated saved bot)
from revision detail (graph revision). Canvas projections, factories, catalog
lookup, and connection/port rules have distinct frontend modules. Home, bot
builder, run detail, chart dashboard, and failure-detail styles live near their
owners; tokens, shell, reset, controls, and shared primitives remain global.

Persisted and live wallet chart payloads validate wallet address shape and
canonicalize case/whitespace at their model boundary. Durable wallet timeline
payloads apply the same normalization to the trade and its chart point, then
check that the point matches its source trade and outcome.

Portfolio snapshots, settlements and their validation policies have a dedicated
payload owner. Broker payloads share its public portfolio validator without
owning standalone portfolio event contracts.

## Slice 17: Shared resource accounting

`api.limits.policy` owns the paper-beta allowance values, exported through the
private usage endpoint. `RunAdmission` serializes queue admission, active claims
and terminal release with one PostgreSQL transaction advisory lock. Run lifecycle
rows are the reservations; terminal states release capacity atomically without a
second counter or reservation table. Bot ownership supplies the account, including
worker claims. Saved-resource creation locks the owning account row; graph
revision limits share the existing bot-row lock. Existing rows count toward
allowances and are never reset by this slice.

Taskiq deliveries wake a database queue drain. Each process selects FIFO among
accounts below their active allowance, claims conditionally, executes, and drains
again on completion. PostgreSQL bounds active execution across worker instances;
Taskiq concurrency remains a local ceiling. Recovery of delivery gaps and dead workers remains
Slice 18; scheduled reconciliation now releases lost worker reservations.

Redis server-time scripts atomically bound account and global request budgets and
open-stream leases. Streams end before their lease expiry and release leases on
response completion or disconnect. Redis failures prevent admission; no in-memory
fallback exists. The runtime's condition registry accepts an optional local cap,
set by the web worker, and rejects additional unresolved conditions before any
subscription grows. SDK transport and paper/live contracts remain unchanged.


## Slice 18: durable launch and run recovery

Launch accepts a UUID `Idempotency-Key` header scoped to the owned bot. Reusing
it returns the original immutable run snapshot and outcome, even after edits or
termination; a new key starts a deliberate new run. Omitting the header explicitly
requests a fresh run for compatibility with existing callers. The browser persists
a pending key in session storage before sending and keeps it through errors and
reload, clearing it only after navigation to the confirmed run. Identities remain
valid as long as their run history is retained. Slice 21 adds `Idempotency-Recovery`
for browser retries: missing or expired attempts return 410 without creating work.
The initial migration includes nullable identity/delivery/claim columns and a unique
bot/key constraint.

The queued row is the durable delivery obligation. The separate `recovery` process
scans on the configured recovery cadence, serializes delivery attempts in PostgreSQL, and
reissues bounded Taskiq wake hints. Redis stream trimming bounds retained hints;
they carry no authoritative execution state. A lost hint is safe because the next
scan retries it and the existing FIFO/allowance claim is conditional. Redis outages
leave queued reservations intact. PostgreSQL outages prevent claims and progress;
recovery retries when PostgreSQL returns. No active run is requeued or resumed.

Every claim creates an internal execution token. Worker transitions, heartbeat
renewal and durable/live publication check that token and a fresh database lease.
Publication locks the run row so it serializes with terminal transitions; expired
leases cannot be renewed before reconciliation. All terminal writers share
`TerminalRunWriter`: the conditional state change, lifecycle event and capacity
release commit together or roll back together. SSE periodically replays PostgreSQL
even when a post-commit Redis wake was lost; reload uses the same durable outcome.
The recovery scan interrupts expired active rows and preserves committed history.

The policy defaults below are checked against their Python owners by the deployment
contract test. A healthy scan recovers worker loss after lease expiry plus its next
tick and bounded I/O; database visibility cannot be promised during an outage.
Deployment starts/stops recovery with API and worker. Taskiq drains jobs before
cancellation; runtime cleanup and final process shutdown have separate bounds.
Unfinished paper runs report an interruption and require an explicit new launch.

<!-- reliability-policy:start -->
| Policy | Default seconds | Code owner |
| --- | ---: | --- |
| Worker heartbeat | 5 | `api.runs.lease_policy.DEFAULT_HEARTBEAT_SECONDS` |
| Worker lease | 30 | `api.runs.lease_policy.DEFAULT_LEASE_SECONDS` |
| Recovery retry | 5 | `api.execution.recovery.policy.DELIVERY_RETRY_SECONDS` |
| Dependency operation | 5 | `api.io_policy.DEPENDENCY_TIMEOUT_SECONDS` |
| Taskiq read block | 1 | `api.execution.policy.TASKIQ_READ_BLOCK_SECONDS` |
| Taskiq job drain | 1 | `api.execution.policy.TASKIQ_DRAIN_SECONDS` |
| Runtime cleanup | 10 | `api.execution.policy.RUNTIME_CLEANUP_SECONDS` |
| Taskiq shutdown | 20 | `api.execution.policy.TASKIQ_SHUTDOWN_SECONDS` |
| Worker process stop | 45 | `api.execution.policy.WORKER_STOP_GRACE_SECONDS` |
| Recovery process stop | 15 | `api.execution.policy.RECOVERY_STOP_GRACE_SECONDS` |
<!-- reliability-policy:end -->

The framework accepts an optional host execution scope around final synchronous
paper fills and resolution settlement, including portfolio and tracker mutation.
The API supplies its database lease fence. Book checks repeat after fence acquisition;
resolution callbacks run after releasing the fence to avoid nesting it with fills.
Paper/live event shapes and Polymarket adapters are unchanged.

## Slice 19: Recovery, verification and credential lifecycle

The September 10 approved policy extends Slice 15. `api.auth` owns all new identity
state. The initial migration includes nullable `email_verified_at`, a
`verification_required` flag defaulting to true, and digest-only purpose-scoped
account tokens. The earlier unverified-account backfill is superseded by the
approved disposable local reset. The HTTP launch boundary rejects an unverified required
account before reserving capacity; history, editing, Stop and authentication stay
available. No framework or execution-domain dependency on identity is added.

Random tokens use SHA-256 digests and a reset/verification purpose. Entropy,
expiry, response floor and attempt budgets are defined by the
[runtime-checked account policy](account-recovery.md). Requests replace the prior same-purpose token
under the user lock. Redemption locks the user then token, checks expiry after
waiting, updates credentials, removes all account tokens and sessions in one
transaction. Verification also records mailbox proof; reset alone does not mark
verification. Login and authenticated credential operations take the same user
lock so an old password cannot race a reset and issue a surviving session.
Authenticated changes recheck the current session under that lock as well as
verifying the current password. Reset/verification never issue a browser session.

SMTP uses Python's standard client behind `asyncio.to_thread`, certificate-checked
STARTTLS or implicit TLS, a bounded socket timeout and runtime-only configuration.
Only explicit local development permits a plaintext loopback test relay. SMTP
credentials support secret files. No provider purchase is required. Reset and
verification requests attempt the same mail delivery for eligible and ineligible
addresses, using an unpersisted random token for ineligible requests. HTTP responses and SMTP errors are generic. The configured minimum response time
reduces ordinary eligibility timing differences; slow database, quota or relay
operations can exceed that floor, so exact latency equality is not guaranteed.
No plaintext token is stored in a database, queue or log. Failed delivery does not
redeem a token and returns a generic 503; retry issues a fresh link. SMTP responses
and exceptions are sanitized at the adapter boundary.

Redis enforces the account policy attempt budgets per credential endpoint/IP
and additionally per normalized email across mail requests, including unknown addresses. Limits never lock an account. Request bodies
retain the 4 KiB limit, secret-safe validation and same-origin JSON CSRF boundary.
Links derive from `POLYBOT_AUTH_ORIGIN`, use URL fragments and a no-referrer browser
page that immediately erases the fragment with history replacement. No automatic
GET redemption, open redirect, token response or browser persistence is allowed.

This policy follows the current [OWASP recovery guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html),
checked for this slice. SMTP is an application account dependency; no Polymarket
protocol, SDK or endpoint behavior changes.

## Slice 20: Operator and observation boundaries

`api.operations` owns the maintenance CLI, durable incident control and mutation
journal. Host OS/Docker access is the authorization boundary; ordinary web sessions
cannot invoke it. Lock order is run-admission advisory lock, account row, then run
rows. Login/session issuance shares the account lock; launch and worker admission
recheck account suspension inside the admission transaction. Global control is a
required singleton seeded by the initial migration; missing state fails explicitly.
Operator termination and lifecycle events commit with the control and audit row.

The recovery process also samples operational measurements every five seconds.
PostgreSQL supplies queue depth/age, stale leases and database bytes; Redis supplies
worker process presence, per-minute HTTP status counts and recent feed observations.
Missing or failed probes produce unknown/unavailable alerts, never zero-valued
healthy measurements. Log records contain only bounded typed operational fields;
request paths, query strings, bodies, emails, headers, SDK payloads and exception
text are excluded. The deployment operator reads structured alerts in recovery
logs; each alert includes its effective threshold and response instruction. No external
monitoring provider or public metrics endpoint is introduced.

Slice 20 operational logs use typed payload-free records and a bounded background
log writer; sink saturation is reported by the next accepted overflow record.
Counter/presence Redis adapters validate stored values; feed envelopes preserve
the original observation time and classify missing lag, invalid JSON and expired
health as unavailable. A separate `api.events.health.writer.RunHealthWriter` shares the
event writer execution lease without adding side effects to generic publication.
The monitor uses its own cadence, verifies the required incident singleton, and
is supervised by recovery. The CLI returns typed status/inspection/mutation shapes;
unhealthy status checks exit nonzero. HTTP admission exposes `incident_paused`
(503) and `account_suspended` (403) without requiring detail-string parsing.

## Slice 21: Data lifecycle boundaries

`api.lifecycle` owns bounded history/account/audit maintenance and the private
restoration quarantine commands. The initial migration includes hidden-history and separate
restore-quarantine markers plus minimal deletion receipts without a user foreign
key. Account access has one Python/SQL predicate covering both suspension and
restore quarantine. Run history age/count selection is shared by reads and cleanup.
Maintenance runs under recovery supervision; deletion uses the same admission →
account → run lock order as launch/operator controls. Physical removal follows
event → run → graph revision → bot → identity references; stale execution leases
cannot write after terminal transition or purge.

Host-only `scripts.beta_backup` uses PostgreSQL container utilities and age, with
systemd timers for backup and RPO checks. Restore decrypts before a single
transaction into a new isolated project and quarantines all access/jobs before any
application service may start. See [the data runbook](beta-data-lifecycle.md) for
approved policy, manual reconciliation and non-database secret custody.

## Guided first use (Slice 22)

The private guided-setup route composes the existing catalog examples, `LaunchForm`
and market selector into choose/configure/review steps. It calls `SavedBotDraft`,
shared with the full editor, to create a private template and saved bot. The
`savedDraft` package owns confirmed-write state, a separate write-result adapter
and UI feedback; HTTP client rejection classification is shared with launch. Confirmed
writes are reused during an in-page retry. Unknown write outcomes block further
sends from that draft and direct users to inspect their saved bots before creating
another; confirmed rejections stay retryable. This does not claim durable save
idempotency across reloads. The existing saved-bot page owns explicit launch,
verification, market validation, capacity and paper gates.

The run-reading guide derives status and loaded order/fill counts from the
existing dashboard contracts. It distinguishes missing/stale book reports,
reconnection and failures from a condition that may legitimately be waiting.
Counts describe the loaded history window, and cached health is identified as
last reported rather than asserted current. No graph debugger or new strategy
engine is introduced.

Browser acceptance supplies deterministic normalized books to the real catalog
bot, `BotRunner`, paper broker, observable broker and execution lease coordinator.
The managed fixture launcher uses production queue recovery and lease expiry,
deduplicates in-flight hints, and drains tasks before closing API resources. A
shared exact-one-market resolver rejects ambiguous fixture selection. Typed
fixture cases live in `backend/tests/control_plane/onboarding_policy.py` and
generate a separate browser test contract. A shared explicit clock and seeded
jitter keep the market scenarios controlled while exercising real elapsed time.
Those inputs live only in `backend/tests/control_plane/onboarding_fixture/`;
production adapters and Polymarket protocols are unchanged.

## Public information boundary (Slice 23)

The exact static information routes are owned by `$lib/public/navigation` and
render before session restoration in the app shell. Public navigation disables
SvelteKit data preloading; no public component imports a private API operation.
The shell restores the session when navigation enters an account or private route,
and keeps private children keyed to the authenticated account. An expired session
clears private state/streams without redirecting an information page. Public pages
read generated allowance/lifecycle policy, not account usage. The existing HTTP
method/path allowlist and ownership predicates remain unchanged.

`api.service_identity` owns the application name used in mail and the generated
browser contract; `$lib/serviceIdentity` supplies shared browser branding.
`$lib/public/identity` carries that name and the missing operator/support contact. Help links use the existing account/recovery routes.
The public support page has no submitting form while its mailbox is unconfigured.
The release checklist in [beta launch](beta-launch.md) requires replacing these
placeholders and testing contact delivery before the private ingress can open.
