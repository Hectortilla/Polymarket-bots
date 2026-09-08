---
name: code-style-review
description: Run a parallel, read-only maintainability and refactoring review using one project subagent per repository style rule, then reconcile their reports and apply accepted fixes holistically.
---

# Code Style Review

Use the reviewer subagents in `.claude/agents/reviewers/`, generated from the
same `.codex/agents/reviewers/*.toml` sources the Codex version of this skill
uses. Reviewers inspect and report only. The parent agent owns evidence
checking, reconciliation, edits, verification, and documentation consistency
so the final change remains coherent.

These project-scoped reviewer subagents are available to Claude Code throughout
this repository, but they are reserved for explicit `code-style-review` runs.
Do not select them for ordinary delegation outside this skill.

This is a standalone Polymarket bot repository. Root and path-specific
`CLAUDE.md`/`AGENTS.md` files and `.agents/CODE_STYLE.md` define its rules.

## Establish Scope

1. Read `AGENTS.md`, `.agents/CODE_STYLE.md`, root `CLAUDE.md` if present,
   and every `CLAUDE.md`/`AGENTS.md` governing the requested or changed paths. Read
   referenced architecture or integration docs when the change is structural.
2. Identify the requested surface. For an implementation pass, inspect the
   task, `git status`, the complete diff, and relevant surrounding code. For a
   review-only request, inspect only the user-specified files or diff.
3. Use LSP for symbol navigation and call sites when available. Use text
   search for strings, comments, configs, tool names, translations, and other
   non-symbol contracts.
4. Give every reviewer the same concise scope, task intent, diff baseline, and
   applicable rule-file paths. Do not give reviewers expected findings or
   prior conclusions.

## Verify The Reviewer Roster

From the repository root, run:

```bash
uv run python .agents/skills/code-style-review/scripts/validate_reviewer_roster.py
```

The validator compares the Codex reviewer roster against `.claude/agents/reviewers/`
and fails if a Claude Code agent is missing or stale relative to its TOML
source. It also checks that the shared reconciliation, action, and guardrail
sections in the Codex and Claude Code skill instructions have not drifted apart
while allowing their runtime-specific terminology. Stop and report its errors
before launching a review; do not bypass or weaken the preflight, and do not
hand-edit files under `.claude/agents/reviewers/` — they are generated, not
authored.

To add or edit a reviewer, edit its `.codex/agents/reviewers/*.toml` source
(and its registration in `.codex/config.toml` if new), then run:

```bash
uv run python .agents/skills/code-style-review/scripts/validate_reviewer_roster.py --write-claude-agents
```

and commit the regenerated `.md` file together with the `.toml` change in
the same commit.

Get the current roster from the generated agents themselves rather than a
second hand-maintained list:

```bash
ls .claude/agents/reviewers/*.md | xargs -n1 basename -s .md
```

Every name printed is a valid `subagent_type` for the Agent tool.

## Launch Reviewers

Launch the entire roster with the Agent tool, one call per reviewer, batched
into as few messages as possible so independent reviewers run concurrently
(send every Agent call for a batch in a single message with multiple tool
uses). Do not substitute a broad built-in agent type for a missing reviewer.

Use this prompt shape for each reviewer, with `subagent_type` set to the
reviewer's name:

```text
Review <scope> against your single assigned rule. The task intent is <intent>.
Use <baseline> for the changed surface and follow <applicable rule files>.
Inspect enough surrounding code to prove or disprove a finding. Do not edit
files. Return only concrete findings with severity and file:line evidence, or
`No findings`.
```

Track one pending ledger entry per reviewer. Mark entries completed, failed,
or timed out as results arrive. Retry each failed or timed-out reviewer once
with the same role, scope, and prompt. If any entry remains incomplete after
retry, report the missing roles and stop before edits. Otherwise, reconcile
the complete report set.

## Reconcile Reports

1. Verify every report against the code and applicable rule files. Discard
   unsupported findings explicitly.
2. Merge duplicate symptoms into one root-cause finding while retaining all
   relevant file references and affected rules.
3. Resolve conflicts using the narrowest applicable `CLAUDE.md`/`AGENTS.md`,
   then broader `CLAUDE.md`/`AGENTS.md`, `.agents/CODE_STYLE.md`, task intent,
   and referenced docs.
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
- After edits, check LSP diagnostics and run the targeted tests and checks required
  by the applicable `CLAUDE.md`/`AGENTS.md` files. Re-run only reviewers whose rules could
  have been affected by the final patch.
- Before handoff, verify no accepted finding remains, scan for documentation and
  contract drift, and report what changed and how it was verified.

## Guardrails

- Never allow reviewer agents to edit files.
- Never omit `mixed-domain-service-reviewer` for service changes.
- Preserve fail-closed trading, live opt-in gates, stable skip reasons, and
  paper/live contract parity as required by `CLAUDE.md`/`AGENTS.md`.
- Do not split modules by line count; split by durable domain or ownership.
- Do not extract coincidentally similar code or one-off UI copy without a shared
  concept.
- Do not broaden the implementation beyond the task to satisfy a low-value
  preference.
