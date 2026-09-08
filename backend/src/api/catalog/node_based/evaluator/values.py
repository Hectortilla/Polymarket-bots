"""Runtime values preserve unavailability separately from Boolean false."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from api.catalog.graphs.reasons import GraphReason

if TYPE_CHECKING:
    from api.catalog.graphs.evaluation_reasons import GraphEvaluationReason
from api.catalog.graphs.value_status import GraphValueStatus


@dataclass(frozen=True, slots=True)
class RuntimeValue:
    value: object | None = None
    status: GraphValueStatus = GraphValueStatus.AVAILABLE
    reason: GraphEvaluationReason | None = None
    input_handle_id: str | None = None
    message: str | None = None

    @classmethod
    def from_value(cls, value: object | None) -> "RuntimeValue":
        if value is None:
            return cls(None, GraphValueStatus.MISSING, GraphReason.MISSING)
        if type(value) is int:
            value = Decimal(value)
        if isinstance(value, Decimal) and not value.is_finite():
            return cls.invalid(GraphReason.INVALID_NUMBER)
        return cls(value)

    @classmethod
    def invalid(
        cls,
        reason: GraphEvaluationReason,
        *,
        input_handle_id: str | None = None,
        message: str | None = None,
    ) -> "RuntimeValue":
        return cls(None, GraphValueStatus.INVALID, reason, input_handle_id, message)

    @classmethod
    def skipped(cls, reason: GraphEvaluationReason) -> "RuntimeValue":
        return cls(None, GraphValueStatus.SKIPPED, reason)

    @property
    def available(self) -> bool:
        return self.status is GraphValueStatus.AVAILABLE
