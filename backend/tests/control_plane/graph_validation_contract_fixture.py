"""Generate cross-runtime graph-validation parity cases from the Python owner."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from pydantic import ValidationError

from control_plane.graph_fixtures import threshold_buy_graph
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.graphs.examples import GRAPH_EXAMPLES
from api.catalog.graphs.values import (
    GraphNodeType,
    GraphOperation,
    GraphScalarType,
)


FRONTEND_GRAPH_VALIDATION_CONTRACT_PATH = (
    Path(__file__).parents[3]
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
        node for node in incompatible_edge["nodes"] if node["id"] == "constant-size"
    )
    size["data"] = {"scalar_type": "boolean", "value": True}

    orphan_processing_node = deepcopy(valid)
    orphan_processing_node["nodes"] = [
        node for node in orphan_processing_node["nodes"] if node["id"] != "action-buy"
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
        *_mvp_cases(),
    )


def _mvp_cases() -> list[tuple[str, dict[str, object]]]:
    examples = [
        (example.name, example.graph.model_dump(mode="json"))
        for example in GRAPH_EXAMPLES
    ]
    cases = list(examples)
    for name, amount in (
        ("exact large Number", "9007199254740993.000000000000000001"),
        ("nonfinite Number", "NaN"),
        ("unsupported exponent", "1e1001"),
        ("invalid Number separator", "1_000"),
        ("signed fractional Number", "+.5"),
        ("zero exponent normalization", "0e10000"),
    ):
        graph = deepcopy(examples[0][1])
        graph["parameters"][0]["data"]["value"] = amount
        cases.append((name, graph))
    unknown_parameter = deepcopy(examples[0][1])
    unknown_parameter["parameters"] = []
    cases.append(("missing parameter reference", unknown_parameter))
    duplicate_inputs = deepcopy(examples[1][1])
    next(n for n in duplicate_inputs["nodes"] if n["id"] == "conditions")["data"][
        "input_ids"
    ] = ["input_1", "input_1", "input_3"]
    cases.append(("duplicate expandable port", duplicate_inputs))
    diagnostics = dict(
        nodes=[
            dict(
                id="first",
                type=GraphNodeType.TRIGGER,
                position=dict(x=0, y=0),
                data=dict(hook_name="on_start"),
            ),
            dict(
                id="second",
                type=GraphNodeType.TRIGGER,
                position=dict(x=0, y=1),
                data=dict(hook_name="on_stop"),
            ),
            dict(
                id="shared",
                type=GraphNodeType.PARAMETER,
                position=dict(x=1, y=0),
                data=dict(parameter_id="amount"),
            ),
            *[
                dict(
                    id=name,
                    type=GraphNodeType.OPERATION,
                    position=dict(x=2, y=index),
                    data=dict(operation=GraphOperation.INSPECT),
                )
                for index, name in enumerate(("inspect-first", "inspect-second"))
            ],
        ],
        edges=[],
        parameters=[
            dict(
                id="amount",
                name="Amount",
                data=dict(scalar_type=GraphScalarType.NUMBER, value="2.0"),
            )
        ],
    )
    for trigger in ("first", "second"):
        for source, handle in ((trigger, "context"), ("shared", "value")):
            diagnostics["edges"].append(
                dict(
                    id=f"{source}-{trigger}",
                    source=source,
                    source_handle=handle,
                    target=f"inspect-{trigger}",
                    target_handle=handle,
                )
            )
    cases.append(("shared parameter across diagnostic-only branches", diagnostics))
    invalid_context = deepcopy(diagnostics)
    invalid_context["edges"][0]["source"] = "shared"
    invalid_context["edges"][0]["source_handle"] = "value"
    cases.append(("Number is not Context", invalid_context))
    cross_trigger = deepcopy(diagnostics)
    cross_trigger["nodes"][2] = dict(
        id="shared",
        type=GraphNodeType.OPERATION,
        position=dict(x=1, y=0),
        data=dict(operation=GraphOperation.ADD),
    )
    cross_trigger["nodes"].append(
        dict(
            id="constant",
            type=GraphNodeType.CONSTANT,
            position=dict(x=0, y=0),
            data=dict(scalar_type=GraphScalarType.NUMBER, value="2"),
        )
    )
    for handle in ("left", "right"):
        cross_trigger["edges"].append(
            dict(
                id=handle,
                source="constant",
                source_handle="value",
                target="shared",
                target_handle=handle,
            )
        )
    cases.append(("processing cannot join triggers", cross_trigger))
    cycle = deepcopy(examples[0][1])
    next(e for e in cycle["edges"] if e["target"] == "flat")["source"] = "enter"
    next(e for e in cycle["edges"] if e["target"] == "flat")["source_handle"] = "result"
    cases.append(("MVP processing cycle", cycle))
    return cases


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
