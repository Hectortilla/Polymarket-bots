from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from polybot.cli.observability.events import DispatchCompleted
from polybot.dashboard.contracts import (
    MAX_CHART_TOKENS,
    DashboardSample,
    EquityChartPoint,
    MarketChartPoint,
    WalletChartPoint,
)
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import Side
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.wallets import validate_wallet_address
from polybot.performance.contracts.valuation_status import ValuationStatus
from pydantic import (
    Field,
    NonNegativeInt,
    field_validator,
    model_validator,
)

from api.events.contracts.payloads.base import EventPayload, NonNegativeJsonInteger

CHART_NULL_VALUE_STATUSES = frozenset({ValuationStatus.UNAVAILABLE})
CHART_VALUE_REQUIRED_STATUSES = frozenset(ValuationStatus) - CHART_NULL_VALUE_STATUSES


class MarketChartPointPayload(EventPayload):
    token_id: str = Field(min_length=1, pattern=r"\S")
    label: str = Field(min_length=1, pattern=r"\S")
    value: Decimal | None
    status: ValuationStatus
    markers: tuple[Side, ...]

    @classmethod
    def from_point(cls, point: MarketChartPoint) -> MarketChartPointPayload:
        return cls.model_validate(point, from_attributes=True)

    @model_validator(mode="after")
    def _validate_value_status(self) -> MarketChartPointPayload:
        _validate_chart_value_status(self.value, self.status)
        return self


class EquityChartPointPayload(EventPayload):
    value: Decimal | None
    status: ValuationStatus

    @classmethod
    def from_point(cls, point: EquityChartPoint) -> EquityChartPointPayload:
        return cls.model_validate(point, from_attributes=True)

    @model_validator(mode="after")
    def _validate_value_status(self) -> EquityChartPointPayload:
        _validate_chart_value_status(self.value, self.status)
        return self


class WalletChartPointPayload(EventPayload):
    source_key: str = Field(min_length=1)
    wallet: str = Field(min_length=1)
    trade_timestamp_ms: NonNegativeInt
    side: Side
    notional: Decimal = Field(ge=0)
    market_label: str = Field(min_length=1, pattern=r"\S")
    accepted: bool | None

    @field_validator("wallet")
    @classmethod
    def _normalize_wallet(cls, wallet: str) -> str:
        return validate_wallet_address(wallet)

    @classmethod
    def from_point(cls, point: WalletChartPoint) -> WalletChartPointPayload:
        return cls.model_validate(point, from_attributes=True)


class WalletTimelinePayload(EventPayload):
    trade: WalletTradeEvent
    outcome: DispatchOutcome | None
    point: WalletChartPointPayload

    @field_validator("trade")
    @classmethod
    def _normalize_trade_wallet(cls, trade: WalletTradeEvent) -> WalletTradeEvent:
        return replace(trade, wallet=validate_wallet_address(trade.wallet))

    @model_validator(mode="after")
    def _validate_trade_and_point(self) -> WalletTimelinePayload:
        if not self.trade.is_valid():
            raise ValueError("wallet timeline trade is invalid")
        expected = WalletChartPointPayload.from_point(
            WalletChartPoint.from_trade(
                self.trade,
                accepted=None if self.outcome is None else self.outcome.accepted,
            )
        )
        if self.point != expected:
            raise ValueError("wallet timeline point does not match its trade")
        return self

    @classmethod
    def from_dispatch(cls, event: DispatchCompleted) -> WalletTimelinePayload:
        trade = event.item.event
        accepted = None if event.outcome is None else event.outcome.accepted
        return WalletTimelinePayload(
            trade=trade,
            outcome=event.outcome,
            point=WalletChartPointPayload.from_point(
                WalletChartPoint.from_trade(trade, accepted=accepted)
            ),
        )


class ChartSamplePayload(EventPayload):
    sampled_at_ms: NonNegativeJsonInteger
    markets: tuple[MarketChartPointPayload, ...] = Field(max_length=MAX_CHART_TOKENS)
    equity: EquityChartPointPayload

    @classmethod
    def from_sample(cls, sample: DashboardSample) -> ChartSamplePayload:
        return cls(
            sampled_at_ms=sample.sampled_at_ms,
            markets=tuple(
                MarketChartPointPayload.from_point(point) for point in sample.markets
            ),
            equity=EquityChartPointPayload.from_point(sample.equity),
        )


def _validate_chart_value_status(
    value: Decimal | None,
    status: ValuationStatus,
) -> None:
    if value is not None and not value.is_finite():
        raise ValueError("chart value must be finite")
    if status in CHART_NULL_VALUE_STATUSES and value is not None:
        raise ValueError("unavailable chart value must be null")
    if status in CHART_VALUE_REQUIRED_STATUSES and value is None:
        raise ValueError("chart value and valuation status disagree")
