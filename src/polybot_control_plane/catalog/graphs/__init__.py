"""Validated node graphs and BaseBot-derived trigger metadata."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot_control_plane.catalog.graphs._fields import DiscoveredGraphField
from polybot_control_plane.catalog.graphs._triggers import (
    DiscoveredGraphPayload,
    DiscoveredGraphTrigger,
    discover_graph_triggers,
)


NODE_GRAPH_SCHEMA_VERSION = 1
MAX_NODE_GRAPH_NODES = 50
MAX_NODE_GRAPH_EDGES = 0
NODE_GRAPH_COORDINATE_LIMIT = 10_000
GRAPH_CONTEXT_HANDLE_ID = "context"
GRAPH_FIELD_HANDLE_PREFIX = "field:"
STARTER_TRIGGER_HOOK_NAME = "on_book"
STARTER_BOOK_OUTPUT_FIELD = "bids"

type GraphElementId = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64),
]
type GraphHookName = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        pattern=r"^on_[a-z][a-z0-9_]*$",
        max_length=64,
    ),
]
type GraphFieldPathSegment = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=64,
    ),
]
type GraphCoordinate = Annotated[
    float,
    Field(
        strict=True,
        allow_inf_nan=False,
        ge=-NODE_GRAPH_COORDINATE_LIMIT,
        le=NODE_GRAPH_COORDINATE_LIMIT,
    ),
]


def _ensure_unique_values(values: tuple[str, ...], value_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{value_name} values must be unique")


class GraphNodeType(StrEnum):
    TRIGGER = "trigger"


class GraphFieldPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segments: tuple[GraphFieldPathSegment, ...] = Field(min_length=1)

    @property
    def dotted(self) -> str:
        return ".".join(self.segments)

    @property
    def handle_id(self) -> str:
        return f"{GRAPH_FIELD_HANDLE_PREFIX}{self.dotted}"


class GraphFieldDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: GraphFieldPath
    handle_id: str
    display_name: str
    value_type: str
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

    hook_name: GraphHookName
    context_handle_id: Literal["context"]
    context_type_name: Literal["BotContext"]
    payload: GraphPayloadDescriptor | None = None

    @classmethod
    def from_discovered(cls, trigger: DiscoveredGraphTrigger) -> Self:
        return cls(
            hook_name=trigger.hook_name,
            context_handle_id=GRAPH_CONTEXT_HANDLE_ID,
            context_type_name=BotContext.__name__,
            payload=(
                None
                if trigger.payload is None
                else GraphPayloadDescriptor.from_discovered(trigger.payload)
            ),
        )


class GraphNodeCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_type: Literal[GraphNodeType.TRIGGER]
    triggers: tuple[GraphTriggerDescriptor, ...]

    @model_validator(mode="after")
    def _validate_unique_hooks(self) -> Self:
        _ensure_unique_values(
            tuple(trigger.hook_name for trigger in self.triggers),
            "graph trigger hook",
        )
        return self

    @classmethod
    def from_bot_type(cls, bot_type: type[Any]) -> Self:
        return cls(
            node_type=GraphNodeType.TRIGGER,
            triggers=tuple(
                GraphTriggerDescriptor.from_discovered(trigger)
                for trigger in discover_graph_triggers(bot_type)
            )
        )

    def trigger(self, hook_name: str) -> GraphTriggerDescriptor | None:
        return next(
            (trigger for trigger in self.triggers if trigger.hook_name == hook_name),
            None,
        )


GRAPH_NODE_CATALOG = GraphNodeCatalog.from_bot_type(BaseBot)


class GraphPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: GraphCoordinate
    y: GraphCoordinate


class GraphNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog: ClassVar[GraphNodeCatalog] = GRAPH_NODE_CATALOG

    hook_name: GraphHookName
    selected_output_paths: tuple[GraphFieldPath, ...] = ()

    @model_validator(mode="after")
    def _validate_hook_and_outputs(self) -> Self:
        trigger = self.catalog.trigger(self.hook_name)
        if trigger is None:
            raise ValueError("graph trigger hook is not supported")
        selected_keys = tuple(path.dotted for path in self.selected_output_paths)
        _ensure_unique_values(selected_keys, "selected graph output path")
        if trigger.payload is None:
            if self.selected_output_paths:
                raise ValueError("payload-less graph triggers cannot select output fields")
            return self
        if any(
            trigger.payload.field_for_path(path) is None
            for path in self.selected_output_paths
        ):
            raise ValueError("selected graph output path does not belong to the trigger payload")
        return self


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.TRIGGER]
    position: GraphPosition
    data: GraphNodeData


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    source: GraphElementId
    target: GraphElementId


class NodeGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[NODE_GRAPH_SCHEMA_VERSION] = NODE_GRAPH_SCHEMA_VERSION
    nodes: tuple[GraphNode, ...] = Field(
        min_length=1,
        max_length=MAX_NODE_GRAPH_NODES,
    )
    edges: tuple[GraphEdge, ...] = Field(
        default=(),
        max_length=MAX_NODE_GRAPH_EDGES,
    )

    @model_validator(mode="after")
    def _validate_unique_nodes_and_hooks(self) -> Self:
        _ensure_unique_values(tuple(node.id for node in self.nodes), "graph node ID")
        _ensure_unique_values(
            tuple(node.data.hook_name for node in self.nodes),
            "graph trigger hook",
        )
        return self


STARTER_BOOK_OUTPUT_PATH = GraphFieldPath(
    segments=(STARTER_BOOK_OUTPUT_FIELD,),
)
STARTER_NODE_GRAPH = NodeGraph(
    nodes=(
        GraphNode(
            id="on-book-trigger",
            type=GraphNodeType.TRIGGER,
            position=GraphPosition(x=80, y=80),
            data=GraphNodeData(
                hook_name=STARTER_TRIGGER_HOOK_NAME,
                selected_output_paths=(STARTER_BOOK_OUTPUT_PATH,),
            ),
        ),
    ),
)
