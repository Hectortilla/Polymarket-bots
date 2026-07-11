"""Dependency-light CLI configuration parsing."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from bots.framework.config import (
    BotConfigOverrides,
    BotMode,
    DECIMAL_CONFIG_FIELDS,
    INTEGER_CONFIG_FIELDS,
)


def parse_config_override(key: str, raw: str) -> tuple[str, object]:
    """Parse one CLI override according to the BotConfig contract."""
    if key not in BotConfigOverrides.__annotations__ or key == "name":
        raise ValueError(f"invalid config override: {key}={raw}")
    if key in {"market_slugs", "wallet_addresses"}:
        return key, tuple(part.strip() for part in raw.split(",") if part.strip())
    if key == "mode":
        return key, BotMode(raw)
    if key in DECIMAL_CONFIG_FIELDS:
        return key, Decimal(raw)
    if key == "live_enabled":
        value = raw.lower()
        if value not in {"true", "false"}:
            raise ValueError(f"{key} must be true or false")
        return key, value == "true"
    if key in INTEGER_CONFIG_FIELDS:
        return key, int(raw)
    return key, raw


def load_dotenv(path: str | Path = ".env") -> None:
    """Load simple dotenv assignments without adding a runtime dependency."""
    dotenv = Path(path)
    if not dotenv.is_file():
        return
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if separator and key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = _dotenv_value(value.strip())


def _dotenv_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value.split(" #", 1)[0].rstrip()


def parse_overrides(values: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        if not separator or not key:
            raise ValueError(f"invalid config override: {value}")
        parsed_key, parsed_value = parse_config_override(key, raw)
        overrides[parsed_key] = parsed_value
    return overrides
