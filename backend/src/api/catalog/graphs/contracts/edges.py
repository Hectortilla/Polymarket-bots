from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
)

from api.catalog.graphs.types import (
    GraphEdgeId,
    GraphElementId,
    GraphHandleId,
)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphEdgeId
    source: GraphElementId
    source_handle: GraphHandleId
    target: GraphElementId
    target_handle: GraphHandleId
