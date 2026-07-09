# Polymarket Bots Agent Instructions

This directory is prepared to become a standalone repository. Keep it isolated:
do not import from the Polyfollow app, database, workers, frontend, or repo-level
configuration.

Before implementing a bot-framework task, read:

1. `README.md`
2. `docs/architecture.md`
3. `docs/bot-author-guide.md`
4. `docs/api-notes.md`
5. The relevant slice in `docs/implementation-plan.md`

Other local agent assets:

- `.agents/CODE_STYLE.md` defines cleanliness and maintainability rules.
- `.agents/skills/code-style-review/` is the local source for the optional
  `$code-style-review` skill.
- `.codex/config.toml` and `.codex/agents/reviewers/` register the reviewer
  subagents used by `$code-style-review`.

If a task names a numbered implementation-plan slice, treat only that slice as
the implementation scope unless the docs explicitly say another slice is a
dependency. Fix doc inaccuracies you discover in the same change, but ask before
making product or architecture decisions that are not already implied by the
docs.

## PolymarketDocs MCP

For external market data, CLOB trading, WebSocket, authentication, smart
contract, protocol-parameter, fee, or endpoint work, verify the current behavior
with the `PolymarketDocs` MCP before writing code or documentation.

Use `docs/api-notes.md` as the local summary, not the source of truth, whenever
it conflicts with the official Polymarket documentation. If the MCP is
unavailable, stop and state that blocker before implementing protocol-sensitive
code.

## Official Polymarket Libraries

For every Polymarket integration, use an official Polymarket Python SDK or
client wherever it provides the required capability. Prefer the unified
`polymarket-client` async SDK for discovery, market data, trading, account data,
and realtime streams. Use a specialized official client, such as
`py-clob-client-v2` or `py-builder-relayer-client`, when the unified SDK does
not cover the requirement or the specialized client is the documented path.

Do not hand-roll HTTP/WebSocket transports, authentication, signatures, order
serialization, or protocol models when an official library already implements
them. A direct integration is allowed only when official libraries lack the
required capability or cannot meet a documented correctness or latency
requirement. Record that exception and its evidence in `docs/api-notes.md` and
the relevant implementation-plan slice before implementing it.

Keep official-library objects inside `bots.polymarket` adapters. Validate and
normalize them into this package's internal contracts at the adapter boundary;
do not expose SDK models to bot or execution-domain code. Because the unified
SDK is currently beta, pin the selected version and add adapter contract tests
when a network slice introduces it. Beta status alone is not a reason to
reimplement supported protocol behavior.

## Working Rules

- Keep the package importable as `bots` after this directory is copied away.
- Prefer small modules named by responsibility.
- Write straightforward code for the current slice. Do not introduce speculative
  abstractions, wrappers, dependencies, or generalized extension points.
- Preserve paper/live contract parity: paper and live brokers use the same
  `OrderRequest` and `FillEvent` shapes.
- Preserve live trading fail-closed behavior. Live execution must require
  `BOT_MODE=live`, `BOT_LIVE_ENABLED=true`, wallet credentials, CLOB
  credentials, and a funder address.
- Normalize external Polymarket payloads at adapter boundaries before core bot
  logic sees them.
- Prefer official Polymarket SDK/client methods before adding direct network or
  protocol implementations.
- Missing, stale, ambiguous, or malformed market data must skip or reject with a
  stable reason instead of guessing.
- Package `__init__.py` files are not barrel exports.
- Add tests proportional to the risk of each change.
- Do not run `$code-style-review` automatically. Use it only when explicitly
  requested for code style, DRY, maintainability, refactoring, architecture, or
  a second-pass review.

## Checkpoints

Ask before implementing when you encounter:

- Ambiguous slice requirements.
- Conflicts between local docs and official Polymarket docs.
- Security, performance, cost, or live-trading trade-offs not settled in the
  docs.

## Expected Finish

Before handing off, report:

- The implemented slice and approach.
- Documentation or plan changes made, if any.
- How to run the relevant tests.
- Any intentional exceptions, unresolved decisions, or blocked MCP/doc checks.
- The final documentation-drift audit for implementation work.

## Review Checklist

Before calling a slice done, verify:

- The requested slice requirements are satisfied.
- Any intentional divergence from local docs is reflected in the affected docs.
- Out-of-scope features were not added.
- Shared contract literals and business rules have one source of truth.
- Validation and normalization happen at ingress or adapter boundaries.
- Trading decisions remain fail-safe.
- Live execution cannot run without config and explicit opt-in.
- Tests cover important behavior and edge cases.

## Extraction Notes

After copying this directory into its own location, run:

```sh
uv sync --extra dev
uv run pytest
```

The current scaffold has no runtime dependency on the parent Polyfollow
repository. If a future change introduces one, either copy that dependency into
this project explicitly or update the docs before extraction.
