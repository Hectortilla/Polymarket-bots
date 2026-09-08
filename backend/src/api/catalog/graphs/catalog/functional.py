from __future__ import annotations

from typing import Literal, Self

from polybot.framework.events import Side
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictStr,
)

from api.catalog.graphs._actions import (
    DiscoveredBrokerAction,
)
from api.catalog.graphs.comparisons import GRAPH_COMPARISON_SPECS
from api.catalog.graphs.ports import (
    GraphInputDescriptor,
    GraphOutputDescriptor,
)
from api.catalog.graphs.values import (
    GRAPH_BROKER_SUBMIT_METHOD_NAME,
    GRAPH_COMPARISON_LEFT_HANDLE_ID,
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GRAPH_COMPARISON_RIGHT_HANDLE_ID,
    GRAPH_VALUE_HANDLE_ID,
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphNodeType,
    GraphPort,
    GraphScalarType,
)


class GraphConstantDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_type: Literal[GraphNodeType.CONSTANT] = GraphNodeType.CONSTANT
    scalar_type: GraphScalarType
    display_name: str
    default_value: StrictBool | StrictStr
    output: GraphOutputDescriptor

    @classmethod
    def from_scalar_type(
        cls,
        scalar_type: GraphScalarType,
        default_value: bool | str,
    ) -> Self:
        return cls(
            scalar_type=scalar_type,
            display_name=f"{'Text' if scalar_type is GraphScalarType.STRING else scalar_type.value.title()} constant",
            default_value=default_value,
            output=GraphOutputDescriptor(
                handle_id=GRAPH_VALUE_HANDLE_ID,
                display_name="Value",
                scalar_type=scalar_type,
            ),
        )


class GraphComparisonDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_type: Literal[GraphNodeType.COMPARISON] = GraphNodeType.COMPARISON
    operator: GraphComparisonOperator
    display_name: str
    inputs: tuple[GraphInputDescriptor, GraphInputDescriptor]
    output: GraphOutputDescriptor

    @classmethod
    def from_operator(cls, operator: GraphComparisonOperator) -> Self:
        scalar_types = GRAPH_COMPARISON_SPECS[operator].scalar_types
        return cls(
            operator=operator,
            display_name=operator.value.replace("_", " ").title(),
            inputs=tuple(
                GraphInputDescriptor(
                    handle_id=handle_id,
                    display_name=handle_id.title(),
                    scalar_types=scalar_types,
                    nullable=True,
                    required=True,
                )
                for handle_id in (
                    GRAPH_COMPARISON_LEFT_HANDLE_ID,
                    GRAPH_COMPARISON_RIGHT_HANDLE_ID,
                )
            ),
            output=GraphOutputDescriptor(
                handle_id=GRAPH_COMPARISON_RESULT_HANDLE_ID,
                display_name="Result",
                scalar_type=GraphScalarType.BOOLEAN,
                nullable=True,
            ),
        )


class GraphBrokerActionDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_type: Literal[GraphNodeType.BROKER_ACTION] = GraphNodeType.BROKER_ACTION
    action: GraphBrokerAction
    method_name: Literal[GRAPH_BROKER_SUBMIT_METHOD_NAME]
    display_name: str
    side: Side
    inputs: tuple[GraphInputDescriptor, ...]
    outputs: tuple[GraphOutputDescriptor, ...] = ()

    @classmethod
    def from_discovered(cls, action: DiscoveredBrokerAction) -> Self:
        return cls(
            action=GraphBrokerAction(
                f"{GRAPH_BROKER_SUBMIT_METHOD_NAME}_{action.side.value.lower()}"
            ),
            method_name=action.method_name,
            display_name=f"{action.side.value} order",
            side=action.side,
            outputs=tuple(
                GraphOutputDescriptor(
                    handle_id=output_handle_id,
                    display_name="Execution Price"
                    if output_handle_id == GraphPort.AVERAGE_PRICE
                    else output_handle_id.replace("_", " ").title(),
                    scalar_type=output_scalar_type,
                    nullable=output_handle_id != GraphPort.STATUS,
                )
                for output_handle_id, output_scalar_type in (
                    (GraphPort.STATUS, GraphScalarType.STRING),
                    (GraphPort.FILLED_SIZE, GraphScalarType.NUMBER),
                    (GraphPort.AVERAGE_PRICE, GraphScalarType.NUMBER),
                    (GraphPort.SKIP_REASON, GraphScalarType.STRING),
                    (GraphPort.REJECT_REASON, GraphScalarType.STRING),
                )
            ),
            inputs=tuple(
                GraphInputDescriptor(
                    handle_id=input_.name,
                    display_name=input_.name.replace("_", " ").title(),
                    scalar_types=(input_.scalar_type,),
                    nullable=input_.nullable,
                    required=input_.required,
                )
                for input_ in action.inputs
            ),
        )
