"""Public catalog and launch request contracts."""

from pydantic import BaseModel, ConfigDict, Field

from polybot_control_plane.catalog.graphs.catalog import GraphNodeCatalog
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.catalog.values import (
    BotDefinitionLabel,
    DefinitionId,
    SelectionMode,
)


class BotDefinitionDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: DefinitionId
    display_name: str
    description: str
    label: BotDefinitionLabel
    market_selection: SelectionMode
    wallet_selection: SelectionMode
    input_schema: dict[str, object]
    graph_catalog: GraphNodeCatalog | None = Field(
        default=None,
        exclude_if=lambda catalog: catalog is None,
    )
    starter_graph: NodeGraph | None = Field(
        default=None,
        exclude_if=lambda graph: graph is None,
    )
