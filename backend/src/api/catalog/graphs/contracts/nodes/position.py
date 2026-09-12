from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
)

from api.catalog.graphs.types import (
    GraphCoordinate,
)


class GraphPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: GraphCoordinate
    y: GraphCoordinate
