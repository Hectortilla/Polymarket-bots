#!/usr/bin/env python3
"""Preflight the code-style review system before its reviewers are launched.

Run this whenever ``$code-style-review`` starts to catch missing registrations,
invalid or writable agents, metadata drift, reviewer descriptions that could
invite use outside the skill, and drift in behavior shared by the Codex and
Claude Code skill instructions. It does not review application code.

The Codex ``.codex/agents/reviewers/*.toml`` files are the single source of
truth for every reviewer's description and instructions. The Claude Code
subagents under ``.claude/agents/reviewers/*.md`` are generated from them —
never hand-edit a file under ``.claude/agents/reviewers/`` directly.

Workflow for adding or editing a reviewer:
1. Edit (or add) the reviewer's ``.codex/agents/reviewers/*.toml`` file, and
   its registration in ``.codex/config.toml`` for a new reviewer.
2. Run this script with ``--write-claude-agents`` to synchronize
   ``.claude/agents/reviewers/*.md``, including removing generated agents whose
   Codex source no longer exists.
3. Commit the ``.toml`` (and ``config.toml`` change, if any) together with
   the regenerated ``.md`` file in the same commit.

The default (check) run fails if a generated file is missing or stale
instead of regenerating it, so drift is never applied unnoticed. This
default run is also what both the Codex and Claude Code versions of the
``code-style-review`` skill invoke as their preflight, so a Codex-only
change that forgets step 2 fails the Claude Code skill's preflight too,
and vice versa.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any

import tomllib

REVIEWER_CONFIG_PREFIX = "./agents/reviewers/"
EXPLICIT_INVOCATION_PREFIX = (
    "Use only when explicitly invoked by the code-style-review skill. "
)
CLAUDE_REVIEWER_TOOLS = "Read, Grep, Glob, LSP"
# Cheap-tier match for Codex's `model = "gpt-5.6-luna"`. Do not pair this with
# an `effort:` frontmatter field: Haiku does not support the effort mechanism,
# so Codex's accompanying `model_reasoning_effort = "max"` has no equivalent
# on this model tier and would be a silent no-op if added.
CLAUDE_REVIEWER_MODEL = "haiku"
SHARED_SKILL_SECTIONS = ("Reconcile Reports", "Act On Findings", "Guardrails")
SKILL_SECTION_NORMALIZATIONS = (
    ("`CLAUDE.md`/`AGENTS.md`", "`AGENTS.md`"),
    ("LSP diagnostics", "diagnostics"),
    ("`mixed-domain-service-reviewer`", "`mixed_domain_service_reviewer`"),
    (
        "`tool-contract-uniqueness-reviewer`",
        "`tool_contract_uniqueness_reviewer`",
    ),
)
LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
        help="Repository root (defaults to the root containing this skill).",
    )
    parser.add_argument(
        "--write-claude-agents",
        action="store_true",
        help=(
            "Synchronize .claude/agents/reviewers/*.md with the Codex TOML "
            "sources instead of only checking them for drift."
        ),
    )
    return parser.parse_args()


def claude_agent_markdown(name: str, description: str, instructions: str) -> str:
    kebab_name = name.replace("_", "-")
    body = instructions.strip()
    return (
        "---\n"
        f"name: {kebab_name}\n"
        f"description: {description}\n"
        f"tools: {CLAUDE_REVIEWER_TOOLS}\n"
        f"model: {CLAUDE_REVIEWER_MODEL}\n"
        "---\n\n"
        f"{body}\n"
    )


def read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as file_handle:
        return tomllib.load(file_handle)


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def normalized_skill_section(skill_text: str, heading: str) -> str | None:
    heading_match = re.search(
        rf"^## {re.escape(heading)}\s*$", skill_text, flags=re.MULTILINE
    )
    if heading_match is None:
        return None

    section_start = heading_match.end()
    next_heading = re.search(r"^## ", skill_text[section_start:], flags=re.MULTILINE)
    section_end = (
        section_start + next_heading.start()
        if next_heading is not None
        else len(skill_text)
    )
    section = skill_text[section_start:section_end]
    for runtime_specific, shared_term in SKILL_SECTION_NORMALIZATIONS:
        section = section.replace(runtime_specific, shared_term)
    return " ".join(section.split())


def shared_skill_drift_errors(
    codex_skill_text: str, claude_skill_text: str
) -> list[str]:
    errors: list[str] = []
    for heading in SHARED_SKILL_SECTIONS:
        codex_section = normalized_skill_section(codex_skill_text, heading)
        claude_section = normalized_skill_section(claude_skill_text, heading)
        if codex_section is None:
            errors.append(f"Codex skill is missing shared section: {heading}")
        if claude_section is None:
            errors.append(f"Claude Code skill is missing shared section: {heading}")
        if (
            codex_section is not None
            and claude_section is not None
            and codex_section != claude_section
        ):
            errors.append(
                f"Claude Code skill section '{heading}' has drifted from the "
                "Codex skill"
            )
    return errors


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    codex_skill_path = repo_root / ".agents/skills/code-style-review/SKILL.md"
    claude_skill_path = repo_root / ".claude/skills/code-style-review/SKILL.md"
    config_path = repo_root / ".codex/config.toml"
    reviewer_directory = repo_root / ".codex/agents/reviewers"
    claude_agent_directory = repo_root / ".claude/agents/reviewers"
    errors: list[str] = []

    try:
        codex_skill_text = codex_skill_path.read_text(encoding="utf-8")
        claude_skill_text = claude_skill_path.read_text(encoding="utf-8")
    except OSError as error:
        LOGGER.error("Unable to read skill instructions: %s", error)
        return 1
    errors.extend(shared_skill_drift_errors(codex_skill_text, claude_skill_text))

    try:
        config = read_toml(config_path)
    except (OSError, tomllib.TOMLDecodeError) as error:
        LOGGER.error("Unable to parse reviewer configuration: %s", error)
        return 1

    agents = config.get("agents", {})
    registered = {
        name: value
        for name, value in agents.items()
        if isinstance(value, dict)
        and str(value.get("config_file", "")).startswith(REVIEWER_CONFIG_PREFIX)
    }

    registered_files: set[Path] = set()
    reviewers: dict[str, dict[str, Any]] = {}
    for name, registration in registered.items():
        reviewer_path = (config_path.parent / registration["config_file"]).resolve()
        registered_files.add(reviewer_path)
        if reviewer_path.parent != reviewer_directory.resolve():
            errors.append(f"{name}: config file escapes reviewer directory")
            continue
        try:
            reviewer = read_toml(reviewer_path)
        except (OSError, tomllib.TOMLDecodeError) as error:
            errors.append(f"{name}: cannot parse {reviewer_path}: {error}")
            continue
        if reviewer.get("name") != name:
            errors.append(f"{name}: file name field must match the registered role")
        description = reviewer.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{name}: description must be non-empty")
        elif description != registration.get("description"):
            errors.append(f"{name}: file and registration descriptions must match")
        elif not description.startswith(EXPLICIT_INVOCATION_PREFIX):
            errors.append(
                f"{name}: description must reserve the reviewer for explicit "
                "code-style-review invocation"
            )
        if reviewer.get("sandbox_mode") != "read-only":
            errors.append(f"{name}: sandbox_mode must be read-only")
        instructions = reviewer.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            errors.append(f"{name}: developer_instructions must be non-empty")
        elif "Do not edit files" not in instructions:
            errors.append(f"{name}: developer_instructions must forbid edits")
        else:
            reviewers[name] = reviewer

    actual_files = {path.resolve() for path in reviewer_directory.glob("*.toml")}
    for path in sorted(actual_files - registered_files):
        errors.append(f"Unregistered reviewer file: {display_path(path, repo_root)}")
    for path in sorted(registered_files - actual_files):
        errors.append(f"Missing reviewer file: {display_path(path, repo_root)}")

    # Regeneration must not partially update the Claude mirror when its source
    # configuration is invalid. Check mode continues below so it can report
    # mirror drift alongside the source errors.
    if args.write_claude_agents and errors:
        for error in errors:
            LOGGER.error("ERROR: %s", error)
        return 1

    actual_claude_files = {
        path.resolve() for path in claude_agent_directory.glob("*.md")
    }
    expected_claude_files = {
        (claude_agent_directory / f"{name.replace('_', '-')}.md").resolve()
        for name in reviewers
    }
    claude_written = 0
    for name, reviewer in sorted(reviewers.items()):
        kebab_name = name.replace("_", "-")
        claude_path = claude_agent_directory / f"{kebab_name}.md"
        expected = claude_agent_markdown(
            name, reviewer["description"], reviewer["developer_instructions"]
        )
        if args.write_claude_agents:
            claude_path.parent.mkdir(parents=True, exist_ok=True)
            claude_path.write_text(expected, encoding="utf-8")
            claude_written += 1
        elif not claude_path.exists():
            errors.append(
                f"{name}: missing Claude Code agent "
                f"{display_path(claude_path, repo_root)}; run with "
                "--write-claude-agents"
            )
        elif claude_path.read_text(encoding="utf-8") != expected:
            errors.append(
                f"{name}: {display_path(claude_path, repo_root)} is stale; "
                "run with --write-claude-agents"
            )

    orphaned_claude_files = actual_claude_files - expected_claude_files
    claude_removed = 0
    if args.write_claude_agents:
        for path in sorted(orphaned_claude_files):
            path.unlink()
            claude_removed += 1
    else:
        for path in sorted(orphaned_claude_files):
            errors.append(
                "Unregistered Claude Code agent file: "
                f"{display_path(path, repo_root)}"
            )

    if errors:
        for error in errors:
            LOGGER.error("ERROR: %s", error)
        return 1

    if args.write_claude_agents:
        LOGGER.info(
            "Wrote %s Claude Code reviewer agents to %s and removed %s "
            "unregistered agents.",
            claude_written,
            display_path(claude_agent_directory, repo_root),
            claude_removed,
        )
        return 0

    LOGGER.info(
        "Validated %s registered read-only reviewers reserved for explicit "
        "code-style-review runs and %s synced Claude Code agents.",
        len(actual_files),
        len(reviewers),
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
