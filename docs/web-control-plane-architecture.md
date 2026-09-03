# Web Control Plane v0 Architecture and API

Status: planned overall; Slices 12A through 12E and Slices 13A through 13F are
implemented.
This document is the single technical contract for the product in
`web-control-plane-spec.md`.

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
  Slices 12A-12F and Slices 13A-13F in `docs/implementation-plan.md`.

The implementation plan assigns architecture-owned work and acceptance to a
slice. It may use canonical contract terms when doing so, but it does not define
an independent shape or algorithm; this document controls if wording conflicts.

## Boundaries and Stack

- `polybot` remains independent of FastAPI, SQLModel, Taskiq, Redis, SvelteKit,
  and the new control-plane package.
- `polybot_control_plane` may import `polybot`; the reverse import is forbidden.
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

- `polybot_control_plane.catalog.values`: dependency-light `DefinitionId`,
  `SelectionMode`, `WidgetKind`, label, and widget-key contracts;
  `polybot_control_plane.catalog.contracts`: `BotDefinitionDescriptor`.
- `polybot_control_plane.bots.contracts`: saved-bot request/read and immutable
  graph-revision contracts.
- `polybot_control_plane.catalog.graphs.values`: dependency-light graph enums,
  limits, and semantic handle values;
  `polybot_control_plane.catalog.graphs.types`: constrained identifiers, field
  paths, and handle contracts.
- `polybot_control_plane.catalog.graphs.catalog`: public node descriptors,
  framework-derived `GraphNodeCatalog`, and the code-owned catalog snapshot.
- `polybot_control_plane.catalog.graphs.contracts`: validated `NodeGraph`, node,
  and edge contracts plus their validation limits. The browser consumes the
  generated limits and catalog, while backend-generated valid and invalid
  graph cases lock its runtime topology validator to the Python contract.
- `polybot_control_plane.catalog.graphs.starter`: the starter graph snapshot.
  Focused private supporting modules discover `BaseBot` hook signatures,
  traverse dataclass and explicitly marked computed outputs, describe the
  trusted broker action, and share graph-validation primitives. The package
  initializer remains empty rather than re-exporting these owners.
- `polybot_control_plane.catalog.node_based.bot`: concrete `NodeBasedBot` hook
  handling.
- `polybot_control_plane.catalog.node_based.evaluator`: orchestration for the
  compiled graph, with focused compiler, value, action, and result owners.
- `polybot_control_plane.runs.status`: `RunStatus` and its lifecycle policy;
  `polybot_control_plane.runs.contracts`: `PaperRunConfig` and `RunRead`.
- `polybot_control_plane.events.kinds`: dependency-light durable and live event
  discriminators; `polybot_control_plane.events.contracts`: `DurableEvent` plus
  their discriminated payloads. Slice 12E adds `LiveChartEvent`,
  `LiveStreamHealthEvent`, their `LiveRunEvent` union, and the `chart.sample`
  durable variant when it first implements live observability cadence.
- `polybot_control_plane.execution.launcher`: the `RunLauncher` protocol.
- `polybot_control_plane.graph_templates`: editable catalog contracts, row, and
  persistence operations.
- `polybot_control_plane.bots`: saved-bot and immutable graph-revision
  contracts, rows, and persistence operations.

Finite wire values are `StrEnum`s. The generated frontend types come from these
Pydantic models through FastAPI OpenAPI. Tests import the enums; they do not copy
contract strings.

Graph identifier limits are owned by
`polybot_control_plane.catalog.graphs.values` and flow into the constrained
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
code-owned catalog, generated client, and disposable control-plane database move
together. Contract changes rewrite the alpha migration history and require a
database recreation instead of compatibility migrations, legacy graph decoders,
or simultaneous schema variants. A future stabilization slice may deliberately
introduce versioning when persisted compatibility becomes a product requirement.

`GraphNodeType` contains exactly `trigger`, `constant`, `comparison`, and
`broker_action`. Every node contains a unique ID, a finite bounded `x`/`y`
position, and the data variant owned by its type. Each `GraphEdge` contains
unique ID, source node and handle IDs, and target node and handle IDs. Launch
validation resolves every node and handle, enforces input cardinality and scalar
type compatibility, rejects cycles, and requires every action to have exactly
one upstream trigger ancestry. Constants can be shared within one trigger
branch; processing/action nodes cannot be disconnected or join different
triggers.

The node-based descriptor alone includes a `GraphNodeCatalog`. Trigger catalog
construction discovers every async `BaseBot` method beginning with `on_` in
class-definition order, resolves postponed annotations, requires `BotContext`
and at most one dataclass payload, and ignores return annotations. Stream-plan
and backtest-query methods are not lifecycle triggers. The catalog exposes the
opaque context handle `context` plus connectable payload fields derived through
Pydantic `TypeAdapter`. Ordinary nested dataclasses are traversed; lists and
tuples are collection boundaries, so `BookSnapshot.bids` exists but
`BookSnapshot.bids.price` does not.

Ordinary methods and properties remain hidden. The framework may explicitly
mark a zero-argument annotated computed event property as graph-safe.
`BookSnapshot.best_bid` and `best_ask` are the first such properties: best bid is
the highest executable SELL-side level and best ask is the lowest executable
BUY-side level. Both return `BookLevel | None`; discovery exposes their nested
`price` and `size` fields and propagates the parent nullability. The stored
`bids` and `asks` collections remain the single source of truth. `midpoint()` and
other unmarked behavior are not graph outputs.

Every scalar trigger field has a generated handle
`field:<dot-joined-path>` and display label
`<PayloadType>.<dot-joined-path>`; no whole-event output exists. Constants are
typed boolean, integer, exact decimal, or string scalar sources. Comparisons are
binary `equal`, `not_equal`, `less_than`, `less_than_or_equal`, `greater_than`,
or `greater_than_or_equal` nodes with one boolean output. A null comparison
input evaluates `False` without coercion.

The broker catalog explicitly publishes only
`Broker.submit(OrderRequest) -> FillEvent`; it never exposes every broker method
implicitly. Its order inputs are derived from the broker signature,
`OrderRequest`, `Side`, and their annotations. BUY and SELL are fixed-side
variants with required `enabled`, `token_id`, limit `price`, and share `size`
inputs plus the existing optional market, condition, source, and reason fields.
`cancel_all` and action-result outputs are outside the MVP.

The frontend uses only backend catalog metadata and generated types for its
palette, labels, always-visible scalar trigger handles, controls, and
connections, and strips only Svelte Flow transient state. The palette presents
a single Comparison item; its node-level select exposes every catalog operator
and removes an existing input edge if the selected operator no longer accepts
its scalar type. Drawn edges are the sole persisted record of which trigger
outputs a graph uses. The starter graph remains non-trading. A complete
supported graph can compare `BookSnapshot.best_ask.price` with a decimal constant and,
when true, submit a BUY using the event token and ask price plus a constant
share size.

At runtime, the worker resolves the run's exact bot-owned graph revision once,
then the catalog constructs `NodeBasedBot(BaseBot)` from that graph and the
decoded `PaperRunConfig`. That bot owns a focused evaluator; `BaseBot` and general
`BotConfig` do not gain graph behavior or graph fields. The graph is compiled
once to dependency indexes and deterministic topological order. Each accepted
hook invocation creates one ephemeral frame and evaluates the matching trigger's
reachable acyclic branch once. This is an event-driven DAG pass, not a state
machine or a fixed-point loop.

An action runs only when `enabled` is exactly true and all required values are
non-null, then constructs the existing `OrderRequest` and awaits
`ctx.broker.submit()`. A missing best level or required value fails closed with
a stable graph skip reason. The evaluator has no cross-event state: every
matching accepted event can submit again while its comparison remains true.
Position checks, cooldowns, once/rising-edge behavior, and dedupe must be future
explicit nodes rather than hidden action semantics. Broker results do not
recursively dispatch `on_fill` in this MVP.

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

If delivery fails, atomically update the committed run to `failed` and append
its terminal lifecycle event in one new PostgreSQL transaction, using a
sanitized `failure_detail`. Publish the durable Redis wake-up only after that
transaction commits. Do not invent a custom error taxonomy for v0.

## Persistence Contract

### Graph template row

`graph_templates` has exactly:

- `id` (UUID primary key)
- `name` (unique, trimmed)
- `graph` (validated `NodeGraph` JSON)
- `created_at`
- `updated_at`

Templates are mutable and are never referenced by bots or runs.

### Saved bot and graph revision rows

`bots` has exactly:

- `id` (UUID primary key)
- `definition_id` (immutable)
- `config` (editable resolved `PaperRunConfig` JSON)
- `created_at`
- `updated_at`

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
- `failure_detail` (nullable, sanitized)

The composite `(bot_id, bot_graph_revision_id)` foreign key prevents a run from
using another bot's revision. Graph-capable definitions require a revision and
other definitions require null; this rule is owned by the catalog. Do not add
separate launch-input/config copies, updated/claimed/stop timestamps,
latest-summary columns, execution-backend fields, user IDs, or idempotency keys.
Current summaries come from durable events. ECS can add its own reference when
an ECS slice actually exists.

The disposable alpha migration history is rewritten in place: `0001` creates
the complete graph-template, saved-bot, graph-revision, and run schema,
including Taskiq progress state; `0002` adds durable events. Later migrations
extend the event contract. This history is not a compatibility promise until a
future stabilization slice says otherwise.

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
writes use the optional-ID `DurableEvent` union; reads decode the committed row
into the required, browser-safe-ID `PersistedDurableEvent` union.

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
`polybot_control_plane.execution.worker.execute_run(run_id: UUID)`. A class
wrapper is unnecessary unless a later implementation creates a real second
caller with additional owned state.

The run store's atomic claim is one conditional database update. It returns the
typed claimed run or `None`; it does not expose a hierarchy of claim-result
types. `None` means duplicate, stopped, or terminal delivery and the task exits.
Taskiq worker concurrency, not a second database capacity algorithm, limits
simultaneous runs.

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
owns its later `stopping` and terminal transitions. Together with launch
delivery failure, these are the only API-owned terminal transitions in v0.

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
dependency-light module under `polybot`, never under `polybot_control_plane` or
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

The route prefix `/api/v1` is defined here once. The current API has only:

- `GET /bot-definitions` — all public descriptors in display order.
- `POST /graph-templates` — create a reusable graph template.
- `GET /graph-templates` — list graph templates by name.
- `GET /graph-templates/{template_id}` — read one template.
- `PATCH /graph-templates/{template_id}` — update its name and/or graph.
- `POST /bots` — validate and save a bot; graph-capable bots copy a template.
- `GET /bots` — list saved bots, newest updated first.
- `GET /bots/{bot_id}` — read one saved bot and its latest graph revision.
- `PATCH /bots/{bot_id}` — replace its validated non-graph configuration.
- `POST /bots/{bot_id}/graph-revisions` — append an immutable graph revision.
- `GET /bots/{bot_id}/graph-revisions/{revision_id}` — read an owned revision.
- `POST /bots/{bot_id}/runs` — snapshot and launch the latest saved bot.
- `GET /runs` — all runs, newest first.
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

UUIDs, enums, cursors, headers, and bodies are typed at FastAPI ingress. Use
FastAPI's normal validation response and small `HTTPException` details for 404
and stale-definition 409. Do not build a custom problem-details framework,
generic pagination framework, status filtering, or links in v0. Durable events
use only the cursor page contract above because their append-only history can be
unbounded.

`RunRead` exposes the row fields plus the resolved graph revision number and
exact graph for historical display. It also carries nullable `latest_equity`
and `equity_status`, derived from the latest durable `chart.sample`; none of
these computed views are persisted on the run row.

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
  from the server-provided exclusive cursor. Terminal hydration does not open a
  stream, and receipt of a terminal lifecycle event closes the current stream.
- Use Ajv only for immediate form feedback against the catalog schema. Do not
  create a parallel TypeScript form contract.
- Present the generated FastAPI validation response without duplicating its
  rules: field issues belong under their controls, graph issues belong beside
  the canvas, and failed saves preserve the edited state.
- The launch page saves a bot without running it. Graph-capable definitions
  select a template and explain the copy boundary.
- The template page edits reusable source graphs. The bot detail page saves
  settings, appends graph revisions, and runs only when there are no unsaved
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
The worker-concurrency default is four; this paragraph is its sole documentation
owner.

Multiple Uvicorn workers are supported because ownership and events are not
process-local. Scaling API workers does not change bot capacity.

## Proportional Test Contract

Each slice's Acceptance section owns its required tests. Combine related
assertions into scenario tests. Add a separate edge-case test only when it covers
a distinct repository-owned branch that could regress; never add tests solely
to exercise framework/library behavior.

## Deferred Without Scaffolding

Authentication, tenancy, payments, ECS, EventBridge, retention/deletion,
scheduling, executable node programming, and live trading are later products. v0 creates
no fields, tables, interfaces, routes, feature flags, or placeholder modules for
them, except the explicitly required `RunLauncher` seam.
