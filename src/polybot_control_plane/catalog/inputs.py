"""Typed launch inputs and paper-config conversion."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

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
from polybot.framework.wallets import validate_wallet_address
from polybot_control_plane.catalog.contracts import WIDGET_SCHEMA_KEY, WidgetKind
from polybot_control_plane.runs.contracts import (
    DataTradesBudget,
    NonnegativeDecimal,
    NonnegativeMilliseconds,
    PaperRunConfig,
    PositiveDecimal,
    RunName,
)


type WalletAddress = Annotated[str, AfterValidator(validate_wallet_address)]


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
        min_length=1,
        json_schema_extra={WIDGET_SCHEMA_KEY: WidgetKind.WALLET_ADDRESSES.value},
    )

    def _stream_rules(self) -> tuple[StreamRule, ...]:
        return (
            StreamRule(
                relation=StreamRelation.INDEPENDENT,
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
