"""Dependency-light CLI configuration parsing."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv as _load_dotenv

from polybot.framework.config.models import (
    BotConfigOverrides,
    BotMode,
    DECIMAL_CONFIG_FIELDS,
    INTEGER_CONFIG_FIELDS,
)
from polybot.framework.config.environment import parse_bool


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
        return key, parse_bool(raw, key=key)
    if key in INTEGER_CONFIG_FIELDS:
        return key, int(raw)
    return key, raw


def load_dotenv(path: str | Path = ".env") -> None:
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
