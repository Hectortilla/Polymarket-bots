"""Serializable graph evaluation and diagnostic contracts."""

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr


class GraphValueStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    INVALID = "invalid"
    SKIPPED = "skipped"
    PLANNED = "planned"


class GraphReason(StrEnum):
    MISSING = "value_unavailable"
    INVALID_NUMBER = "invalid_number"
    DIVISION_BY_ZERO = "division_by_zero"
    INVALID_BOUNDS = "invalid_bounds"
    WHOLE_NUMBER_REQUIRED = "whole_number_required"
    PORTFOLIO_UNAVAILABLE = "portfolio_unavailable"
    COOLDOWN_ACTIVE = "cooldown_active"
    ALREADY_CONSUMED = "already_consumed"
    RESET = "reset"
    STATE_CAPACITY = "state_capacity_exceeded"
    INVALID_KEY = "invalid_key"
    DISABLED = "disabled"
    PLANNED = "planned"


class GraphValueRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: GraphValueStatus
    value: StrictBool | StrictStr | None = None
    reason: str | None = None
    input_handle_id: str | None = None
    message: str | None = None


class GraphNodeEvaluationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_id: str
    outputs: dict[str, GraphValueRead]
    status: GraphValueStatus = GraphValueStatus.AVAILABLE
    reason: str | None = None
