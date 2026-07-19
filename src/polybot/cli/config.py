"""Dependency-light CLI configuration parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv as _load_dotenv

from polybot.framework.config.models import parse_config_override_value


DEFAULT_DOTENV_PATH = Path(".env")


def parse_config_override(key: str, raw: str) -> tuple[str, object]:
    """Parse one CLI override according to the BotConfig contract."""
    return key, parse_config_override_value(key, raw)


def load_dotenv(path: str | Path = DEFAULT_DOTENV_PATH) -> None:
    """Load a dotenv file without overriding existing process variables."""
    _load_dotenv(dotenv_path=path, override=False)


def parse_overrides(values: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        if not separator or not key:
            raise ValueError(f"invalid config override: {value}")
        parsed_key, parsed_value = parse_config_override(key, raw)
        overrides[parsed_key] = parsed_value
    return overrides
