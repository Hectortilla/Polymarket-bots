"""Incremental equity-curve metrics that do not retain CSV history."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .valuation import PortfolioValuation, ValuationStatus


ZERO = Decimal("0")


@dataclass(slots=True)
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

    def record(self, timestamp_ms: int, valuation: PortfolioValuation) -> None:
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or timestamp_ms < 0
        ):
            raise ValueError("equity sample timestamp must be nonnegative")
        if self.last_timestamp_ms is not None and timestamp_ms < self.last_timestamp_ms:
            raise ValueError("equity sample timestamps must be nondecreasing")
        if self.first_timestamp_ms is None:
            self.first_timestamp_ms = timestamp_ms
        self.last_timestamp_ms = timestamp_ms
        self.sample_count += 1
        self.final_valuation = valuation
        if valuation.status is ValuationStatus.STALE:
            self.stale_sample_count += 1
        elif valuation.status is ValuationStatus.UNAVAILABLE:
            self.unavailable_sample_count += 1
        if valuation.equity_usdc is None:
            return
        self.available_sample_count += 1
        self._record_drawdown(valuation.equity_usdc)

    @property
    def history_status(self) -> ValuationStatus:
        if self.unavailable_sample_count:
            return ValuationStatus.UNAVAILABLE
        if self.stale_sample_count:
            return ValuationStatus.STALE
        return ValuationStatus.FRESH

    @property
    def drawdown_status(self) -> ValuationStatus:
        return self.history_status

    def _record_drawdown(self, equity_usdc: Decimal) -> None:
        if self.peak_equity_usdc is None or equity_usdc > self.peak_equity_usdc:
            self.peak_equity_usdc = equity_usdc
        peak = self.peak_equity_usdc
        drawdown = max(peak - equity_usdc, ZERO)
        if self.max_drawdown_usdc is None or drawdown > self.max_drawdown_usdc:
            self.max_drawdown_usdc = drawdown
        if peak > ZERO:
            fraction = drawdown / peak
            if (
                self.max_drawdown_fraction is None
                or fraction > self.max_drawdown_fraction
            ):
                self.max_drawdown_fraction = fraction
