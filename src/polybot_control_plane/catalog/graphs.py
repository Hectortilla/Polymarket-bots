"""Validated node-graph launch and persistence contracts."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


NODE_GRAPH_SCHEMA_VERSION = 1
MAX_NODE_GRAPH_NODES = 50
MAX_NODE_GRAPH_EDGES = 100
NODE_GRAPH_COORDINATE_LIMIT = 10_000

type GraphElementId = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64),
]
type GraphLabel = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=80),
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


def _ensure_unique_ids(ids: tuple[str, ...], element_name: str) -> None:
    if len(ids) != len(set(ids)):
        raise ValueError(f"{element_name} IDs must be unique")


class GraphNodeType(StrEnum):
    INPUT = "input"
    DEFAULT = "default"
    OUTPUT = "output"


class GraphPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: GraphCoordinate
    y: GraphCoordinate


class GraphNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: GraphLabel


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: GraphNodeType
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
    def _validate_identity_and_references(self) -> "NodeGraph":
        node_ids = tuple(node.id for node in self.nodes)
        edge_ids = tuple(edge.id for edge in self.edges)
        _ensure_unique_ids(node_ids, "node")
        _ensure_unique_ids(edge_ids, "edge")
        known_nodes = frozenset(node_ids)
        if any(
            edge.source not in known_nodes or edge.target not in known_nodes
            for edge in self.edges
        ):
            raise ValueError("edge endpoints must reference existing nodes")
        return self


STARTER_NODE_GRAPH = NodeGraph(
    nodes=(
        GraphNode(
            id="market-input",
            type=GraphNodeType.INPUT,
            position=GraphPosition(x=0, y=80),
            data=GraphNodeData(label="Market input"),
        ),
        GraphNode(
            id="condition",
            type=GraphNodeType.DEFAULT,
            position=GraphPosition(x=240, y=80),
            data=GraphNodeData(label="Condition"),
        ),
        GraphNode(
            id="output",
            type=GraphNodeType.OUTPUT,
            position=GraphPosition(x=480, y=80),
            data=GraphNodeData(label="Output"),
        ),
    ),
    edges=(
        GraphEdge(
            id="market-input-condition",
            source="market-input",
            target="condition",
        ),
        GraphEdge(id="condition-output", source="condition", target="output"),
    ),
)
