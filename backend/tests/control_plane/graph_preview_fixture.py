"""Generate a frontend preview fixture using the actual Python evaluator."""

import asyncio
import json
from pathlib import Path

from api.catalog.graphs.examples.entry_exit import entry_exit_example
from api.catalog.graphs.preview import GraphPreviewRequest
from api.catalog.graphs.preview_samples import (
    PREVIEW_SAMPLE_TIME_MS,
    sample_payload,
)
from api.catalog.node_based.preview import preview_graph


def preview_fixture() -> dict:
    request = GraphPreviewRequest(
        graph=entry_exit_example().graph,
        hook_name="on_book",
        payload=sample_payload("on_book"),
        now_ms=PREVIEW_SAMPLE_TIME_MS,
    )
    response = asyncio.run(preview_graph(request))
    return {
        "request": request.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
    }


if __name__ == "__main__":
    path = (
        Path(__file__).parents[3] / "frontend/src/lib/catalog/graphPreview.fixture.json"
    )
    path.write_text(json.dumps(preview_fixture(), indent=2) + "\n")
