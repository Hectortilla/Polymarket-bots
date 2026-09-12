from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
)

from api.catalog.graphs.types import (
    GraphElementId,
)
from api.catalog.graphs.values import (
    GraphBrokerAction,
    GraphNodeType,
)

from .position import GraphPosition


class GraphBrokerActionNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: GraphBrokerAction


class GraphBrokerActionNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.BROKER_ACTION]
    position: GraphPosition
    data: GraphBrokerActionNodeData
