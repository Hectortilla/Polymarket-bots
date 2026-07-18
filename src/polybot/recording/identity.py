"""Sanitized, stable recorder target identity."""

from __future__ import annotations

import json

from polybot.framework.config.models import BotConfig


def bot_target_identity(spec: str, config: BotConfig) -> str:
    return _canonical_identity(
        {
            "kind": "bot",
            "spec": spec,
            "config": {
                "data_trades_budget_per_10s": (
                    config.data_trades_budget_per_10s
                ),
                "event_max_age_ms": config.event_max_age_ms,
                "live_enabled": config.live_enabled,
                "market_slugs": list(config.market_slugs),
                "max_order_size": str(config.max_order_size),
                "max_slippage_pct": str(config.max_slippage_pct),
                "mode": config.mode.value,
                "name": config.name,
                "paper_latency_jitter_ms": config.paper_latency_jitter_ms,
                "paper_latency_ms": config.paper_latency_ms,
                "paper_portfolio_usdc": str(config.paper_portfolio_usdc),
                "stream_rules": [
                    {
                        "relation": rule.relation.value,
                        "market_slugs": list(rule.market_slugs),
                        "wallet_addresses": list(rule.wallet_addresses),
                    }
                    for rule in config.stream_rules
                ],
                "wallet_addresses": list(config.wallet_addresses),
            },
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
