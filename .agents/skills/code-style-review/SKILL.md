---
name: code-style-review
description: Run a parallel maintainability and refactoring review using one project subagent per repository style rule, then reconcile every verified finding and implement all fixes holistically.
---

# Code Style Review

Use the reviewer roles registered in `.codex/config.toml`; their configurations
live in `.codex/agents/reviewers/`. Reviewer agents inspect and report; the
parent agent owns reconciliation, edits, verification, and documentation
consistency. Reviewer agents must not edit files directly, so the parent can
apply the complete reconciled fix set coherently.
Documentation satisfaction, acceptance criteria, and the final drift audit are
task-completion duties, not style-reviewer roles; the parent must still perform
them under `AGENTS.md`.

## Establish Scope

1. Read `AGENTS.md` and `.agents/CODE_STYLE.md` completely.
2. Identify the requested surface. For an implementation pass, inspect the task,
   its referenced docs, `git status`, and the complete diff. For a review-only
   request, inspect only the user-specified files or diff.
3. Give every reviewer the same concise scope, task intent, and diff baseline.
   Do not give reviewers expected findings or conclusions.

## Launch Reviewers

Before launching, compare the `[agents.<role>]` entries in `.codex/config.toml`
with this roster and verify every `config_file` exists. Stop and report any
missing, duplicate, or unlisted entry.

Launch every reviewer below in one parallel batch. Do not substitute a broad
built-in reviewer. If a runtime thread cap prevents one batch, use the fewest
maximum-concurrency waves possible and do not omit reviewers.

- `duplicated_logic_reviewer`
- `synchronized_knowledge_reviewer`
- `shared_rule_representation_reviewer`
- `semantic_abstraction_reviewer`
- `domain_shared_code_reviewer`
- `cross_boundary_contract_reviewer`
- `ingress_validation_reviewer`
- `import_placement_reviewer`
- `internal_revalidation_reviewer`
- `validation_before_decisions_reviewer`
- `market_data_guard_reviewer`
- `primitive_precondition_reviewer`
- `contract_literal_reviewer`
- `literal_single_source_reviewer`
- `constant_ownership_reviewer`
- `semantic_constant_name_reviewer`
- `test_contract_literal_reviewer`
- `user_copy_extraction_reviewer`
- `module_responsibility_reviewer`
- `owner_local_code_reviewer`
- `cohesive_module_package_reviewer`
- `mixed_domain_service_reviewer`
- `init_barrel_export_reviewer`
- `package_root_ownership_reviewer`
- `small_explicit_function_reviewer`
- `object_method_placement_reviewer`
- `dependency_light_foundation_reviewer`
- `descriptive_name_reviewer`
- `public_contract_discoverability_reviewer`
- `typed_finite_state_reviewer`
- `intent_comment_reviewer`
- `constant_extraction_test_reviewer`
- `task_scope_reviewer`
- `final_contract_scan_reviewer`
- `final_validation_scan_reviewer`
- `pure_domain_function_reviewer`
- `risk_proportional_test_reviewer`
- `important_branch_test_reviewer`
- `fail_safe_trading_reviewer`
- `live_execution_gate_reviewer`
- `async_blocking_io_reviewer`
- `mirror_event_idempotency_reviewer`
- `stable_skip_reason_reviewer`

Use this task shape for each reviewer:

```text
Review <scope> against your single assigned rule. The task intent is <intent>.
Use <baseline> for the changed surface. Inspect enough surrounding code to prove
or disprove a finding. Do not edit files. Return only concrete findings with
severity and file:line evidence, or `No findings`.
```

Create a ledger with one pending entry per reviewer. Mark each entry completed,
failed, or timed out as results arrive. Retry each failed or timed-out reviewer
once with the same role, scope, and prompt. If any ledger entry remains
incomplete after retry, close all reviewer threads, report the missing roles,
and stop before edits. Otherwise, close all reviewer threads and reconcile the
complete report set.

## Reconcile Reports

1. Verify reported evidence in the code and discard unsupported findings.
2. Merge duplicate symptoms into one root-cause finding while retaining all
   relevant file references and affected rules.
3. Resolve conflicting suggestions against `.agents/CODE_STYLE.md`, then
   `AGENTS.md`, task scope, and referenced docs in that order.
4. Prefer the smallest coherent design that fixes all verified findings. Do not
   apply isolated suggestions that would create a worse module boundary,
   dependency direction, or public contract.
5. Treat every verified finding as actionable. Critical bugs, logical
   correctness, structural maintainability, style, naming, readability, and
   comments have equal priority. Resolve ordering only as needed to keep the
   resulting patch coherent and safe; do not omit or defer a finding because
   it is classified as style or readability.

## Act On Findings

- For a review-only request, report findings first and do not edit.
- For an implementation or refactoring request, the parent agent must apply
  every verified finding from the complete reviewer set. Do not silently reject,
  skip, or defer findings. If two findings conflict, reconcile them into one
  coherent solution that addresses both; if a finding is unsupported, verify
  that explicitly during reconciliation rather than treating it as deferred.
  Update tests and affected docs, tasks, and decisions as required by
  `AGENTS.md`.
- After edits, run targeted tests and checks. Re-run only the reviewers whose
  rules could have been affected by the final patch.
- Verify that no reviewer finding remains unapplied before handoff. Run the
  relevant tests and checks, and complete the final documentation-drift audit.
  The handoff should state what was changed and how it was verified; do not
  substitute a findings summary for implementing the fixes.

## Guardrails

- Never allow reviewer agents to edit files.
- Never omit `mixed_domain_service_reviewer` for service changes.
- Do not split modules by line count; split by durable domain or ownership.
- Do not extract coincidentally similar code or one-off UI copy without a shared
  concept.
- Do not broaden the implementation beyond the task to satisfy a low-value style
  preference.
