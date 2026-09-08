# Paper strategy graph MVP

The backend catalog is the source of truth for the editor's node types, ports,
operators and settings. Triggers are discovered from `BaseBot` hooks and annotated
event fields, including explicitly marked computed properties. Broker inputs are
derived from the allowed `Broker.submit(OrderRequest)` signature. Other operations
are explicitly registered; defining a Python method does not publish it automatically.
Svelte implements the visual representation and consumes generated contracts. The
node picker uses collapsible sections and nested operation categories from backend
metadata. Search reveals matching groups automatically and clearing it restores
the browsing state. Strategy parameters and event preview use spaced disclosure
panels with labelled fields that stack on narrow screens.

Implementation is tracked in [the two-phase checklist](graph-mvp-plan.md).
The current contract replaces the disposable alpha format without legacy decoders.

## Values and calculations

The graph exposes Number, Boolean and Text. Numbers travel as exact decimal strings,
including whole values such as `"2"`, and become Python `Decimal` during execution.
Framework integer outputs, including timestamps, become graph Numbers automatically.
The framework's Python types and broker order contracts remain unchanged. Boolean
values are never treated as numbers, and arbitrary Text is not implicitly parsed.

Number text is bounded to 256 characters and an adjusted decimal exponent of ±1000.
The browser and server use the same exported numeric syntax and limits. Arithmetic
uses a local 28-significant-digit decimal context with half-even rounding, independent
of process-global decimal settings. Round uses half-up rounding and a nonnegative
whole count of decimal places (at most 1000). Whole-number settings accept `2.0`;
`2.7` produces `whole_number_required` with the offending input handle and a
field-specific explanation. Numeric input constraints are published in the catalog. Cooldown duration is expressed in milliseconds.

Available operations are AND, OR, NOT, Is Present, Between, Select, Add, Subtract,
Multiply, Divide, Min, Max, Clamp, Round, Cooldown, Once, Deduplicate, Position,
Balance, Inspect and Log. AND and OR have 2–16 uniquely identified inputs. Between
includes both endpoints. Select has an explicit result type, inferred by its selected
node setting rather than a user-inserted cast. Its alternatives must have that type.

Custom parameters have a stable ID, a name and a typed value. Parameter nodes refer
to the graph-level definition, so the value is stored once per revision. Saving a
parameter change creates a new bot graph revision. Active runs retain the exact
revision and parameter values they were launched with.

## Unavailable data and graph execution

Each accepted hook evaluates a compiled acyclic branch in deterministic order.
Each node and action runs at most once per event. Evaluations for one bot are serial.
Constants and parameters may be shared between independent trigger branches;
processing, stateful and action nodes cannot join different triggers. Every functional
branch terminates in an action or an Inspect/Log diagnostic. Diagnostics do not require
an order. The default starter contains only a book trigger and never trades.

Values carry `available`, `missing`, `invalid`, `skipped` or `planned` status and a
stable reason. Missing comparison inputs remain missing. AND, OR and NOT preserve
unavailability instead of interpreting it as false. Is Present reports false only for
missing data; invalid inputs remain invalid. Select propagates the chosen alternative
only. An unchosen invalid alternative cannot enable an action or invalidate a chosen
available value. Both alternatives' upstream nodes still follow normal DAG evaluation;
Select is a value selector, not a branch-execution construct.

Division by zero and invalid numeric bounds produce explicit errors. No error path
supplies a guessed price, quantity, zero balance or synthetic fill. Compilation checks
all required operation capabilities before any branch can submit an order.

## Own portfolio

`ctx.portfolio` is an optional read-only `PortfolioReader`. Its synchronous `snapshot()`
returns immutable framework-owned `PortfolioSnapshot` and `PortfolioPosition` objects.
The reader is wired to the existing paper accounting owner in the paper runner and
replay, independently of broker/performance wrappers. It does not perform network I/O.
`ctx.positions` remains the external-wallet position client.

Position accepts Context and Token ID and exposes Size, Has Position and Average Entry
Price. Balance accepts Context and exposes Available Cash. One snapshot is read per
event evaluation that needs portfolio data. Later events observe completed fills and
settlements. A known absent position has size zero, Has Position false and no average
entry price. Signed positions are preserved: Has Position means size is nonzero.
An absent provider produces `portfolio_unavailable`, never an empty account. Available
Cash is current paper cash, not a buying-power or margin calculation.

## Stateful signal controls

Connect Context, Enabled and an explicit Text Key. Cooldown also requires Duration
Milliseconds. Once offers an optional Reset Boolean. State belongs to a run, node ID
and key; a new run starts fresh. Ordinary book gaps do not clear consumed claims.

False or unavailable Enabled values do not consume opportunities. A passing signal
consumes an opportunity even if a downstream order is skipped or rejected. Place the
complete entry condition before the control when it should govern an order signal.

Cooldown permits another signal at or after expiry using `ctx.clock`. Once consumes
one signal per key until Reset is true. A reset evaluation clears the key and emits
false; a later enabled event may pass. Deduplicate requires an explicit identity key;
it never invents an event identity from a timestamp or price.

Each node remembers at most 10,000 keys. Expired cooldown entries can be reclaimed.
Once and Deduplicate never evict claims to permit repeats. Capacity exhaustion blocks
with `state_capacity_exceeded`. Invalid or ineligible events do not consume state.

## Actions, diagnostics and preview

Buy/Sell expose Status, Filled Size, Execution Price, Skip Reason and Reject Reason.
Execution Price uses the actual `FillEvent.average_price` value.
These are based on the actual broker result. Skipped actions have no fill values.
Graph skip reasons and broker rejection reasons are distinct. Downstream processing
and diagnostics may consume action outputs within the DAG; actions do not recursively
invoke `on_fill`. Broker submission retains its existing validation and fill behavior.

Inspect records the connected value in the evaluation result. Inspect and Log also
emit node-labelled activity; repeated unchanged messages are coalesced to at most one
per second per node. The next emitted message reports its suppressed-repeat count.
Existing order/fill activity remains intact.

**Try this event** evaluates the draft using an editable synthetic framework payload,
explicit virtual time, and optional sample cash/positions. The backend validates those
inputs and uses the same compiler and evaluator as paper runs. Each request starts
fresh transient state. The response shows each node's outputs, status and reason, plus
intended orders. Decimal amounts in sample JSON should be quoted strings.

Default event examples live in the backend's `catalog/graphs/preview_samples.py`.
They construct real framework events with explicit scenario values and inherit
contract defaults; the catalog serializes them for the frontend. Start/stop have
no payload and use `null`. A test checks every catalog trigger's sample through
preview validation and verifies that serialization preserves it, including default
fields. New required fields or payload-bearing hooks require an example update;
docstrings are not parsed and runtime defaults are not added for examples.
The same backend catalog prefills Sample positions with two shares of the example
token at an average entry price of `0.4`. Edit it or use `[]` for no holdings.

Preview uses services that reject broker calls, network reads and sleeps. It does not
create a run or persist state. Actions are marked planned; downstream fill-dependent
values are unavailable. It is a decision preview, not a fill simulator. Use paper runs
for fills and behavior over time. Results are marked outdated after graph changes.

The starting-point selector includes **Threshold entry and exit** and **Multiple
conditions and cooldown**. Both use editable parameters and current token IDs from
events. Copying an example does not start a run. The first is intended for positions
opened by that example; it is not a general short-position exit strategy.

## Validation

Run `uv run pytest`, and set `POLYBOT_TEST_POSTGRES_URL` to a disposable PostgreSQL
instance for database integration tests. From `frontend/`, run `npm run generate:check`,
`npm run check`, `npm test` and `npm run build`. Export changed schemas with
`uv run python -m polybot_control_plane.api.openapi` before generating the client.

No new Polymarket transport, SDK integration, live execution, arbitrary code, loops,
collection processing or cross-stream joining is introduced by this MVP.
