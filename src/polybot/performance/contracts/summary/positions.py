"""Open-position section of a persisted performance summary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from polybot.performance.valuation import ValuationStatus

from ..files import PerformancePositionField
from ..parsing import (
    optional_decimal_text,
    required_decimal_text,
    required_text,
    require_exact_keys,
)


@dataclass(frozen=True, slots=True)
class PerformancePositionSummary:
    """One validated open position and its executable valuation state."""

    token_id: str
    size: str
    average_entry_price: str | None
    executable_mark: str | None
    last_executable_mark: str | None
    market_value_usdc: str | None
    valuation_status: ValuationStatus

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PerformancePositionSummary:
        """Decode one exact open-position summary object."""
        require_exact_keys(payload, PerformancePositionField, "open position")
        try:
            valuation_status = ValuationStatus(
                required_text(payload, PerformancePositionField.VALUATION_STATUS)
            )
        except ValueError as error:
            raise ValueError(
                "performance summary open position valuation status is invalid"
            ) from error
        return cls(
            token_id=required_text(payload, PerformancePositionField.TOKEN_ID),
            size=required_decimal_text(payload, PerformancePositionField.SIZE),
            average_entry_price=optional_decimal_text(
                payload,
                PerformancePositionField.AVERAGE_ENTRY_PRICE,
            ),
            executable_mark=optional_decimal_text(
                payload,
                PerformancePositionField.EXECUTABLE_MARK,
            ),
            last_executable_mark=optional_decimal_text(
                payload,
                PerformancePositionField.LAST_EXECUTABLE_MARK,
            ),
            market_value_usdc=optional_decimal_text(
                payload,
                PerformancePositionField.MARKET_VALUE_USDC,
            ),
            valuation_status=valuation_status,
        )

    def to_dict(self) -> dict[str, object]:
        """Encode the stable open-position section."""
        return {
            PerformancePositionField.TOKEN_ID: self.token_id,
            PerformancePositionField.SIZE: self.size,
            PerformancePositionField.AVERAGE_ENTRY_PRICE: self.average_entry_price,
            PerformancePositionField.EXECUTABLE_MARK: self.executable_mark,
            PerformancePositionField.LAST_EXECUTABLE_MARK: (
                self.last_executable_mark
            ),
            PerformancePositionField.MARKET_VALUE_USDC: self.market_value_usdc,
            PerformancePositionField.VALUATION_STATUS: self.valuation_status.value,
        }
