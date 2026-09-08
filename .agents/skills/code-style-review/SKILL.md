---
name: code-style-review
description: Run a parallel, read-only maintainability and refactoring review using one project subagent per repository style rule, then reconcile their reports and apply accepted fixes holistically.
---

# Code Style Review

Use the reviewer roles registered in `.codex/config.toml`; their configurations
live in `.codex/agents/reviewers/`. Reviewers inspect and report only. The parent
agent owns evidence checking, reconciliation, edits, verification, and
documentation consistency so the final change remains coherent.

These project-scoped reviewer roles are available to Codex in every trusted
session for this repository, but they are reserved for explicit
`code-style-review` runs. Do not select them for ordinary delegation outside
this skill.

This is a standalone Polymarket bot repository. Root and path-specific
`AGENTS.md` files and `.agents/CODE_STYLE.md` define its rules.

## Establish Scope

1. Read `AGENTS.md`, `.agents/CODE_STYLE.md`, and every `AGENTS.md`
   governing the requested or changed paths. Read
   referenced architecture or integration docs when the change is structural.
2. Identify the requested surface. For an implementation pass, inspect the task,
   `git status`, the complete diff, and relevant surrounding code. For a
   review-only request, inspect only the user-specified files or diff.
3. Use code intelligence for symbol navigation and call sites when available.
   Use text search for strings, comments, configs, tool names, translations, and
   other non-symbol contracts.
4. Give every reviewer the same concise scope, task intent, diff baseline, and
   applicable rule-file paths. Do not give reviewers expected findings or prior
   conclusions.

## Verify The Reviewer Roster

From the repository root, run:

```bash
uv run python .agents/skills/code-style-review/scripts/validate_reviewer_roster.py
```

The validator compares the reviewer TOMLs in `.codex/agents/reviewers/` with
the `.codex/config.toml` entries whose `config_file` is under
`./agents/reviewers/`, checks the read-only and explicit-invocation contracts,
and checks that every reviewer's Claude Code mirror under
`.claude/agents/reviewers/`
(used by the Claude Code version of this skill) is present and not stale
relative to its TOML source. It also checks that the shared reconciliation,
action, and guardrail sections in the Codex and Claude Code skill instructions
have not drifted apart while allowing their runtime-specific terminology. If
you added or edited a reviewer without
regenerating that mirror, run the same command with `--write-claude-agents`
and commit the regenerated `.md` file alongside your `.toml` change. Stop and
report its errors before launching a review; do not bypass or weaken the
preflight.

Get the current roster from the reviewer configurations rather than maintaining
a second list in this skill:

```bash
for file in .codex/agents/reviewers/*.toml; do
  basename "${file%.toml}" | tr '-' '_'
done
```

Every name printed is a registered reviewer role after the preflight passes.

## Launch Reviewers

Launch the entire roster with the highest concurrency the runtime supports. If
the thread cap prevents one batch, use the fewest maximum-concurrency waves and
do not omit reviewers. Do not substitute a broad built-in reviewer.

Use this task shape for each reviewer:

```text
Review <scope> against your single assigned rule. The task intent is <intent>.
Use <baseline> for the changed surface and follow <applicable rule files>.
Inspect enough surrounding code to prove or disprove a finding. Do not edit
files. Return only concrete findings with severity and file:line evidence, or
`No findings`.
```

Track one pending ledger entry per reviewer. Mark entries completed, failed, or
timed out as results arrive. Retry each failed or timed-out reviewer once with
the same role, scope, and prompt. If any entry remains incomplete after retry,
close all reviewer threads, report the missing roles, and stop before edits.
Otherwise, close all reviewer threads and reconcile the complete report set.

## Reconcile Reports

1. Verify every report against the code and applicable rule files. Discard
   unsupported findings explicitly.
2. Merge duplicate symptoms into one root-cause finding while retaining all
   relevant file references and affected rules.
3. Resolve conflicts using the narrowest applicable `AGENTS.md`, then broader
   `AGENTS.md`, `.agents/CODE_STYLE.md`, task intent, and referenced docs.
4. Prefer the smallest coherent design that fixes all verified findings. Do not
   apply an isolated suggestion that worsens ownership, dependency direction,
   public contracts, or task scope.
5. Treat verified correctness, maintainability, naming, readability, testing,
   localization, and documentation findings as actionable. Severity determines
   communication and sequencing, not whether a verified finding is silently
   ignored.

## Act On Findings

- For a review-only request, report findings first and do not edit.
- For an implementation or refactoring request, apply every verified finding.
  Reconcile conflicting suggestions into one coherent solution; do not silently
  skip or defer them. Update tests, exported contracts, skill docs,
  implementation plans, and architecture docs when the changed contract
  requires it.
- After edits, check diagnostics and run the targeted tests and checks required
  by the applicable `AGENTS.md` files. Re-run only reviewers whose rules could
  have been affected by the final patch.
- Before handoff, verify no accepted finding remains, scan for documentation and
  contract drift, and report what changed and how it was verified.

## Guardrails

- Never allow reviewer agents to edit files.
- Never omit `mixed_domain_service_reviewer` for service changes.
- Preserve fail-closed trading, live opt-in gates, stable skip reasons, and
  paper/live contract parity as required by `AGENTS.md`.
- Do not split modules by line count; split by durable domain or ownership.
- Do not extract coincidentally similar code or one-off UI copy without a shared
  concept.
- Do not broaden the implementation beyond the task to satisfy a low-value
  preference.
