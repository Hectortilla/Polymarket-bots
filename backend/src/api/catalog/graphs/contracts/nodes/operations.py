from __future__ import annotations

from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
)

from api.catalog.graphs.operations import OPERATION_DESCRIPTORS
from api.catalog.graphs.operations.logic import (
    DEFAULT_BOOLEAN_INPUT_IDS,
    MAX_BOOLEAN_INPUTS,
    MIN_BOOLEAN_INPUTS,
)
from api.catalog.graphs.ports import (
    GraphInputDescriptor,
    GraphOutputDescriptor,
)
from api.catalog.graphs.types import (
    GraphElementId,
    GraphHandleId,
)
from api.catalog.graphs.values import (
    DEFAULT_OPERATION_SCALAR_TYPE,
    GraphNodeType,
    GraphOperation,
    GraphPort,
    GraphScalarType,
)

from .position import GraphPosition


class GraphOperationNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation: GraphOperation
    input_ids: tuple[GraphHandleId, ...] = ()
    scalar_type: GraphScalarType = DEFAULT_OPERATION_SCALAR_TYPE

    @model_validator(mode="after")
    def _validate_dynamic_inputs(self) -> Self:
        expandable = OPERATION_DESCRIPTORS[self.operation].expandable
        if expandable:
            ids = self.input_ids or DEFAULT_BOOLEAN_INPUT_IDS
            if not MIN_BOOLEAN_INPUTS <= len(ids) <= MAX_BOOLEAN_INPUTS or len(
                set(ids)
            ) != len(ids):
                raise ValueError(
                    f"Boolean inputs require {MIN_BOOLEAN_INPUTS}–{MAX_BOOLEAN_INPUTS} unique handles"
                )
        elif self.input_ids:
            raise ValueError("Only AND and OR support expandable inputs")
        return self


class GraphOperationNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: GraphElementId
    type: Literal[GraphNodeType.OPERATION]
    position: GraphPosition
    data: GraphOperationNodeData

    def inputs(self) -> tuple[GraphInputDescriptor, ...]:
        descriptor = OPERATION_DESCRIPTORS[self.data.operation]
        if descriptor.expandable:
            return tuple(
                descriptor.inputs[0].model_copy(
                    update={
                        "handle_id": input_handle_id,
                        "display_name": input_handle_id,
                    }
                )
                for input_handle_id in self.data.input_ids or DEFAULT_BOOLEAN_INPUT_IDS
            )
        if OPERATION_DESCRIPTORS[self.data.operation].selectable_scalar_type:
            return tuple(
                (
                    port.model_copy(update={"scalar_types": (self.data.scalar_type,)})
                    if port.handle_id != GraphPort.CONDITION
                    else port
                )
                for port in descriptor.inputs
            )
        return descriptor.inputs

    def outputs(self) -> tuple[GraphOutputDescriptor, ...]:
        outputs = OPERATION_DESCRIPTORS[self.data.operation].outputs
        if OPERATION_DESCRIPTORS[self.data.operation].selectable_scalar_type:
            return tuple(
                port.model_copy(update={"scalar_type": self.data.scalar_type})
                for port in outputs
            )
        return outputs
