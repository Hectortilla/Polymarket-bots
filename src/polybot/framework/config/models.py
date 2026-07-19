"""Typed bot configuration model and local validation."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any, TypedDict, Unpack

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

CONFIG_OVERRIDE_KIND = "override_kind"
CONFIG_SENSITIVE = "sensitive"
CONFIG_IDENTITY = "identity"


class ConfigOverrideKind(StrEnum):
    TEXT = "text"
    MODE = "mode"
    STREAM_RULES = "stream_rules"
    MARKET_SLUGS = "market_slugs"
    WALLET_ADDRESSES = "wallet_addresses"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"


def _config_field(
    default: object,
    *,
    override_kind: ConfigOverrideKind | None = None,
    sensitive: bool = False,
    identity: bool = True,
) -> Any:
    metadata = {
        CONFIG_OVERRIDE_KIND: override_kind,
        CONFIG_SENSITIVE: sensitive,
        CONFIG_IDENTITY: identity,
    }
    if default is MISSING:
        return field(metadata=metadata)
    return field(default=default, metadata=metadata)


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
    name: str = _config_field(MISSING)
    mode: BotMode = _config_field(
        DEFAULT_BOT_MODE,
        override_kind=ConfigOverrideKind.MODE,
    )
    stream_rules: tuple[StreamRule, ...] = _config_field(
        (),
        override_kind=ConfigOverrideKind.STREAM_RULES,
    )
    market_slugs: tuple[str, ...] = _config_field(
        (),
        override_kind=ConfigOverrideKind.MARKET_SLUGS,
    )
    wallet_addresses: tuple[str, ...] = _config_field(
        (),
        override_kind=ConfigOverrideKind.WALLET_ADDRESSES,
    )
    data_trades_budget_per_10s: int = _config_field(
        DEFAULT_DATA_TRADES_BUDGET_PER_10S,
        override_kind=ConfigOverrideKind.INTEGER,
    )
    max_order_size: Decimal = _config_field(
        DEFAULT_MAX_ORDER_SIZE,
        override_kind=ConfigOverrideKind.DECIMAL,
    )
    max_slippage_pct: Decimal = _config_field(
        DEFAULT_MAX_SLIPPAGE_PCT,
        override_kind=ConfigOverrideKind.DECIMAL,
    )
    paper_latency_ms: int = _config_field(
        DEFAULT_PAPER_LATENCY_MS,
        override_kind=ConfigOverrideKind.INTEGER,
    )
    paper_latency_jitter_ms: int = _config_field(
        DEFAULT_PAPER_LATENCY_JITTER_MS,
        override_kind=ConfigOverrideKind.INTEGER,
    )
    event_max_age_ms: int = _config_field(
        DEFAULT_EVENT_MAX_AGE_MS,
        override_kind=ConfigOverrideKind.INTEGER,
    )
    paper_portfolio_usdc: Decimal = _config_field(
        DEFAULT_PAPER_PORTFOLIO_USDC,
        override_kind=ConfigOverrideKind.DECIMAL,
    )
    live_enabled: bool = _config_field(False, override_kind=ConfigOverrideKind.BOOLEAN)
    private_key: str | None = _config_field(
        None,
        override_kind=ConfigOverrideKind.TEXT,
        sensitive=True,
        identity=False,
    )
    api_key: str | None = _config_field(
        None,
        override_kind=ConfigOverrideKind.TEXT,
        sensitive=True,
        identity=False,
    )
    api_secret: str | None = _config_field(
        None,
        override_kind=ConfigOverrideKind.TEXT,
        sensitive=True,
        identity=False,
    )
    api_passphrase: str | None = _config_field(
        None,
        override_kind=ConfigOverrideKind.TEXT,
        sensitive=True,
        identity=False,
    )
    funder_address: str | None = _config_field(
        None,
        override_kind=ConfigOverrideKind.TEXT,
        sensitive=True,
        identity=False,
    )

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

    def without_sensitive_values(self) -> BotConfig:
        return replace(
            self,
            **{
                field_info.name: None
                for field_info in fields(self)
                if field_info.metadata[CONFIG_SENSITIVE]
            },
        )

    def identity_values(self) -> dict[str, object]:
        return {
            field_info.name: _configuration_json_value(getattr(self, field_info.name))
            for field_info in fields(self)
            if field_info.metadata[CONFIG_IDENTITY]
        }

    @classmethod
    def from_env(cls, name: str) -> BotConfig:
        values = config_values_from_env()
        values["mode"] = BotMode(values["mode"])
        return cls(name=name, **values)


def sensitive_config_field_names() -> frozenset[str]:
    return frozenset(
        field_info.name
        for field_info in fields(BotConfig)
        if field_info.metadata[CONFIG_SENSITIVE]
    )


def parse_config_override_value(key: str, raw: str) -> object:
    from polybot.framework.config.environment import parse_bool
    from polybot.framework.config.stream_rules import parse_stream_rules_json
    from polybot.framework.wallets import validate_wallet_address

    field_by_name = {field_info.name: field_info for field_info in fields(BotConfig)}
    field_info = field_by_name.get(key)
    kind = None if field_info is None else field_info.metadata[CONFIG_OVERRIDE_KIND]
    if kind is None:
        raise ValueError(f"invalid config override: {key}={raw}")
    if kind is ConfigOverrideKind.MODE:
        return BotMode(raw)
    if kind is ConfigOverrideKind.STREAM_RULES:
        return parse_stream_rules_json(raw)
    if kind is ConfigOverrideKind.MARKET_SLUGS:
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    if kind is ConfigOverrideKind.WALLET_ADDRESSES:
        return tuple(
            validate_wallet_address(part)
            for part in raw.split(",")
            if part.strip()
        )
    if kind is ConfigOverrideKind.INTEGER:
        return int(raw)
    if kind is ConfigOverrideKind.DECIMAL:
        return Decimal(raw)
    if kind is ConfigOverrideKind.BOOLEAN:
        return parse_bool(raw, key=key)
    return raw


def _configuration_json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StreamRule):
        return {
            "relation": value.relation.value,
            "market_slugs": list(value.market_slugs),
            "wallet_addresses": list(value.wallet_addresses),
        }
    if isinstance(value, tuple):
        return [_configuration_json_value(item) for item in value]
    return value
