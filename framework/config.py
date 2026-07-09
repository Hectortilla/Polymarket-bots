from __future__ import annotations

import os
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Final


class BotMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


BOT_MODE_ENV: Final = "BOT_MODE"
BOT_MARKET_SLUGS_ENV: Final = "BOT_MARKET_SLUGS"
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


@dataclass(frozen=True, slots=True)
class BotConfig:
    name: str
    mode: BotMode = DEFAULT_BOT_MODE
    market_slugs: tuple[str, ...] = ()
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

    @classmethod
    def from_env(cls, name: str) -> BotConfig:
        return cls(
            name=name,
            mode=BotMode(os.getenv(BOT_MODE_ENV, DEFAULT_BOT_MODE.value)),
            market_slugs=_env_csv(BOT_MARKET_SLUGS_ENV),
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

    def with_overrides(self, **overrides: object) -> BotConfig:
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


def _env_csv(key: str) -> tuple[str, ...]:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())
