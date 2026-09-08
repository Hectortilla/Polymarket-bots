"""Public graph-node catalog descriptors and framework discovery assembly."""

from __future__ import annotations

from typing import Any, Literal, Self

from polybot_control_plane.catalog.graphs.ports import (
    GraphInputDescriptor,
    GraphOutputDescriptor,
)
from polybot_control_plane.catalog.graphs.preview_samples import (
    sample_payload,
    PREVIEW_SAMPLE_TIME_MS,
)
from polybot_control_plane.catalog.graphs.operations import (
    GraphOperationDescriptor,
    operation_descriptors,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    model_validator,
)

from polybot.framework.base import BaseBot
from polybot.framework.events import Side
from polybot_control_plane.catalog.graphs._actions import (
    DiscoveredBrokerAction,
    discover_broker_actions,
)
from polybot_control_plane.catalog.graphs._fields import DiscoveredGraphField
from polybot_control_plane.catalog.graphs._triggers import (
    DiscoveredGraphPayload,
    DiscoveredGraphTrigger,
    discover_graph_triggers,
)
from polybot_control_plane.catalog.graphs._validation import (
    ensure_unique_graph_trigger_hooks,
    ensure_unique_values,
)
from polybot_control_plane.catalog.graphs.comparisons import GRAPH_COMPARISON_SPECS
from polybot_control_plane.catalog.graphs.values import (
    GRAPH_BROKER_SUBMIT_METHOD_NAME,
    GRAPH_COMPARISON_LEFT_HANDLE_ID,
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GRAPH_COMPARISON_RIGHT_HANDLE_ID,
    GRAPH_CONTEXT_HANDLE_ID,
    GRAPH_CONTEXT_TYPE_NAME,
    GRAPH_VALUE_HANDLE_ID,
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphNodeType,
    GraphScalarType,
    GraphPort,
)
from polybot_control_plane.catalog.graphs.types import (
    GraphFieldPath,
    GraphHookName,
    GraphHandleId,
)


class GraphFieldDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: GraphFieldPath
    handle_id: GraphHandleId
    display_name: str
    value_type: str
    scalar_type: GraphScalarType | None
    nullable: bool
    collection: bool
    value_schema: dict[str, object]

    @classmethod
    def from_discovered(
        cls,
        payload_type_name: str,
        field: DiscoveredGraphField,
    ) -> Self:
        path = GraphFieldPath(segments=field.path)
        return cls(
            path=path,
            handle_id=path.handle_id,
            display_name=f"{payload_type_name}.{path.dotted}",
            value_type=field.value_type,
            scalar_type=field.scalar_type,
            nullable=field.nullable,
            collection=field.collection,
            value_schema=dict(field.value_schema),
        )


class GraphPayloadDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type_name: str
    fields: tuple[GraphFieldDescriptor, ...]

    @classmethod
    def from_discovered(cls, payload: DiscoveredGraphPayload) -> Self:
        return cls(
            type_name=payload.type_name,
            fields=tuple(
                GraphFieldDescriptor.from_discovered(payload.type_name, field)
                for field in payload.fields
            ),
        )

    def field_for_path(self, path: GraphFieldPath) -> GraphFieldDescriptor | None:
        return next((field for field in self.fields if field.path == path), None)


class GraphTriggerDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_type: Literal[GraphNodeType.TRIGGER] = GraphNodeType.TRIGGER
    hook_name: GraphHookName
    context_handle_id: Literal[GRAPH_CONTEXT_HANDLE_ID]
    context_type_name: Literal[GRAPH_CONTEXT_TYPE_NAME]
    payload: GraphPayloadDescriptor | None = None
    sample_payload: dict[str, Any] | None = None
    sample_time_ms: int = PREVIEW_SAMPLE_TIME_MS

    @classmethod
    def from_discovered(cls, trigger: DiscoveredGraphTrigger) -> Self:
        return cls(
            hook_name=trigger.hook_name,
            sample_payload=sample_payload(trigger.hook_name),
            context_handle_id=GRAPH_CONTEXT_HANDLE_ID,
            context_type_name=GRAPH_CONTEXT_TYPE_NAME,
            payload=(
                None
                if trigger.payload is None
                else GraphPayloadDescriptor.from_discovered(trigger.payload)
            ),
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
                    handle_id=name,
                    display_name="Execution Price" if name == GraphPort.AVERAGE_PRICE else name.replace("_", " ").title(),
                    scalar_type=kind,
                    nullable=name != GraphPort.STATUS,
                )
                for name, kind in (
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


class GraphNodeCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operations: tuple[GraphOperationDescriptor, ...] = ()
    triggers: tuple[GraphTriggerDescriptor, ...]
    constants: tuple[GraphConstantDescriptor, ...]
    comparisons: tuple[GraphComparisonDescriptor, ...]
    broker_actions: tuple[GraphBrokerActionDescriptor, ...]

    @model_validator(mode="after")
    def _validate_unique_entries(self) -> Self:
        ensure_unique_graph_trigger_hooks(
            tuple(trigger.hook_name for trigger in self.triggers),
        )
        ensure_unique_values(
            tuple(constant.scalar_type for constant in self.constants),
            "graph constant scalar type",
        )
        ensure_unique_values(
            tuple(comparison.operator for comparison in self.comparisons),
            "graph comparison operator",
        )
        ensure_unique_values(
            tuple(action.action for action in self.broker_actions),
            "graph broker action",
        )
        return self

    @classmethod
    def from_bot_type(cls, bot_type: type[Any]) -> Self:
        return cls(
            operations=operation_descriptors(),
            triggers=tuple(
                GraphTriggerDescriptor.from_discovered(trigger)
                for trigger in discover_graph_triggers(bot_type)
            ),
            constants=(
                GraphConstantDescriptor.from_scalar_type(
                    GraphScalarType.BOOLEAN,
                    False,
                ),
                GraphConstantDescriptor.from_scalar_type(
                    GraphScalarType.NUMBER,
                    "0",
                ),
                GraphConstantDescriptor.from_scalar_type(
                    GraphScalarType.STRING,
                    "",
                ),
            ),
            comparisons=tuple(
                GraphComparisonDescriptor.from_operator(operator)
                for operator in GraphComparisonOperator
            ),
            broker_actions=tuple(
                GraphBrokerActionDescriptor.from_discovered(action)
                for action in discover_broker_actions()
            ),
        )

    def trigger(self, hook_name: str) -> GraphTriggerDescriptor | None:
        return next(
            (trigger for trigger in self.triggers if trigger.hook_name == hook_name),
            None,
        )

    def constant(self, scalar_type: GraphScalarType) -> GraphConstantDescriptor:
        return next(item for item in self.constants if item.scalar_type is scalar_type)

    def comparison(
        self,
        operator: GraphComparisonOperator,
    ) -> GraphComparisonDescriptor:
        return next(item for item in self.comparisons if item.operator is operator)

    def broker_action(
        self,
        action: GraphBrokerAction,
    ) -> GraphBrokerActionDescriptor:
        return next(item for item in self.broker_actions if item.action is action)


GRAPH_NODE_CATALOG = GraphNodeCatalog.from_bot_type(BaseBot)
