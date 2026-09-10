"""Public saved-bot configuration contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api.catalog.graphs.contracts import NodeGraph
from api.catalog.values import DefinitionId
from api.runs.contracts import PaperRunConfig


class BotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: DefinitionId
    inputs: dict[str, object]
    graph: NodeGraph | None = None


class BotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, object]
    graph: NodeGraph | None = None


class BotRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    definition_id: DefinitionId
    config: PaperRunConfig
    created_at: datetime
    updated_at: datetime
