# Code Style And Maintainability

This repo values clean, modular, explicit code. Agents should leave each task
easy to read, easy to change, and boring to debug.

## DRY And Single Sources Of Truth

- Avoid duplicated logic aggressively. Business rules, formulas, state
  transitions, validation, API contracts, route paths, status values, feature
  gates, and safety checks must have one clear source of truth.
- Treat duplicated knowledge as a bug waiting to happen. If two places must
  change together, extract the shared concept before continuing.
- Prefer shared constants, enums, typed models, helper functions, and focused
  services over repeating the same rule inline.
- Keep abstractions honest. Extract code because it represents the same concept
  or behavior, not only because two snippets happen to look similar.
- Do not hide important behavior behind vague utility functions. Shared code
  should make the domain clearer, not merely shorter.
- For cross-boundary duplication, such as backend and frontend contracts, prefer
  stable shared definitions or generated clients when the project supports them.
  Until then, keep each side's constants explicit and named the same way.

## Validation Boundaries

- Keep external input validation and normalization at ingress boundaries before
  core business logic runs. HTTP request-shape validation belongs in FastAPI
  parameter declarations or Pydantic request models. SDK, WebSocket, config,
  model, and database payload checks belong in their adapter or persistence
  boundary.
- Internal business logic, service orchestration, and readonly client wrappers
  assume their callers already supplied valid request-shaped values. Do not
  re-run wallet address, condition ID, or pagination-limit validation inside
  those layers.
- Do not interleave `None`, range, shape, or status checks with formulas,
  state transitions, or strategy/risk/execution decisions. Validate first, then
  call calculation functions with typed, already-valid values.
- Domain guards that turn bad external market data into stable skip reasons are
  allowed and are not request-shape validation. Keep those fail-safe checks at
  the strategy, risk, or execution boundary before calculation code.
- Low-level primitives may still enforce true preconditions, but keep those
  checks in a named boundary helper or thin public wrapper and delegate formulas
  to private calculation functions.

## Official External Clients

- Prefer an official vendor SDK/client whenever it supports the external
  operation. For Polymarket, follow the selection rule in
  `docs/api-notes.md`: unified async SDK first, then specialized official
  clients, then a documented direct-integration exception.
- Keep vendor models, errors, and transport lifecycle inside the owning adapter.
  Normalize them into package contracts before domain or bot code sees them.
- Do not duplicate authentication, signing, serialization, pagination, or
  realtime subscription behavior supplied by an official client.
- Pin beta SDK versions and contract-test adapter behavior rather than leaking
  unstable vendor contracts across the codebase.

## Constants And Literals

- Treat hardcoded literals as a design smell when they represent shared
  contracts, identifiers, routes, statuses, service names, environment keys,
  ports, timeouts, limits, or domain values.
- Literal extraction is a DRY practice: shared values should be named once and
  imported everywhere else.
- Put shared values in the smallest owning module that makes sense. Prefer
  focused bot-package modules such as `framework/config.py`,
  `framework/events.py`, `execution/orders.py`, or `polymarket/types.py` over a
  broad global constants module.
- Keep constants named for meaning, not for their current value. Prefer
  `SERVICE_NAME` over `POLYFOLLOW_BACKEND_STRING`.
- Avoid duplicating literals in tests. Tests should import contract constants
  when they are asserting repo-owned behavior.
- One-off user-facing copy can stay close to the component when extracting it
  would make the UI harder to read. Extract it once it is reused, translated,
  shared with tests, or part of a stable contract.

## Modularity

- Keep modules focused on one responsibility.
- Put code near the thing that owns it. Do not create global utility modules
  until at least two real call sites need the same behavior or a value is a
  stable contract.
- Before introducing a standalone function, check whether its parameters,
  manipulated values, or call sites reveal an owning class or domain object. If
  one argument is conceptually the receiver, or several inputs are attributes of
  the same existing class, make the behavior a method of that class instead.
- Use class or static methods when behavior is state-free but still belongs
  under a domain type for semantic clarity, discoverability, and reuse. Keep
  standalone functions for genuinely ownerless pure formulas, dependency-light
  helpers, or stable cross-domain contracts.
- Put object-to-object response or DTO factories on the target schema/response
  class when they mostly copy fields from one model, entity, or view. Prefer
  `Response.from_view(...)` or `Response.from_model(...)` over isolated
  `*_response(...)` helpers, unless that would force an invalid dependency
  direction. Do not put API response construction on ORM persistence models.
- When one cohesive area grows into clear internal sections, prefer promoting
  the module into a package with focused submodules. Split by ownership, such as
  contracts, typed models, loading/parsing, or persistence, not by arbitrary
  line count.
- When a service module contains multiple durable domains, such as public
  orchestration, typed contracts, validation/normalization, domain formulas,
  book/IO adapters, or persistence, promote it to a package immediately. Keep
  the public entrypoint in the package root when that is the API, and move
  supporting contracts and helpers into semantic submodules. Do not leave a
  mixed-domain service as a single file only because there is one current call
  site or a task lists one broad file path.
- Do not use package `__init__.py` files as barrel exports that re-import
  classes, functions, constants, or submodules solely for shorter imports.
  Prefer importing from the semantic submodule that owns the symbol.
- Package `__init__.py` files may contain real implementation when a concept
  genuinely belongs at the package root. If a symbol deserves to be imported
  from the package root, implement it there instead of defining it in a
  submodule and re-exporting it. Keep supporting concepts in focused submodules
  when those submodule names add useful meaning.
- Prefer small, explicit functions over clever inline logic.
- Avoid circular dependencies by keeping constants and pure helpers dependency
  light.

## Readability

- Choose descriptive names that explain intent.
- Make public contracts stable and easy to discover.
- Prefer typed values, enums, and structured data over loose strings when a
  value has a finite set of valid states.
- Keep comments rare and useful. Explain why something exists, not what obvious
  code does.

## Change Safety

- Update tests when extracting shared constants so tests verify the same public
  behavior without repeating implementation literals.
- Keep changes task-scoped. Do not refactor unrelated code just because it is
  nearby.
- Before finishing, scan for duplicated contract literals and accidental
  out-of-scope implementation.
- Before finishing, scan changed domain code for validation logic woven into
  formulas or state transitions, and move it to a boundary when found.
