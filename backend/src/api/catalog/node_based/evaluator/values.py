"""Runtime values preserve unavailability separately from Boolean false."""

from dataclasses import dataclass
from decimal import Decimal
from polybot.framework.context import BotContext
from api.catalog.graphs.results import (
    GraphReason,
    GraphValueRead,
    GraphValueStatus,
)


@dataclass(frozen=True, slots=True)
class RuntimeValue:
    value: object | None = None
    status: GraphValueStatus = GraphValueStatus.AVAILABLE
    reason: str | None = None
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
        reason: str,
        *,
        input_handle_id: str | None = None,
        message: str | None = None,
    ) -> "RuntimeValue":
        return cls(None, GraphValueStatus.INVALID, reason, input_handle_id, message)

    @classmethod
    def skipped(cls, reason: str) -> "RuntimeValue":
        return cls(None, GraphValueStatus.SKIPPED, reason)

    @property
    def available(self) -> bool:
        return self.status is GraphValueStatus.AVAILABLE

    def read(self) -> GraphValueRead:
        value = self.value
        if isinstance(value, BotContext):
            value = "Context"
        elif value is not None and not isinstance(value, (bool, str)):
            value = str(value)
        return GraphValueRead(
            status=self.status,
            value=value,
            reason=self.reason,
            input_handle_id=self.input_handle_id,
            message=self.message,
        )
