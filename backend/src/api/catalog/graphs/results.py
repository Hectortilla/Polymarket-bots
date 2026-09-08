"""Serializable graph evaluation and diagnostic contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.catalog.graphs.value_status import GraphValueStatus

if TYPE_CHECKING:
    from api.catalog.node_based.evaluator.values import RuntimeValue

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from api.catalog.graphs.evaluation_reasons import GraphEvaluationReason


class GraphValueRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: GraphValueStatus
    value: StrictBool | StrictStr | None = None
    reason: GraphEvaluationReason | None = None
    input_handle_id: str | None = None
    message: str | None = None

    @classmethod
    def from_runtime(cls, runtime: RuntimeValue) -> GraphValueRead:
        value = runtime.value
        if value is not None and not isinstance(value, (bool, str)):
            value = str(value)
        return cls(
            status=runtime.status,
            value=value,
            reason=runtime.reason,
            input_handle_id=runtime.input_handle_id,
            message=runtime.message,
        )


class GraphNodeEvaluationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_id: str
    outputs: dict[str, GraphValueRead]
    status: GraphValueStatus = GraphValueStatus.AVAILABLE
    reason: GraphEvaluationReason | None = None
