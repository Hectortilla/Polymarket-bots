"""Validated payloads carried by durable run events."""

from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    model_validator,
)

from polybot.cli.observability.events import (
    PortfolioPositionSnapshot,
    PortfolioSnapshot,
)
from polybot.cli.observability.states import (
    BootstrapPhase,
    validate_bootstrap_progress,
)
from polybot.dashboard.contracts import (
    DashboardSample,
    EquityChartPoint,
    MAX_CHART_TOKENS,
    MAX_WALLET_TIMELINE_EVENTS,
    MarketChartPoint,
    WalletChartPoint,
)
from polybot.dashboard.wallets import wallet_chart_point
from polybot.execution.paper.validation import validate_order
from polybot.framework.activity import ActivitySeverity, validate_activity_message
from polybot.framework.config.mode import BotMode
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import FillEvent, OrderRequest, Side
from polybot.framework.events.prices import is_outcome_price
from polybot.framework.events.resolutions import MarketSettlementEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.performance.contracts.valuation_status import ValuationStatus
from polybot_control_plane.runs.status import RunStatus


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunStartedPayload(EventPayload):
    status: Literal[RunStatus.STARTING] = RunStatus.STARTING
    name: str = Field(min_length=1)
    mode: BotMode
    initial_cash_usdc: Decimal = Field(gt=0)


class RunStatusPayload(EventPayload):
    status: RunStatus


class RunBootstrapPayload(EventPayload):
    phase: BootstrapPhase
    completed: int
    total: int

    @model_validator(mode="after")
    def _validate_progress(self) -> "RunBootstrapPayload":
        validate_bootstrap_progress(self.completed, self.total)
        return self


class BotActivityPayload(EventPayload):
    message: str
    severity: ActivitySeverity

    @model_validator(mode="after")
    def _validate_message(self) -> "BotActivityPayload":
        validate_activity_message(self.message)
        return self


class BrokerOrderPayload(EventPayload):
    order: OrderRequest

    @model_validator(mode="after")
    def _validate_order(self) -> "BrokerOrderPayload":
        _validate_durable_order(self.order)
        return self


class BrokerFillPayload(EventPayload):
    order: OrderRequest
    fill: FillEvent
    portfolio: PortfolioSnapshot | None
    latency_ms: NonNegativeInt

    @model_validator(mode="after")
    def _validate_order_and_portfolio(self) -> "BrokerFillPayload":
        _validate_durable_order(self.order)
        if self.portfolio is not None:
            _validate_portfolio_snapshot(self.portfolio)
        return self


class BrokerFailurePayload(EventPayload):
    order: OrderRequest
    error: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_order(self) -> "BrokerFailurePayload":
        _validate_durable_order(self.order)
        return self


class MarketSettlementPayload(EventPayload):
    settlement: MarketSettlementEvent
    portfolio: PortfolioSnapshot

    @model_validator(mode="after")
    def _validate_portfolio(self) -> "MarketSettlementPayload":
        _validate_portfolio_snapshot(self.portfolio)
        return self


class PortfolioSnapshotPayload(EventPayload):
    cash_usdc: Decimal
    cumulative_fees_usdc: Decimal = Field(ge=0)
    positions: tuple[PortfolioPositionSnapshot, ...]

    @model_validator(mode="after")
    def _validate_snapshot(self) -> "PortfolioSnapshotPayload":
        _validate_portfolio_values(
            self.cash_usdc,
            self.cumulative_fees_usdc,
            self.positions,
        )
        return self


class StreamHealthPayload(EventPayload):
    queue_depth: NonNegativeInt
    peak_queue_depth: NonNegativeInt
    book_dispatch_lag_ms: NonNegativeInt | None
    book_stale: bool
    book_received_count: NonNegativeInt
    book_coalesced_count: NonNegativeInt


class MarketChartPointPayload(EventPayload):
    token_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: Decimal | None
    status: ValuationStatus
    markers: tuple[Side, ...]

    @classmethod
    def from_point(cls, point: MarketChartPoint) -> "MarketChartPointPayload":
        return cls.model_validate(point, from_attributes=True)

    @model_validator(mode="after")
    def _validate_value_status(self) -> "MarketChartPointPayload":
        _validate_chart_value_status(self.value, self.status)
        return self


class EquityChartPointPayload(EventPayload):
    value: Decimal | None
    status: ValuationStatus

    @classmethod
    def from_point(cls, point: EquityChartPoint) -> "EquityChartPointPayload":
        return cls.model_validate(point, from_attributes=True)

    @model_validator(mode="after")
    def _validate_value_status(self) -> "EquityChartPointPayload":
        _validate_chart_value_status(self.value, self.status)
        return self


class WalletChartPointPayload(EventPayload):
    source_key: str = Field(min_length=1)
    wallet: str = Field(min_length=1)
    trade_timestamp_ms: NonNegativeInt
    side: Side
    notional: Decimal = Field(ge=0)
    market_label: str = Field(min_length=1)
    accepted: bool | None

    @classmethod
    def from_point(cls, point: WalletChartPoint) -> "WalletChartPointPayload":
        return cls.model_validate(point, from_attributes=True)


class WalletTimelinePayload(EventPayload):
    trade: WalletTradeEvent
    outcome: DispatchOutcome | None
    point: WalletChartPointPayload

    @model_validator(mode="after")
    def _validate_trade_and_point(self) -> "WalletTimelinePayload":
        if not self.trade.is_valid():
            raise ValueError("wallet timeline trade is invalid")
        expected = WalletChartPointPayload.from_point(
            wallet_chart_point(
                self.trade,
                accepted=None if self.outcome is None else self.outcome.accepted,
            )
        )
        if self.point != expected:
            raise ValueError("wallet timeline point does not match its trade")
        return self


class MarketChartPayload(EventPayload):
    sampled_at_ms: NonNegativeInt
    points: tuple[MarketChartPointPayload, ...] = Field(max_length=MAX_CHART_TOKENS)

    @classmethod
    def from_sample(cls, sample: DashboardSample) -> "MarketChartPayload":
        return cls(
            sampled_at_ms=sample.sampled_at_ms,
            points=tuple(
                MarketChartPointPayload.from_point(point)
                for point in sample.markets
            ),
        )


class EquityChartPayload(EventPayload):
    sampled_at_ms: NonNegativeInt
    point: EquityChartPointPayload

    @classmethod
    def from_sample(cls, sample: DashboardSample) -> "EquityChartPayload":
        return cls(
            sampled_at_ms=sample.sampled_at_ms,
            point=EquityChartPointPayload.from_point(sample.equity),
        )


class WalletChartPayload(EventPayload):
    sampled_at_ms: NonNegativeInt
    points: tuple[WalletChartPointPayload, ...] = Field(
        max_length=MAX_WALLET_TIMELINE_EVENTS
    )


class ChartSamplePayload(EventPayload):
    sampled_at_ms: NonNegativeInt
    markets: tuple[MarketChartPointPayload, ...] = Field(max_length=MAX_CHART_TOKENS)
    equity: EquityChartPointPayload

    @classmethod
    def from_sample(cls, sample: DashboardSample) -> "ChartSamplePayload":
        return cls(
            sampled_at_ms=sample.sampled_at_ms,
            markets=tuple(
                MarketChartPointPayload.from_point(point)
                for point in sample.markets
            ),
            equity=EquityChartPointPayload.from_point(sample.equity),
        )


class RunFailurePayload(EventPayload):
    error: str = Field(min_length=1)


def _validate_durable_order(order: OrderRequest) -> None:
    issue = validate_order(order)
    if issue is not None:
        _, detail = issue
        raise ValueError(detail)


def _validate_chart_value_status(
    value: Decimal | None,
    status: ValuationStatus,
) -> None:
    if value is not None and not value.is_finite():
        raise ValueError("chart value must be finite")
    if status is ValuationStatus.UNAVAILABLE and value is not None:
        raise ValueError("unavailable chart value must be null")
    if status is not ValuationStatus.UNAVAILABLE and value is None:
        raise ValueError("chart value and valuation status disagree")


def _validate_portfolio_snapshot(snapshot: PortfolioSnapshot) -> None:
    _validate_portfolio_values(
        snapshot.cash_usdc,
        snapshot.cumulative_fees_usdc,
        snapshot.positions,
    )


def _validate_portfolio_values(
    cash_usdc: Decimal,
    cumulative_fees_usdc: Decimal,
    positions: tuple[PortfolioPositionSnapshot, ...],
) -> None:
    if not cash_usdc.is_finite():
        raise ValueError("portfolio cash must be finite")
    if not cumulative_fees_usdc.is_finite() or cumulative_fees_usdc < 0:
        raise ValueError("portfolio fees must be finite and nonnegative")
    token_ids: set[str] = set()
    for position in positions:
        if not position.token_id or position.token_id in token_ids:
            raise ValueError("portfolio position token IDs must be non-empty and unique")
        token_ids.add(position.token_id)
        if not position.size.is_finite() or position.size < 0:
            raise ValueError("portfolio position size must be finite and nonnegative")
        if position.size == 0:
            if position.average_entry_price is not None:
                raise ValueError("empty portfolio positions cannot have an average price")
        elif position.average_entry_price is None or not is_outcome_price(
            position.average_entry_price
        ):
            raise ValueError(
                "open portfolio positions require a valid average outcome price"
            )
