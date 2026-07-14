"""Environment loading for :mod:`polybot.framework.config`."""

import os

from decimal import Decimal
from typing import Any

from .constants import (
    BOT_API_KEY_ENV,
    BOT_API_PASSPHRASE_ENV,
    BOT_API_SECRET_ENV,
    BOT_DATA_TRADES_BUDGET_PER_10S_ENV,
    BOT_EVENT_MAX_AGE_MS_ENV,
    BOT_FUNDER_ADDRESS_ENV,
    BOT_LIVE_ENABLED_ENV,
    BOT_MAX_ORDER_SIZE_ENV,
    BOT_MAX_SLIPPAGE_PCT_ENV,
    BOT_MODE_ENV,
    BOT_PAPER_LATENCY_JITTER_MS_ENV,
    BOT_PAPER_LATENCY_MS_ENV,
    BOT_PAPER_PORTFOLIO_USDC_ENV,
    BOT_PRIVATE_KEY_ENV,
    DEFAULT_DATA_TRADES_BUDGET_PER_10S,
    DEFAULT_EVENT_MAX_AGE_MS,
    DEFAULT_MAX_ORDER_SIZE,
    DEFAULT_MAX_SLIPPAGE_PCT,
    DEFAULT_PAPER_LATENCY_JITTER_MS,
    DEFAULT_PAPER_LATENCY_MS,
    DEFAULT_PAPER_PORTFOLIO_USDC,
    DEFAULT_BOT_MODE,
)
from .stream_rules import env_stream_rules


def optional_env(key: str) -> str | None:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return None
    return value


def parse_bool(value: str, *, key: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{key} must be true or false")
    return normalized == "true"


def env_bool(key: str) -> bool:
    return parse_bool(os.getenv(key, "false"), key=key)


def config_values_from_env() -> dict[str, Any]:
    """Read and parse environment values before model validation."""

    return {
        "mode": os.getenv(BOT_MODE_ENV, DEFAULT_BOT_MODE),
        "stream_rules": env_stream_rules(),
        "data_trades_budget_per_10s": int(
            os.getenv(
                BOT_DATA_TRADES_BUDGET_PER_10S_ENV,
                str(DEFAULT_DATA_TRADES_BUDGET_PER_10S),
            )
        ),
        "max_order_size": Decimal(
            os.getenv(BOT_MAX_ORDER_SIZE_ENV, str(DEFAULT_MAX_ORDER_SIZE))
        ),
        "max_slippage_pct": Decimal(
            os.getenv(BOT_MAX_SLIPPAGE_PCT_ENV, str(DEFAULT_MAX_SLIPPAGE_PCT))
        ),
        "paper_latency_ms": int(
            os.getenv(BOT_PAPER_LATENCY_MS_ENV, str(DEFAULT_PAPER_LATENCY_MS))
        ),
        "paper_latency_jitter_ms": int(
            os.getenv(
                BOT_PAPER_LATENCY_JITTER_MS_ENV,
                str(DEFAULT_PAPER_LATENCY_JITTER_MS),
            )
        ),
        "event_max_age_ms": int(
            os.getenv(BOT_EVENT_MAX_AGE_MS_ENV, str(DEFAULT_EVENT_MAX_AGE_MS))
        ),
        "paper_portfolio_usdc": Decimal(
            os.getenv(
                BOT_PAPER_PORTFOLIO_USDC_ENV,
                str(DEFAULT_PAPER_PORTFOLIO_USDC),
            )
        ),
        "live_enabled": env_bool(BOT_LIVE_ENABLED_ENV),
        "private_key": optional_env(BOT_PRIVATE_KEY_ENV),
        "api_key": optional_env(BOT_API_KEY_ENV),
        "api_secret": optional_env(BOT_API_SECRET_ENV),
        "api_passphrase": optional_env(BOT_API_PASSPHRASE_ENV),
        "funder_address": optional_env(BOT_FUNDER_ADDRESS_ENV),
    }
