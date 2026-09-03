"""Generate cross-runtime graph-validation parity cases from the Python owner."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from pydantic import ValidationError

from control_plane.graph_fixtures import threshold_buy_graph
from polybot_control_plane.catalog.graphs.contracts import NodeGraph


FRONTEND_GRAPH_VALIDATION_CONTRACT_PATH = (
    Path(__file__).parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "catalog"
    / "graphValidationContract.fixture.json"
)


def frontend_graph_validation_contract() -> dict[str, object]:
    cases = _graph_cases()
    return {
        "cases": [
            {
                "name": name,
                "graph": graph,
                "valid": _is_valid_node_graph(graph),
            }
            for name, graph in cases
        ]
    }


def _graph_cases() -> tuple[tuple[str, dict[str, object]], ...]:
    valid = threshold_buy_graph()

    missing_required_input = deepcopy(valid)
    missing_required_input["edges"] = missing_required_input["edges"][:-1]

    incompatible_edge = deepcopy(valid)
    size = next(
        node
        for node in incompatible_edge["nodes"]
        if node["id"] == "constant-size"
    )
    size["data"] = {"scalar_type": "boolean", "value": True}

    orphan_processing_node = deepcopy(valid)
    orphan_processing_node["nodes"] = [
        node
        for node in orphan_processing_node["nodes"]
        if node["id"] != "action-buy"
    ]
    orphan_processing_node["edges"] = [
        edge
        for edge in orphan_processing_node["edges"]
        if edge["target"] != "action-buy"
    ]

    return (
        ("valid threshold branch", valid),
        ("missing required input", missing_required_input),
        ("incompatible edge scalar", incompatible_edge),
        ("processing node without action", orphan_processing_node),
    )


def _is_valid_node_graph(graph: dict[str, object]) -> bool:
    try:
        NodeGraph.model_validate(graph)
    except ValidationError:
        return False
    return True


def write_frontend_graph_validation_contract() -> None:
    FRONTEND_GRAPH_VALIDATION_CONTRACT_PATH.write_text(
        json.dumps(frontend_graph_validation_contract(), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_frontend_graph_validation_contract()
