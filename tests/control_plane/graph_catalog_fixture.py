"""Generate the focused graph catalog used by frontend unit tests."""

from __future__ import annotations

import json
from pathlib import Path

from polybot_control_plane.catalog.graphs.catalog import (
    GRAPH_NODE_CATALOG,
    GraphNodeCatalog,
    GraphTriggerDescriptor,
)
from polybot_control_plane.catalog.graphs.types import GraphFieldPath


FRONTEND_FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "catalog"
    / "graphNodeCatalog.fixture.json"
)


def _trigger(
    hook_name: str,
    *field_paths: str,
) -> GraphTriggerDescriptor:
    trigger = GRAPH_NODE_CATALOG.trigger(hook_name)
    if trigger is None:
        raise ValueError(f"Unknown graph trigger: {hook_name}")
    if not field_paths:
        return trigger
    if trigger.payload is None:
        raise ValueError(f"Graph trigger has no payload: {hook_name}")

    fields = []
    for field_path in field_paths:
        field = trigger.payload.field_for_path(
            GraphFieldPath(segments=tuple(field_path.split(".")))
        )
        if field is None:
            raise ValueError(
                f"Unknown graph output field: {hook_name}.{field_path}"
            )
        fields.append(field)
    payload = trigger.payload.model_copy(update={"fields": tuple(fields)})
    return trigger.model_copy(update={"payload": payload})


def frontend_graph_catalog() -> dict[str, object]:
    catalog = GraphNodeCatalog(
        triggers=(
            _trigger("on_start"),
            _trigger("on_book", "bids", "asks", "token_id", "best_ask.price"),
            _trigger("on_wallet_trade", "size"),
        ),
        constants=GRAPH_NODE_CATALOG.constants,
        comparisons=GRAPH_NODE_CATALOG.comparisons,
        broker_actions=GRAPH_NODE_CATALOG.broker_actions,
    )
    return catalog.model_dump(mode="json")


def write_frontend_graph_catalog() -> None:
    FRONTEND_FIXTURE_PATH.write_text(
        json.dumps(frontend_graph_catalog(), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_frontend_graph_catalog()
