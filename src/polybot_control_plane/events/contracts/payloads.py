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
from polybot.execution.paper.validation import validate_order
from polybot.framework.activity import ActivitySeverity, validate_activity_message
from polybot.framework.config.mode import BotMode
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import FillEvent, OrderRequest
from polybot.framework.events.prices import is_outcome_price
from polybot.framework.events.resolutions import MarketSettlementEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
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


class WalletTimelinePayload(EventPayload):
    trade: WalletTradeEvent
    outcome: DispatchOutcome | None

    @model_validator(mode="after")
    def _validate_trade(self) -> "WalletTimelinePayload":
        if not self.trade.is_valid():
            raise ValueError("wallet timeline trade is invalid")
        return self


class StreamHealthPayload(EventPayload):
    queue_depth: NonNegativeInt
    peak_queue_depth: NonNegativeInt
    book_dispatch_lag_ms: NonNegativeInt | None
    book_stale: bool
    book_received_count: NonNegativeInt
    book_coalesced_count: NonNegativeInt


class RunFailurePayload(EventPayload):
    error: str = Field(min_length=1)


def _validate_durable_order(order: OrderRequest) -> None:
    issue = validate_order(order)
    if issue is not None:
        _, detail = issue
        raise ValueError(detail)


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
