"""Incremental equity-curve metrics that do not retain CSV history."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .valuation import (
    PortfolioValuation,
    ValuationStatus,
    aggregate_valuation_status,
)


ZERO_DRAWDOWN = Decimal("0")


@dataclass(frozen=True, slots=True)
class EquityCurveMetrics:
    sample_count: int = 0
    available_sample_count: int = 0
    stale_sample_count: int = 0
    unavailable_sample_count: int = 0
    peak_equity_usdc: Decimal | None = None
    max_drawdown_usdc: Decimal | None = None
    max_drawdown_fraction: Decimal | None = None
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    final_valuation: PortfolioValuation | None = None

    def after_sample(
        self,
        timestamp_ms: int,
        valuation: PortfolioValuation,
    ) -> EquityCurveMetrics:
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or timestamp_ms < 0
        ):
            raise ValueError("equity sample timestamp must be nonnegative")
        if self.last_timestamp_ms is not None and timestamp_ms < self.last_timestamp_ms:
            raise ValueError("equity sample timestamps must be nondecreasing")
        stale_count = self.stale_sample_count + (
            valuation.status is ValuationStatus.STALE
        )
        unavailable_count = self.unavailable_sample_count + (
            valuation.status is ValuationStatus.UNAVAILABLE
        )
        available_count = self.available_sample_count + (
            valuation.equity_usdc is not None
        )
        peak, max_drawdown, max_fraction = _after_drawdown(
            valuation.equity_usdc,
            peak_equity_usdc=self.peak_equity_usdc,
            max_drawdown_usdc=self.max_drawdown_usdc,
            max_drawdown_fraction=self.max_drawdown_fraction,
        )
        return EquityCurveMetrics(
            sample_count=self.sample_count + 1,
            available_sample_count=available_count,
            stale_sample_count=stale_count,
            unavailable_sample_count=unavailable_count,
            peak_equity_usdc=peak,
            max_drawdown_usdc=max_drawdown,
            max_drawdown_fraction=max_fraction,
            first_timestamp_ms=(
                timestamp_ms if self.first_timestamp_ms is None else self.first_timestamp_ms
            ),
            last_timestamp_ms=timestamp_ms,
            final_valuation=valuation,
        )

    @property
    def history_status(self) -> ValuationStatus:
        statuses = []
        if self.unavailable_sample_count:
            statuses.append(ValuationStatus.UNAVAILABLE)
        if self.stale_sample_count:
            statuses.append(ValuationStatus.STALE)
        return aggregate_valuation_status(statuses)

    @property
    def drawdown_status(self) -> ValuationStatus:
        return self.history_status



def _after_drawdown(
    equity_usdc: Decimal | None,
    *,
    peak_equity_usdc: Decimal | None,
    max_drawdown_usdc: Decimal | None,
    max_drawdown_fraction: Decimal | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if equity_usdc is None:
        return peak_equity_usdc, max_drawdown_usdc, max_drawdown_fraction
    peak = (
        equity_usdc
        if peak_equity_usdc is None or equity_usdc > peak_equity_usdc
        else peak_equity_usdc
    )
    drawdown = max(peak - equity_usdc, ZERO_DRAWDOWN)
    maximum = (
        drawdown
        if max_drawdown_usdc is None or drawdown > max_drawdown_usdc
        else max_drawdown_usdc
    )
    fraction_maximum = max_drawdown_fraction
    if peak > ZERO_DRAWDOWN:
        fraction = drawdown / peak
        if fraction_maximum is None or fraction > fraction_maximum:
            fraction_maximum = fraction
    return peak, maximum, fraction_maximum
