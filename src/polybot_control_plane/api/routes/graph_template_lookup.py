"""Shared graph-template HTTP lookup contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from polybot_control_plane.graph_templates.contracts import GraphTemplateRead


GRAPH_TEMPLATE_NOT_FOUND_DETAIL = "graph template not found"


def require_graph_template(
    template: GraphTemplateRead | None,
) -> GraphTemplateRead:
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GRAPH_TEMPLATE_NOT_FOUND_DETAIL)
    return template
