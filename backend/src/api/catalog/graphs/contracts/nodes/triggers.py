from __future__ import annotations

from typing import ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
)

from api.catalog.graphs.catalog import (
    GRAPH_NODE_CATALOG,
    GraphNodeCatalog,
)
from api.catalog.graphs.types import (
    GraphElementId,
    GraphHookName,
)
from api.catalog.graphs.values import (
    GraphNodeType,
)

from .position import GraphPosition


class GraphTriggerNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog: ClassVar[GraphNodeCatalog] = GRAPH_NODE_CATALOG

    hook_name: GraphHookName

    @model_validator(mode="after")
    def _validate_hook(self) -> Self:
        if self.catalog.trigger(self.hook_name) is None:
            raise ValueError("graph trigger hook is not supported")
        return self


class GraphTriggerNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.TRIGGER]
    position: GraphPosition
    data: GraphTriggerNodeData
