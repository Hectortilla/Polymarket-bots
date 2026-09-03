"""Generate frontend runtime constants from the backend catalog contract."""

from __future__ import annotations

import json
from pathlib import Path

from polybot_control_plane.catalog.values import (
    BotDefinitionLabel,
    WIDGET_SCHEMA_KEY,
    SelectionMode,
    WidgetKind,
)
from polybot_control_plane.graph_templates.names import (
    GRAPH_TEMPLATE_NAME_MAX_LENGTH,
)
from polybot_control_plane.catalog.graphs.values import (
    GRAPH_BROKER_SUBMIT_METHOD_NAME,
    GRAPH_FIELD_PATH_SEPARATOR,
    GRAPH_FIELD_PATH_SEGMENT_PATTERN,
    GRAPH_HOOK_NAME_PATTERN,
    MAX_GRAPH_EDGE_IDENTIFIER_LENGTH,
    MAX_GRAPH_IDENTIFIER_LENGTH,
    MIN_GRAPH_FIELD_PATH_SEGMENTS,
    MIN_GRAPH_IDENTIFIER_LENGTH,
    MIN_GRAPH_INPUT_SCALAR_TYPES,
    NODE_GRAPH_COORDINATE_LIMIT,
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphNodeType,
    GraphScalarType,
)
from polybot_control_plane.catalog.graphs.contracts import (
    MAX_INPUT_CONNECTIONS_PER_HANDLE,
    MAX_NODE_GRAPH_EDGES,
    MAX_NODE_GRAPH_NODES,
    MIN_NODE_GRAPH_NODES,
    NO_INPUT_CONNECTIONS,
    EXPECTED_TRIGGER_BRANCH_COUNT,
)
from polybot_control_plane.catalog.graphs.catalog import GRAPH_NODE_CATALOG


FRONTEND_CATALOG_CONTRACT_PATH = (
    Path(__file__).parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "catalog"
    / "catalogContract.fixture.json"
)


def frontend_catalog_contract() -> dict[str, object]:
    return {
        "graphTemplate": {
            "maximumNameLength": GRAPH_TEMPLATE_NAME_MAX_LENGTH,
        },
        "widgetSchemaKey": WIDGET_SCHEMA_KEY,
        "graphFieldPathSeparator": GRAPH_FIELD_PATH_SEPARATOR,
        "graphFieldPathSegmentPattern": GRAPH_FIELD_PATH_SEGMENT_PATTERN,
        "graphBrokerSubmitMethodName": GRAPH_BROKER_SUBMIT_METHOD_NAME,
        "nodeGraph": {
            "coordinateLimit": NODE_GRAPH_COORDINATE_LIMIT,
            "hookNamePattern": GRAPH_HOOK_NAME_PATTERN,
            "maximumEdgeIdentifierLength": MAX_GRAPH_EDGE_IDENTIFIER_LENGTH,
            "maximumEdges": MAX_NODE_GRAPH_EDGES,
            "maximumIdentifierLength": MAX_GRAPH_IDENTIFIER_LENGTH,
            "maximumInputConnectionsPerHandle": MAX_INPUT_CONNECTIONS_PER_HANDLE,
            "maximumNodes": MAX_NODE_GRAPH_NODES,
            "minimumNodes": MIN_NODE_GRAPH_NODES,
            "minimumIdentifierLength": MIN_GRAPH_IDENTIFIER_LENGTH,
            "minimumFieldPathSegments": MIN_GRAPH_FIELD_PATH_SEGMENTS,
            "minimumInputScalarTypes": MIN_GRAPH_INPUT_SCALAR_TYPES,
            "noInputConnections": NO_INPUT_CONNECTIONS,
            "requiredTriggerBranchCount": EXPECTED_TRIGGER_BRANCH_COUNT,
        },
        "graphNodeCatalog": GRAPH_NODE_CATALOG.model_dump(mode="json"),
        "graphNodeType": {kind.name: kind.value for kind in GraphNodeType},
        "graphBrokerAction": {
            action.name: action.value for action in GraphBrokerAction
        },
        "graphComparisonOperator": {
            operator.name: operator.value for operator in GraphComparisonOperator
        },
        "graphScalarType": {
            scalar_type.name: scalar_type.value for scalar_type in GraphScalarType
        },
        "botDefinitionLabel": {
            label.name: label.value for label in BotDefinitionLabel
        },
        "selectionMode": {mode.name: mode.value for mode in SelectionMode},
        "widgetKind": {kind.name: kind.value for kind in WidgetKind},
    }


def write_frontend_catalog_contract() -> None:
    FRONTEND_CATALOG_CONTRACT_PATH.write_text(
        json.dumps(frontend_catalog_contract(), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_frontend_catalog_contract()
