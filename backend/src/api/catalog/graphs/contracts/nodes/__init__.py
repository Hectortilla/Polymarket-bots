"""Discriminated union of the graph node families."""

from typing import Annotated

from pydantic import Field

from .actions import GraphBrokerActionNode
from .comparisons import GraphComparisonNode
from .constants import GraphConstantNode
from .operations import GraphOperationNode
from .parameters import GraphParameterNode
from .triggers import GraphTriggerNode

type GraphNode = Annotated[
    GraphTriggerNode
    | GraphConstantNode
    | GraphComparisonNode
    | GraphBrokerActionNode
    | GraphOperationNode
    | GraphParameterNode,
    Field(discriminator="type"),
]
