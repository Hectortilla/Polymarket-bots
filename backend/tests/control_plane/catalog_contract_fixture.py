"""Generate frontend runtime constants from the backend catalog contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from api.catalog.graphs.catalog import GRAPH_NODE_CATALOG
from api.catalog.graphs.contracts.limits import (
    EXPECTED_TRIGGER_BRANCH_COUNT,
    MAX_GRAPH_PARAMETERS,
    MAX_INPUT_CONNECTIONS_PER_HANDLE,
    MAX_NODE_GRAPH_EDGES,
    MAX_NODE_GRAPH_NODES,
    MAX_PARAMETER_NAME_LENGTH,
    MIN_NODE_GRAPH_NODES,
    NO_INPUT_CONNECTIONS,
)
from api.catalog.graphs.evaluation_reasons import GraphEvaluationReason
from api.catalog.graphs.numbers import (
    GRAPH_NUMBER_PATTERN,
    MAX_NUMBER_EXPONENT,
    MAX_NUMBER_TEXT_LENGTH,
)
from api.catalog.graphs.operations import MAX_BOOLEAN_INPUTS
from api.catalog.graphs.preview_samples import DEFAULT_PREVIEW_CASH
from api.catalog.graphs.value_status import GraphValueStatus
from api.catalog.graphs.values import (
    DEFAULT_OPERATION_SCALAR_TYPE,
    GRAPH_BROKER_SUBMIT_METHOD_NAME,
    GRAPH_CONTEXT_PORT_TYPE,
    GRAPH_FIELD_PATH_SEGMENT_PATTERN,
    GRAPH_FIELD_PATH_SEPARATOR,
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
    GraphPort,
    GraphScalarType,
)
from api.catalog.values import (
    WIDGET_SCHEMA_KEY,
    BotDefinitionLabel,
    SelectionMode,
    WidgetKind,
)
from api.http.market_contracts import (
    DEFAULT_MARKET_SEARCH_LIMIT,
    MAX_MARKET_SEARCH_LENGTH,
    MAX_MARKET_SEARCH_LIMIT,
    MIN_MARKET_SEARCH_LENGTH,
)
from api.market_selection import MAX_SELECTED_MARKETS

FRONTEND_CATALOG_CONTRACT_PATH = (
    Path(__file__).parents[3]
    / "frontend"
    / "src"
    / "lib"
    / "catalog"
    / "catalogContract.fixture.json"
)


def frontend_catalog_contract() -> dict[str, object]:
    return {
        "graphPort": {port.name: port.value for port in GraphPort},
        "graphEvaluationReasons": sorted(
            {
                reason.value
                for reason_type in get_args(GraphEvaluationReason.__value__)
                for reason in reason_type
            }
        ),
        "graphValueStatus": {status.name: status.value for status in GraphValueStatus},
        "maximumBooleanInputs": MAX_BOOLEAN_INPUTS,
        "maximumNumberTextLength": MAX_NUMBER_TEXT_LENGTH,
        "maximumNumberExponent": MAX_NUMBER_EXPONENT,
        "numberPattern": GRAPH_NUMBER_PATTERN,
        "contextPortType": GRAPH_CONTEXT_PORT_TYPE,
        "maximumParameters": MAX_GRAPH_PARAMETERS,
        "maximumParameterNameLength": MAX_PARAMETER_NAME_LENGTH,
        "marketSearch": {
            "minimumQueryLength": MIN_MARKET_SEARCH_LENGTH,
            "maximumQueryLength": MAX_MARKET_SEARCH_LENGTH,
            "defaultLimit": DEFAULT_MARKET_SEARCH_LIMIT,
            "maximumLimit": MAX_MARKET_SEARCH_LIMIT,
            "maximumSelections": MAX_SELECTED_MARKETS,
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
        "defaultPreviewCash": str(DEFAULT_PREVIEW_CASH),
        "defaultOperationScalarType": DEFAULT_OPERATION_SCALAR_TYPE,
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
        "botDefinitionLabel": {label.name: label.value for label in BotDefinitionLabel},
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
