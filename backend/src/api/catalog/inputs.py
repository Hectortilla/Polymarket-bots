"""Typed launch inputs and paper-config conversion."""

from __future__ import annotations

from polybot.framework.config.constants import (
    DEFAULT_DATA_TRADES_BUDGET,
    DEFAULT_EVENT_MAX_AGE_MS,
    DEFAULT_MAX_ORDER_SIZE,
    DEFAULT_MAX_SLIPPAGE_PCT,
    DEFAULT_PAPER_LATENCY_JITTER_MS,
    DEFAULT_PAPER_LATENCY_MS,
    DEFAULT_PAPER_PORTFOLIO_USDC,
)
from polybot.framework.streams import StreamRelation, StreamRule
from pydantic import BaseModel, ConfigDict, Field

from api.catalog.values import WIDGET_SCHEMA_KEY, WidgetKind
from api.market_selection import MAX_SELECTED_MARKETS, MIN_SELECTED_MARKETS, MarketSlug
from api.runs.contracts import (
    DataTradesBudget,
    NonnegativeDecimal,
    NonnegativeMilliseconds,
    PaperRunConfig,
    PositiveDecimal,
    RunName,
)
from api.wallet_selection import (
    MAX_SELECTED_WALLETS,
    MIN_SELECTED_WALLETS,
    WalletAddress,
)


class PaperLaunchInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RunName
    data_trades_budget_per_10s: DataTradesBudget = Field(
        default=DEFAULT_DATA_TRADES_BUDGET,
    )
    max_order_size: PositiveDecimal = Field(
        default=DEFAULT_MAX_ORDER_SIZE,
        json_schema_extra={WIDGET_SCHEMA_KEY: WidgetKind.DECIMAL.value},
    )
    max_slippage_pct: NonnegativeDecimal = Field(
        default=DEFAULT_MAX_SLIPPAGE_PCT,
        json_schema_extra={WIDGET_SCHEMA_KEY: WidgetKind.DECIMAL.value},
    )
    paper_latency_ms: NonnegativeMilliseconds = Field(
        default=DEFAULT_PAPER_LATENCY_MS,
    )
    paper_latency_jitter_ms: NonnegativeMilliseconds = Field(
        default=DEFAULT_PAPER_LATENCY_JITTER_MS,
    )
    event_max_age_ms: NonnegativeMilliseconds = Field(
        default=DEFAULT_EVENT_MAX_AGE_MS,
    )
    paper_portfolio_usdc: PositiveDecimal = Field(
        default=DEFAULT_PAPER_PORTFOLIO_USDC,
        json_schema_extra={WIDGET_SCHEMA_KEY: WidgetKind.DECIMAL.value},
    )

    def to_run_config(self) -> PaperRunConfig:
        return PaperRunConfig(
            name=self.name,
            stream_rules=self._stream_rules(),
            data_trades_budget_per_10s=self.data_trades_budget_per_10s,
            max_order_size=self.max_order_size,
            max_slippage_pct=self.max_slippage_pct,
            paper_latency_ms=self.paper_latency_ms,
            paper_latency_jitter_ms=self.paper_latency_jitter_ms,
            event_max_age_ms=self.event_max_age_ms,
            paper_portfolio_usdc=self.paper_portfolio_usdc,
        )

    def _stream_rules(self) -> tuple[StreamRule, ...]:
        return ()


class WalletPaperLaunchInputs(PaperLaunchInputs):
    wallet_addresses: tuple[WalletAddress, ...] = Field(
        min_length=MIN_SELECTED_WALLETS,
        max_length=MAX_SELECTED_WALLETS,
        json_schema_extra={WIDGET_SCHEMA_KEY: WidgetKind.WALLET_ADDRESSES.value},
    )

    def _stream_rules(self) -> tuple[StreamRule, ...]:
        return (
            StreamRule(
                relation=StreamRelation.INDEPENDENT,
                wallet_addresses=self.wallet_addresses,
            ),
        )


class NodeBasedLaunchInputs(PaperLaunchInputs):
    market_slugs: tuple[MarketSlug, ...] = Field(
        title="Markets",
        min_length=MIN_SELECTED_MARKETS,
        max_length=MAX_SELECTED_MARKETS,
        json_schema_extra={WIDGET_SCHEMA_KEY: WidgetKind.MARKET_SLUGS.value},
    )

    wallet_addresses: tuple[WalletAddress, ...] = Field(
        default=(),
        title="Wallets",
        description="Follow these wallets across markets. Wallet trade triggers receive their activity.",
        max_length=MAX_SELECTED_WALLETS,
        json_schema_extra={WIDGET_SCHEMA_KEY: WidgetKind.WALLET_ADDRESSES.value},
    )

    def _stream_rules(self) -> tuple[StreamRule, ...]:
        return (
            StreamRule(
                relation=StreamRelation.INDEPENDENT,
                market_slugs=self.market_slugs,
                wallet_addresses=self.wallet_addresses,
            ),
        )


class WinnerLaunchInputs(PaperLaunchInputs):
    pass


class MomentumExampleLaunchInputs(PaperLaunchInputs):
    pass


class ContrarianLaunchInputs(PaperLaunchInputs):
    pass


class MarketWatcherLaunchInputs(PaperLaunchInputs):
    pass


class RandomHoldExampleLaunchInputs(PaperLaunchInputs):
    pass


class WalletFilterCopyExampleLaunchInputs(WalletPaperLaunchInputs):
    pass
