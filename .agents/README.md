# Bot Agent Workspace

This folder holds bot-repo-local agent context for the future standalone
project.

- `tasks/README.md` is the local task registry placeholder.
- `CODE_STYLE.md` supports the local `$code-style-review` workflow.
- `skills/code-style-review/` contains the local review skill.
- Canonical working instructions live in `../AGENTS.md`.
- Bot architecture and implementation sequencing live in `../docs/`.

Codex runtime configuration lives separately in `../.codex/` because Codex
discovers subagent registrations from `.codex/config.toml`.
