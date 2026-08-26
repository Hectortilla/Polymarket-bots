"""Public catalog and launch request contracts."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from polybot_control_plane.catalog.graphs.catalog import GraphNodeCatalog


WIDGET_SCHEMA_KEY = "x-widget"

type DefinitionId = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
class SelectionMode(StrEnum):
    USER_CONFIGURED = "user_configured"
    BOT_MANAGED = "bot_managed"
    ABSENT = "absent"


class WidgetKind(StrEnum):
    DECIMAL = "decimal"
    MARKET_SLUGS = "market_slugs"
    NODE_GRAPH = "node_graph"
    WALLET_ADDRESSES = "wallet_addresses"
    STREAM_RULES = "stream_rules"


class BotDefinitionLabel(StrEnum):
    STANDARD = "standard"
    EXAMPLE = "example"
    NON_TRADING = "non_trading"


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


class LaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: DefinitionId
    inputs: dict[str, object]
