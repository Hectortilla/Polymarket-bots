"""Public contracts for the reusable graph-template catalog."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.graph_templates.names import GraphTemplateName


class GraphTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: GraphTemplateName
    graph: NodeGraph


class GraphTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: GraphTemplateName | None = None
    graph: NodeGraph | None = None

    @model_validator(mode="after")
    def _require_change(self) -> "GraphTemplateUpdate":
        if self.name is None and self.graph is None:
            raise ValueError("at least one graph template field is required")
        return self


class GraphTemplateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: GraphTemplateName
    graph: NodeGraph
    created_at: datetime
    updated_at: datetime
