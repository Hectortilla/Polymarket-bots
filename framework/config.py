from __future__ import annotations

import os
import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Final, TypedDict, Unpack

from bots.framework.streams import StreamRelation, StreamRule


class BotMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


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
    book_max_age_ms: int
    paper_portfolio_usdc: Decimal
    live_enabled: bool
    private_key: str | None
    api_key: str | None
    api_secret: str | None
    api_passphrase: str | None
    funder_address: str | None


BOT_MODE_ENV: Final = "BOT_MODE"
BOT_STREAM_RULES_ENV: Final = "BOT_STREAM_RULES"
BOT_DATA_TRADES_BUDGET_PER_10S_ENV: Final = "BOT_DATA_TRADES_BUDGET_PER_10S"
BOT_MAX_ORDER_SIZE_ENV: Final = "BOT_MAX_ORDER_SIZE"
BOT_MAX_SLIPPAGE_PCT_ENV: Final = "BOT_MAX_SLIPPAGE_PCT"
BOT_PAPER_LATENCY_MS_ENV: Final = "BOT_PAPER_LATENCY_MS"
BOT_PAPER_LATENCY_JITTER_MS_ENV: Final = "BOT_PAPER_LATENCY_JITTER_MS"
BOT_BOOK_MAX_AGE_MS_ENV: Final = "BOT_BOOK_MAX_AGE_MS"
BOT_PAPER_PORTFOLIO_USDC_ENV: Final = "BOT_PAPER_PORTFOLIO_USDC"
BOT_LIVE_ENABLED_ENV: Final = "BOT_LIVE_ENABLED"
BOT_PRIVATE_KEY_ENV: Final = "POLYMARKET_PRIVATE_KEY"
BOT_API_KEY_ENV: Final = "POLY_API_KEY"
BOT_API_SECRET_ENV: Final = "POLY_API_SECRET"
BOT_API_PASSPHRASE_ENV: Final = "POLY_API_PASSPHRASE"
BOT_FUNDER_ADDRESS_ENV: Final = "DEPOSIT_WALLET_ADDRESS"

DEFAULT_BOT_MODE: Final = BotMode.PAPER
DEFAULT_MAX_ORDER_SIZE: Final = Decimal("10")
DEFAULT_MAX_SLIPPAGE_PCT: Final = Decimal("0.02")
DEFAULT_PAPER_LATENCY_MS: Final = 250
DEFAULT_PAPER_LATENCY_JITTER_MS: Final = 100
DEFAULT_BOOK_MAX_AGE_MS: Final = 5_000
DEFAULT_PAPER_PORTFOLIO_USDC: Final = Decimal("1000")
DEFAULT_DATA_TRADES_BUDGET_PER_10S: Final = 180
WALLET_ADDRESS_PATTERN: Final = re.compile(r"0x[a-fA-F0-9]{40}\Z")
DECIMAL_CONFIG_FIELDS: Final = frozenset(
    {"max_order_size", "max_slippage_pct", "paper_portfolio_usdc"}
)
INTEGER_CONFIG_FIELDS: Final = frozenset(
    {"paper_latency_ms", "paper_latency_jitter_ms", "book_max_age_ms", "data_trades_budget_per_10s"}
)


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
    book_max_age_ms: int = DEFAULT_BOOK_MAX_AGE_MS
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
            value = getattr(self, field_name)
            if not value.is_finite():
                raise ValueError(f"{field_name} must be finite")
        if self.max_order_size <= 0:
            raise ValueError("max_order_size must be positive")
        if self.max_slippage_pct < 0:
            raise ValueError("max_slippage_pct must be nonnegative")
        if self.paper_latency_ms < 0:
            raise ValueError("paper_latency_ms must be nonnegative")
        if self.paper_latency_jitter_ms < 0:
            raise ValueError("paper_latency_jitter_ms must be nonnegative")
        if self.book_max_age_ms < 0:
            raise ValueError("book_max_age_ms must be nonnegative")
        if self.paper_portfolio_usdc <= 0:
            raise ValueError("paper_portfolio_usdc must be positive")
        if not 1 <= self.data_trades_budget_per_10s <= DEFAULT_DATA_TRADES_BUDGET_PER_10S:
            raise ValueError("data_trades_budget_per_10s must be between 1 and 180")

    @classmethod
    def from_env(cls, name: str) -> BotConfig:
        return cls(
            name=name,
            mode=BotMode(os.getenv(BOT_MODE_ENV, DEFAULT_BOT_MODE.value)),
            stream_rules=_env_stream_rules(),
            data_trades_budget_per_10s=int(os.getenv(BOT_DATA_TRADES_BUDGET_PER_10S_ENV, str(DEFAULT_DATA_TRADES_BUDGET_PER_10S))),
            max_order_size=Decimal(
                os.getenv(BOT_MAX_ORDER_SIZE_ENV, str(DEFAULT_MAX_ORDER_SIZE))
            ),
            max_slippage_pct=Decimal(
                os.getenv(BOT_MAX_SLIPPAGE_PCT_ENV, str(DEFAULT_MAX_SLIPPAGE_PCT))
            ),
            paper_latency_ms=int(
                os.getenv(BOT_PAPER_LATENCY_MS_ENV, str(DEFAULT_PAPER_LATENCY_MS))
            ),
            paper_latency_jitter_ms=int(
                os.getenv(
                    BOT_PAPER_LATENCY_JITTER_MS_ENV,
                    str(DEFAULT_PAPER_LATENCY_JITTER_MS),
                )
            ),
            book_max_age_ms=int(
                os.getenv(BOT_BOOK_MAX_AGE_MS_ENV, str(DEFAULT_BOOK_MAX_AGE_MS))
            ),
            paper_portfolio_usdc=Decimal(
                os.getenv(
                    BOT_PAPER_PORTFOLIO_USDC_ENV,
                    str(DEFAULT_PAPER_PORTFOLIO_USDC),
                )
            ),
            live_enabled=_env_bool(BOT_LIVE_ENABLED_ENV),
            private_key=_optional_env(BOT_PRIVATE_KEY_ENV),
            api_key=_optional_env(BOT_API_KEY_ENV),
            api_secret=_optional_env(BOT_API_SECRET_ENV),
            api_passphrase=_optional_env(BOT_API_PASSPHRASE_ENV),
            funder_address=_optional_env(BOT_FUNDER_ADDRESS_ENV),
        )

    def with_overrides(self, **overrides: Unpack[BotConfigOverrides]) -> BotConfig:
        return replace(self, **overrides)

def _env_bool(key: str) -> bool:
    value = os.getenv(key, "false").lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{key} must be true or false")
    return value == "true"


def _optional_env(key: str) -> str | None:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return None
    return value


def _env_stream_rules() -> tuple[StreamRule, ...]:
    raw = os.getenv(BOT_STREAM_RULES_ENV)
    if raw is None or not raw.strip():
        return ()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{BOT_STREAM_RULES_ENV} must be valid JSON") from error
    if not isinstance(values, list):
        raise ValueError(f"{BOT_STREAM_RULES_ENV} must be a JSON array")
    rules: list[StreamRule] = []
    for value in values:
        if not isinstance(value, dict) or set(value) - {"relation", "market_slugs", "wallet_addresses"}:
            raise ValueError("stream rules contain unsupported fields")
        relation = value.get("relation")
        markets = value.get("market_slugs", [])
        wallets = value.get("wallet_addresses", [])
        if not isinstance(relation, str) or not isinstance(markets, list) or not isinstance(wallets, list):
            raise ValueError("stream rules have invalid field types")
        if not all(isinstance(item, str) for item in [*markets, *wallets]):
            raise ValueError("stream rule selectors must be strings")
        if any(WALLET_ADDRESS_PATTERN.fullmatch(wallet) is None for wallet in wallets):
            raise ValueError("stream rule wallet addresses must be 0x-prefixed addresses")
        rules.append(StreamRule(StreamRelation(relation), tuple(markets), tuple(wallets)))
    return tuple(dict.fromkeys(rules))
