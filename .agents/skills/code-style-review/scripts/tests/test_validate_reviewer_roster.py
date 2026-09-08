from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[1] / "validate_reviewer_roster.py"
REVIEWER_NAME = "sample_reviewer"
REVIEWER_DESCRIPTION = (
    "Use only when explicitly invoked by the code-style-review skill. "
    "Reports sample findings."
)
REVIEWER_INSTRUCTIONS = "Review the sample. Do not edit files."


def create_repo(tmp_path: Path, claude_agent_contents: str | None) -> Path:
    repo_root = tmp_path / "repo"
    codex_skill_path = repo_root / ".agents/skills/code-style-review/SKILL.md"
    claude_skill_path = repo_root / ".claude/skills/code-style-review/SKILL.md"
    reviewer_path = repo_root / ".codex/agents/reviewers/sample-reviewer.toml"
    claude_agent_path = repo_root / ".claude/agents/reviewers/sample-reviewer.md"

    shared_skill_text = """\
# Code Style Review

## Reconcile Reports

Reconcile the reports.

## Act On Findings

Act on valid findings.

## Guardrails

Keep the review read-only.
"""
    codex_skill_path.parent.mkdir(parents=True)
    codex_skill_path.write_text(shared_skill_text, encoding="utf-8")
    claude_skill_path.parent.mkdir(parents=True)
    claude_skill_path.write_text(shared_skill_text, encoding="utf-8")

    config_path = repo_root / ".codex/config.toml"
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(
        f"""\
[agents.{REVIEWER_NAME}]
description = "{REVIEWER_DESCRIPTION}"
config_file = "./agents/reviewers/sample-reviewer.toml"
""",
        encoding="utf-8",
    )
    reviewer_path.parent.mkdir(parents=True)
    reviewer_path.write_text(
        f"""\
name = "{REVIEWER_NAME}"
description = "{REVIEWER_DESCRIPTION}"
sandbox_mode = "read-only"
developer_instructions = "{REVIEWER_INSTRUCTIONS}"
""",
        encoding="utf-8",
    )

    if claude_agent_contents is not None:
        claude_agent_path.parent.mkdir(parents=True)
        claude_agent_path.write_text(claude_agent_contents, encoding="utf-8")

    return repo_root


def expected_claude_agent() -> str:
    return f"""\
---
name: sample-reviewer
description: {REVIEWER_DESCRIPTION}
tools: Read, Grep, Glob, LSP
model: haiku
---

{REVIEWER_INSTRUCTIONS}
"""


def run_validator(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_missing_claude_agent_fails_validation(tmp_path: Path) -> None:
    repo_root = create_repo(tmp_path, claude_agent_contents=None)

    result = run_validator(repo_root)

    assert result.returncode == 1
    assert "missing Claude Code agent" in result.stderr
    assert "run with --write-claude-agents" in result.stderr


def test_stale_claude_agent_fails_validation(tmp_path: Path) -> None:
    repo_root = create_repo(tmp_path, claude_agent_contents="stale contents\n")

    result = run_validator(repo_root)

    assert result.returncode == 1
    assert ".claude/agents/reviewers/sample-reviewer.md is stale" in result.stderr
    assert "run with --write-claude-agents" in result.stderr


def test_orphaned_claude_agent_is_reported_and_removed_in_write_mode(
    tmp_path: Path,
) -> None:
    repo_root = create_repo(tmp_path, claude_agent_contents=expected_claude_agent())
    orphan_path = repo_root / ".claude/agents/reviewers/orphan-reviewer.md"
    orphan_path.write_text("orphaned\n", encoding="utf-8")

    check_result = run_validator(repo_root)

    assert check_result.returncode == 1
    assert (
        "Unregistered Claude Code agent file: "
        ".claude/agents/reviewers/orphan-reviewer.md"
    ) in check_result.stderr

    write_result = run_validator(repo_root, "--write-claude-agents")

    assert write_result.returncode == 0
    assert "removed 1 unregistered agents" in write_result.stderr
    assert not orphan_path.exists()


def test_generation_produces_a_valid_roster(tmp_path: Path) -> None:
    repo_root = create_repo(tmp_path, claude_agent_contents=None)

    write_result = run_validator(repo_root, "--write-claude-agents")
    check_result = run_validator(repo_root)

    assert write_result.returncode == 0, write_result.stderr
    assert check_result.returncode == 0, check_result.stderr
    agent_path = repo_root / ".claude/agents/reviewers/sample-reviewer.md"
    assert agent_path.read_text(encoding="utf-8") == expected_claude_agent()


def test_writable_source_blocks_generation_without_changing_mirror(
    tmp_path: Path,
) -> None:
    repo_root = create_repo(tmp_path, claude_agent_contents=expected_claude_agent())
    reviewer_path = repo_root / ".codex/agents/reviewers/sample-reviewer.toml"
    reviewer_path.write_text(
        reviewer_path.read_text(encoding="utf-8").replace(
            'sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"'
        ),
        encoding="utf-8",
    )
    agent_path = repo_root / ".claude/agents/reviewers/sample-reviewer.md"
    original_mirror = agent_path.read_bytes()

    result = run_validator(repo_root, "--write-claude-agents")

    assert result.returncode == 1
    assert "sandbox_mode must be read-only" in result.stderr
    assert agent_path.read_bytes() == original_mirror


def test_shared_skill_drift_blocks_preflight(tmp_path: Path) -> None:
    repo_root = create_repo(tmp_path, claude_agent_contents=expected_claude_agent())
    skill_path = repo_root / ".claude/skills/code-style-review/SKILL.md"
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8").replace(
            "Keep the review read-only.", "Reviewers may edit files."
        ),
        encoding="utf-8",
    )

    result = run_validator(repo_root)

    assert result.returncode == 1
    assert "section 'Guardrails' has drifted" in result.stderr
