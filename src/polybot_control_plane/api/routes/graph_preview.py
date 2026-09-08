"""Isolated graph decision preview."""

from fastapi import APIRouter
from polybot_control_plane.api.routes.paths import (
    GRAPH_PREVIEW_PATH,
    PREVIEW_GRAPH_OPERATION_ID,
)
from polybot_control_plane.catalog.graphs.preview import (
    GraphPreviewRequest,
    GraphPreviewResponse,
)

from polybot_control_plane.catalog.node_based.preview import (
    preview_graph as evaluate_preview,
)

router = APIRouter()


@router.post(
    GRAPH_PREVIEW_PATH,
    response_model=GraphPreviewResponse,
    operation_id=PREVIEW_GRAPH_OPERATION_ID,
)
async def preview_graph(request: GraphPreviewRequest) -> GraphPreviewResponse:
    return await evaluate_preview(request)
