from __future__ import annotations

from decimal import Decimal
from typing import Annotated, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

from api.catalog.graphs.catalog import (
    GRAPH_NODE_CATALOG,
    GraphNodeCatalog,
)
from api.catalog.graphs.contracts.limits import MAX_PARAMETER_NAME_LENGTH
from api.catalog.graphs.numbers import number_from_text
from api.catalog.graphs.operations import (
    DEFAULT_BOOLEAN_INPUT_IDS,
    MAX_BOOLEAN_INPUTS,
    MIN_BOOLEAN_INPUTS,
    OPERATION_DESCRIPTORS,
)
from api.catalog.graphs.ports import (
    GraphInputDescriptor,
    GraphOutputDescriptor,
)
from api.catalog.graphs.types import (
    GraphCoordinate,
    GraphElementId,
    GraphHandleId,
    GraphHookName,
)
from api.catalog.graphs.values import (
    DEFAULT_OPERATION_SCALAR_TYPE,
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphNodeType,
    GraphOperation,
    GraphPort,
    GraphScalarType,
)


class GraphPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: GraphCoordinate
    y: GraphCoordinate


class GraphTriggerNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog: ClassVar[GraphNodeCatalog] = GRAPH_NODE_CATALOG

    hook_name: GraphHookName

    @model_validator(mode="after")
    def _validate_hook(self) -> Self:
        if self.catalog.trigger(self.hook_name) is None:
            raise ValueError("graph trigger hook is not supported")
        return self


class GraphBooleanConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scalar_type: Literal[GraphScalarType.BOOLEAN]
    value: StrictBool


class GraphNumberConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scalar_type: Literal[GraphScalarType.NUMBER]
    value: StrictStr

    @field_validator("value")
    @classmethod
    def _validate_number(cls, value: str) -> str:
        number_from_text(value)
        return value


class GraphStringConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scalar_type: Literal[GraphScalarType.STRING]
    value: StrictStr


type GraphConstantNodeData = Annotated[
    GraphBooleanConstantData | GraphNumberConstantData | GraphStringConstantData,
    Field(discriminator="scalar_type"),
]


class GraphComparisonNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operator: GraphComparisonOperator


class GraphBrokerActionNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: GraphBrokerAction


class GraphTriggerNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.TRIGGER]
    position: GraphPosition
    data: GraphTriggerNodeData


class GraphConstantNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.CONSTANT]
    position: GraphPosition
    data: GraphConstantNodeData

    def runtime_value(self) -> object:
        return (
            Decimal(self.data.value)
            if self.data.scalar_type is GraphScalarType.NUMBER
            else self.data.value
        )


class GraphComparisonNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.COMPARISON]
    position: GraphPosition
    data: GraphComparisonNodeData


class GraphBrokerActionNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.BROKER_ACTION]
    position: GraphPosition
    data: GraphBrokerActionNodeData


class GraphParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: GraphElementId
    name: str = Field(min_length=1, max_length=MAX_PARAMETER_NAME_LENGTH)
    data: GraphConstantNodeData


class GraphParameterNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    parameter_id: GraphElementId


class GraphParameterNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: GraphElementId
    type: Literal[GraphNodeType.PARAMETER]
    position: GraphPosition
    data: GraphParameterNodeData


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


type GraphNode = Annotated[
    GraphTriggerNode
    | GraphConstantNode
    | GraphComparisonNode
    | GraphBrokerActionNode
    | GraphOperationNode
    | GraphParameterNode,
    Field(discriminator="type"),
]
