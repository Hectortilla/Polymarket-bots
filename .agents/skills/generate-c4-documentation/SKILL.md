---
name: generate-c4-documentation
description: Generate or update evidence-backed C4 model architecture documentation for an entire repository, monorepo, service, subsystem, feature slice, or selected code paths. Use when Codex needs to reverse-engineer an existing codebase into system landscape, system context, container, component, dynamic, deployment, or code-level views; explain architectural boundaries and relationships; create architecture onboarding material; audit existing C4 docs for drift; or document a planned architecture while distinguishing verified facts from assumptions.
---

# Generate C4 Documentation

Create architecture documentation that maps code and runtime evidence onto the
C4 abstractions. Prefer a small, useful set of diagrams over exhaustive output.
Keep every architectural claim traceable to source files, configuration,
infrastructure, tests, or user-supplied facts.

Read:

- `references/c4-model-rules.md` before choosing diagram levels or element types.
- `references/output-contract.md` before creating or updating documentation.

## Establish the task

Determine:

1. The scope: whole repository, monorepo, system, subsystem, container, feature,
   or explicit paths.
2. The intent: document the current state, a proposed state, or both.
3. The audience and useful zoom levels.
4. The destination and diagram notation already used by the repository.

Infer these from the request and repository when possible. Ask only when a
choice would materially change scope or architecture. Default to current-state
documentation under the repository's existing architecture-docs location, or
`docs/architecture/c4/` when no convention exists.

For a whole system, start with system context and container views. Add component
views only for containers where they aid understanding. Add dynamic views only
for important, non-obvious runtime flows. Add deployment views only when an
environment is known. Avoid code diagrams unless explicitly requested or
necessary for a stable, complex component.

## Investigate before modelling

Read repository instructions and existing architecture documents first. Respect
their required tools, sources of truth, and scope rules.

Build an evidence inventory in passes:

1. **Shape**: inspect top-level directories, manifests, workspace files,
   dependency locks, build definitions, and ownership boundaries.
2. **Runtime**: locate entry points, processes, scheduled jobs, workers,
   serverless functions, applications, and data stores.
3. **Interfaces**: trace HTTP/RPC endpoints, events, queues, commands, database
   access, files, SDK clients, and public APIs.
4. **Operations**: inspect containers, orchestration, infrastructure as code,
   CI/CD, environment configuration, observability, and deployment docs.
5. **Behavior**: use tests and representative call paths to verify important
   relationships and dynamic flows.

Use fast repository search and language-aware tools when available. Exclude
generated files, vendored code, dependency caches, build output, and large
fixtures unless they are architectural evidence.

For large codebases, inventory broadly, then inspect representative boundary
files deeply. Do not claim exhaustive coverage unless every relevant boundary
was actually inspected.

## Build an architecture evidence ledger

Record candidate elements and relationships before drawing:

| ID | Candidate | C4 type | Responsibility | Technology | Evidence | Confidence |
|---|---|---|---|---|---|---|

Use stable IDs across all views. Classify confidence as:

- **Verified**: directly established by code, config, infrastructure, or tests.
- **Corroborated**: supported by multiple indirect sources.
- **Assumed**: plausible but not established; require an explicit assumption.
- **Unknown**: evidence is insufficient; do not invent the missing fact.

Treat imports as code dependencies, not automatically runtime communication.
Treat directories, packages, libraries, and repositories as organizational
units until evidence supports a C4 type. A C4 container must be a separately
runnable/deployable application or a data store; it is not a Docker container
and not merely a source folder.

For planned architecture, label proposed elements and relationships. Never mix
current and proposed state without a visually and textually explicit
distinction.

## Model from the outside in

Create one coherent model, then derive views from it:

1. Define the system or container in scope and its responsibility.
2. Identify people and external software systems.
3. Identify runtime containers and data stores inside the system boundary.
4. Decompose only selected containers into cohesive components.
5. Add relationships with a single direction and an intent-rich label.
6. Add technology/protocol details where appropriate.
7. Reuse the same names, IDs, descriptions, and relationship directions across
   every view.

Do not mix abstraction levels in one static view. Show only elements needed to
tell that view's story. Split unreadable diagrams instead of shrinking or
crowding them.

## Generate the documentation

Follow `references/output-contract.md`. Adapt to an existing repository
convention rather than creating a competing documentation system.

Prefer notation already used in the repository. Otherwise use, in order:

1. Structurizr DSL when a model-as-code workflow already exists or the user
   requests a single reusable architecture model.
2. C4-PlantUML when PlantUML rendering is already supported.
3. Mermaid in Markdown for portable, reviewable documentation.

Use ordinary Mermaid flowcharts with explicit C4 types when the target renderer
does not reliably support Mermaid's C4 syntax. C4 is notation-independent;
semantic correctness and readability matter more than a particular renderer.

Every diagram document must include:

- A title naming the diagram type and scope.
- A short purpose and audience statement.
- An explicit scope and boundary.
- A diagram whose elements have types and responsibilities.
- A key or legend.
- Directional, specifically labelled relationships.
- Technologies for containers, components, and inter-process relationships when
  verified and applicable.
- Evidence links or repository-relative source paths.
- Assumptions, unknowns, and coverage limits.

Make local file references clickable in the surrounding Markdown where the
renderer permits it. Keep evidence paths repository-relative inside committed
documentation.

## Validate and reconcile

Validate at three levels:

1. **Source fidelity**: revisit the entry point or boundary source behind every
   important element and relationship.
2. **Cross-view consistency**: ensure names, responsibilities, technologies,
   directions, and scope agree across all documents.
3. **Diagram quality**: apply the checklist in
   `references/c4-model-rules.md`.

Run the bundled structural audit:

```bash
python3 <skill-dir>/scripts/audit_c4_docs.py <docs-dir>
```

For a whole-system documentation set, request the recommended views:

```bash
python3 <skill-dir>/scripts/audit_c4_docs.py <docs-dir> \
  --expect system-context,container
```

Also use the repository's existing formatter, diagram renderer, link checker,
or docs build when available. Render diagrams when tooling exists and inspect
them for clipped labels, crossed edges, unreadable density, and inconsistent
boundaries. If rendering is unavailable, state that limitation.

Fix documentation defects found during validation. Do not alter production code
merely to make the documentation cleaner unless the user explicitly asks.

## Update existing C4 documentation

Treat the existing model as a hypothesis:

1. Inventory its elements, relationships, IDs, and claimed technologies.
2. Compare those claims with current runtime and deployment evidence.
3. Preserve stable names and IDs for unchanged concepts.
4. Remove or mark stale elements; do not silently retain uncertain claims.
5. Report material drift and unresolved contradictions.

Avoid broad rewrites when a focused update preserves history and reviewability.

## Finish

Report:

- Scope and C4 views created or updated.
- Important boundaries and architectural findings.
- Evidence coverage and areas intentionally not inspected.
- Assumptions, unknowns, and current-versus-proposed distinctions.
- Validation and rendering performed.
- Exact documentation entry point.

Do not claim the architecture is complete when external systems, runtime
configuration, or deployment evidence remains unavailable.
