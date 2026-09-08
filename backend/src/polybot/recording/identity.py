"""Sanitized, stable recorder target identity."""

from __future__ import annotations

import json
from enum import StrEnum

from polybot.framework.config.models import BotConfig


TARGET_IDENTITY_KIND_FIELD = "kind"
TARGET_IDENTITY_BOT_SPEC_FIELD = "spec"
TARGET_IDENTITY_CONFIGURATION_FIELD = "config"
TARGET_IDENTITY_MARKET_SLUGS_FIELD = "market_slugs"


class TargetIdentityKind(StrEnum):
    BOT = "bot"
    STATIC = "static"


def bot_target_identity(spec: str, config: BotConfig) -> str:
    return _canonical_identity(
        {
            TARGET_IDENTITY_KIND_FIELD: TargetIdentityKind.BOT.value,
            TARGET_IDENTITY_BOT_SPEC_FIELD: spec,
            TARGET_IDENTITY_CONFIGURATION_FIELD: config.identity_values(),
        }
    )


def static_target_identity(market_slugs: tuple[str, ...]) -> str:
    return _canonical_identity(
        {
            TARGET_IDENTITY_KIND_FIELD: TargetIdentityKind.STATIC.value,
            TARGET_IDENTITY_MARKET_SLUGS_FIELD: sorted(set(market_slugs)),
        }
    )


def _canonical_identity(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def describe_target_identity(target_identity: str) -> str:
    """Return a compact label for a recognized canonical target identity."""
    try:
        payload = json.loads(target_identity)
    except json.JSONDecodeError:
        return target_identity
    if not isinstance(payload, dict):
        return target_identity
    try:
        kind = TargetIdentityKind(payload.get(TARGET_IDENTITY_KIND_FIELD))
    except (TypeError, ValueError):
        return target_identity
    if kind is TargetIdentityKind.BOT:
        spec = payload.get(TARGET_IDENTITY_BOT_SPEC_FIELD)
        return f"bot {spec}" if isinstance(spec, str) else target_identity
    market_slugs = payload.get(TARGET_IDENTITY_MARKET_SLUGS_FIELD)
    if isinstance(market_slugs, list) and all(
        isinstance(slug, str) for slug in market_slugs
    ):
        return "static " + ", ".join(market_slugs)
    return target_identity
