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
    GraphComparisonOperator,
    GraphNodeType,
)

from .position import GraphPosition


class GraphComparisonNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operator: GraphComparisonOperator


class GraphComparisonNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.COMPARISON]
    position: GraphPosition
    data: GraphComparisonNodeData
