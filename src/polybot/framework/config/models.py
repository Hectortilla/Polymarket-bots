"""Typed bot configuration model and local validation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import TypedDict, Unpack

from polybot.framework.streams import StreamRelation, StreamRule
from .constants import (
    DEFAULT_DATA_TRADES_BUDGET_PER_10S,
    DEFAULT_BOT_MODE as DEFAULT_BOT_MODE_NAME,
    DEFAULT_EVENT_MAX_AGE_MS,
    DEFAULT_MAX_ORDER_SIZE,
    DEFAULT_MAX_SLIPPAGE_PCT,
    DEFAULT_PAPER_LATENCY_JITTER_MS,
    DEFAULT_PAPER_LATENCY_MS,
    DEFAULT_PAPER_PORTFOLIO_USDC,
)
from .environment import config_values_from_env

DECIMAL_CONFIG_FIELDS = frozenset(
    {"max_order_size", "max_slippage_pct", "paper_portfolio_usdc"}
)
INTEGER_CONFIG_FIELDS = frozenset(
    {
        "paper_latency_ms",
        "paper_latency_jitter_ms",
        "event_max_age_ms",
        "data_trades_budget_per_10s",
    }
)


class BotMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


DEFAULT_BOT_MODE = BotMode(DEFAULT_BOT_MODE_NAME)


class BotConfigOverrides(TypedDict, total=False):
    name: str
    mode: BotMode
    stream_rules: tuple[StreamRule, ...]
    market_slugs: tuple[str, ...]
    wallet_addresses: tuple[str, ...]
    data_trades_budget_per_10s: int
    max_order_size: Decimal
    max_slippage_pct: Decimal
    paper_latency_ms: int
    paper_latency_jitter_ms: int
    event_max_age_ms: int
    paper_portfolio_usdc: Decimal
    live_enabled: bool
    private_key: str | None
    api_key: str | None
    api_secret: str | None
    api_passphrase: str | None
    funder_address: str | None


@dataclass(frozen=True, slots=True)
class BotConfig:
    name: str
    mode: BotMode = DEFAULT_BOT_MODE
    stream_rules: tuple[StreamRule, ...] = ()
    market_slugs: tuple[str, ...] = ()
    wallet_addresses: tuple[str, ...] = ()
    data_trades_budget_per_10s: int = DEFAULT_DATA_TRADES_BUDGET_PER_10S
    max_order_size: Decimal = DEFAULT_MAX_ORDER_SIZE
    max_slippage_pct: Decimal = DEFAULT_MAX_SLIPPAGE_PCT
    paper_latency_ms: int = DEFAULT_PAPER_LATENCY_MS
    paper_latency_jitter_ms: int = DEFAULT_PAPER_LATENCY_JITTER_MS
    event_max_age_ms: int = DEFAULT_EVENT_MAX_AGE_MS
    paper_portfolio_usdc: Decimal = DEFAULT_PAPER_PORTFOLIO_USDC
    live_enabled: bool = False
    private_key: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    api_passphrase: str | None = None
    funder_address: str | None = None

    def __post_init__(self) -> None:
        if not self.stream_rules and (self.market_slugs or self.wallet_addresses):
            relation = (
                StreamRelation.FILTERED
                if self.market_slugs and self.wallet_addresses
                else StreamRelation.INDEPENDENT
            )
            object.__setattr__(
                self,
                "stream_rules",
                (StreamRule(relation, self.market_slugs, self.wallet_addresses),),
            )
        for field_name in DECIMAL_CONFIG_FIELDS:
            if not getattr(self, field_name).is_finite():
                raise ValueError(f"{field_name} must be finite")
        if self.max_order_size <= 0:
            raise ValueError("max_order_size must be positive")
        if self.max_slippage_pct < 0:
            raise ValueError("max_slippage_pct must be nonnegative")
        if self.paper_latency_ms < 0:
            raise ValueError("paper_latency_ms must be nonnegative")
        if self.paper_latency_jitter_ms < 0:
            raise ValueError("paper_latency_jitter_ms must be nonnegative")
        if self.event_max_age_ms < 0:
            raise ValueError("event_max_age_ms must be nonnegative")
        if self.paper_portfolio_usdc <= 0:
            raise ValueError("paper_portfolio_usdc must be positive")
        if (
            not 1
            <= self.data_trades_budget_per_10s
            <= DEFAULT_DATA_TRADES_BUDGET_PER_10S
        ):
            raise ValueError(
                "data_trades_budget_per_10s must be between 1 and "
                f"{DEFAULT_DATA_TRADES_BUDGET_PER_10S}"
            )

    def with_overrides(self, **overrides: Unpack[BotConfigOverrides]) -> BotConfig:
        return replace(self, **overrides)

    @classmethod
    def from_env(cls, name: str) -> BotConfig:
        values = config_values_from_env()
        values["mode"] = BotMode(values["mode"])
        return cls(name=name, **values)
