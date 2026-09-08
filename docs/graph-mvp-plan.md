# MVP graph nodes — implementation checklist

The backend owns node contracts and metadata. The graph exposes Number (exact decimal strings), Boolean and Text. Python framework types remain precise. Existing alpha data is disposable. This work remains paper-only.

## Phase 1 — Frontend representation and shared contracts

- [x] **1.1 — Backend-owned catalog and schemas:** all MVP descriptors, Number, parameters, multi-output/context ports and preview contracts.
- [x] **1.2 — Editor and persistence:** catalog-driven renderers, expandable logic, parameter controls, graph validation, saved revisions and preview UI.
- [x] **1.3 — Intermediate execution boundary:** reject every unsupported operation before any action.

## Phase 2 — Backend execution and necessary fixes

- [x] **2.1 — Evaluation and missing-data handling:** deterministic Decimal operations, explicit unavailable results and fail-closed Boolean composition.
- [x] **2.2 — Framework portfolio capability:** immutable own-portfolio snapshots wired to paper and replay contexts.
- [x] **2.3 — Event controls:** keyed cooldown/once/deduplication, explicit reset, strategy clock and bounded per-run state.
- [x] **2.4 — Action feedback and diagnostics:** broker outputs, node results and coalesced activity messages.
- [x] **2.5 — Try this event preview:** same evaluator, isolated sample data, planned orders without submissions, and example strategies.

Check each unit only after implementation, relevant validation and documentation updates. See [graph behavior and authoring](graph-node-mvp.md) for executable semantics. Full acceptance includes pytest, disposable PostgreSQL integration, generated API checks, Svelte checks, frontend tests and build.


## Phase completion and documentation-drift audit

Both phases are implemented. All catalog operations are now executable, and the
compiler still rejects unsupported operations before executing any branch. The
backend-generated contract remains authoritative for node ports, numeric constraints,
operation choices, expandable input limits and preview results.

Phase 1 audit: graph Integer/Decimal variants were removed; framework/config numeric
types retain their existing contracts. Number editing and persistence use exact strings.
The editor renders every operation, prunes incompatible connections, round-trips
parameters and examples, and accepts Context and diagnostic-only branches. Shared
backend-generated fixtures cover numeric validity, expandable ports, parameters,
context, cycles, and separate trigger ownership.

Phase 2 audit: unavailable comparisons and Boolean inputs cannot enable actions.
Portfolio snapshots are immutable and wired independently of paper and replay broker
wrappers. Event controls use the strategy clock, retain bounded claims across gaps,
and reset with each run. Actions expose real fills; preview exposes planned orders
without broker submissions, network access, run creation, or state persistence.
README, architecture, control-plane specification/architecture and author guide link
to these semantics. Earlier Slice 13 descriptions are historical and explicitly
superseded by Slice 14. No external protocol behavior changed, so no PolymarketDocs
verification was required.

## Verification record

- Backend unit suite: `uv run pytest` — 1,008 passed, 16 service-dependent tests
  skipped with disposable service URLs unset.
- PostgreSQL/Redis: tested against fresh temporary local instances. The new exact-Number,
  copied-graph and immutable-parameter revision test passes. The full service-backed
  suite reports 1,015 passed and eight failures, all eight also reproduced on the
  unchanged repository HEAD:
  persisted-versus-runtime lifecycle/order event expectations, two corrupt-graph error
  message expectations, and two SSE log-capture assertions. These existing failures
  remain outside the graph expansion; the full integration suite is not green.
- Frontend: 150 tests passed; Svelte/TypeScript reports zero errors and warnings;
  the production build and generated artifact check pass. Tests cover operation creation
  and reopening, dynamic edge removal, shared validation fixtures, preview UI tests,
  and production build are covered. `generate:check` uses an isolated temporary Git
  index containing the new generated artifacts, so it checks regeneration without
  staging workspace changes.

Focused backend tests: `uv run pytest tests/control_plane/test_graph_mvp.py`.
Persistence test (with `POLYBOT_TEST_POSTGRES_URL` set to a disposable database):
`uv run pytest tests/control_plane/test_postgres.py::test_graph_parameters_preserve_exact_values_and_run_revisions`.
Frontend checks run from `frontend/`: `npm run generate:check`, `npm run check`,
`npm test`, and `npm run build`.
