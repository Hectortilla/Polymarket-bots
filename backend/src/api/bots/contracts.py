"""Public saved-bot and immutable graph-revision contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api.bots.revisions import GraphRevisionNumber
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.values import DefinitionId
from api.runs.contracts import PaperRunConfig


class BotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: DefinitionId
    inputs: dict[str, object]
    graph_template_id: UUID | None = None


class BotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, object]


class BotGraphRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: NodeGraph


class BotGraphRevisionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    bot_id: UUID
    revision: GraphRevisionNumber
    graph: NodeGraph
    created_at: datetime


class BotRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    definition_id: DefinitionId
    config: PaperRunConfig
    latest_graph_revision: BotGraphRevisionRead | None = None
    created_at: datetime
    updated_at: datetime
