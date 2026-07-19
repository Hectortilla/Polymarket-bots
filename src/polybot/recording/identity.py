"""Sanitized, stable recorder target identity."""

from __future__ import annotations

import json

from polybot.framework.config.models import BotConfig


def bot_target_identity(spec: str, config: BotConfig) -> str:
    return _canonical_identity(
        {
            "kind": "bot",
            "spec": spec,
            "config": config.identity_values(),
        }
    )


def static_target_identity(market_slugs: tuple[str, ...]) -> str:
    return _canonical_identity(
        {
            "kind": "static",
            "market_slugs": sorted(set(market_slugs)),
        }
    )


def _canonical_identity(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
