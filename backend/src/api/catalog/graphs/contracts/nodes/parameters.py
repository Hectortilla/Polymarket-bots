from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from api.catalog.graphs.contracts.limits import MAX_PARAMETER_NAME_LENGTH
from api.catalog.graphs.types import (
    GraphElementId,
)
from api.catalog.graphs.values import (
    GraphNodeType,
)

from .constants import GraphConstantNodeData
from .position import GraphPosition


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
