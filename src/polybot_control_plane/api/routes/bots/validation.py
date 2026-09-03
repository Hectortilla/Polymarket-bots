"""Saved-bot HTTP validation and error translation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from polybot_control_plane.api.routes.graph_template_lookup import (
    require_graph_template,
)
from polybot_control_plane.catalog.definitions import (
    CATALOG,
    GraphRequirementError,
)
from polybot_control_plane.graph_templates.store import GraphTemplateStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from polybot_control_plane.bots.contracts import BotRead
    from polybot_control_plane.catalog.values import DefinitionId
    from polybot_control_plane.catalog.definitions import CatalogEntry
    from polybot_control_plane.catalog.graphs.contracts import NodeGraph
    from polybot_control_plane.runs.contracts import PaperRunConfig


BOT_NOT_FOUND_DETAIL = "bot not found"
DEFINITION_NOT_FOUND_DETAIL = "bot definition not found"
GRAPH_TEMPLATE_REQUIRED_DETAIL = "graph template is required for this bot definition"
GRAPH_TEMPLATE_FORBIDDEN_DETAIL = (
    "graph template is not accepted by this bot definition"
)
GRAPH_REVISION_REQUIRED_DETAIL = "bot graph revision is required"
GRAPH_REVISION_FORBIDDEN_DETAIL = "bot graph revision is not accepted"
REQUEST_BODY_LOCATION = "body"
BOT_INPUTS_FIELD = "inputs"


def require_catalog_entry(definition_id: DefinitionId) -> CatalogEntry:
    definition = CATALOG.get(definition_id)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DEFINITION_NOT_FOUND_DETAIL)
    return definition


def parse_config(
    definition: CatalogEntry,
    inputs: object,
    body: dict[str, object],
) -> PaperRunConfig:
    try:
        return definition.parse_config(inputs)
    except ValidationError as error:
        raise RequestValidationError(
            _input_validation_errors(error),
            body=body,
        ) from error


def _input_validation_errors(
    error: ValidationError,
) -> list[dict[str, object]]:
    return [
        {
            **issue,
            "loc": (REQUEST_BODY_LOCATION, BOT_INPUTS_FIELD, *issue["loc"]),
        }
        for issue in error.errors()
    ]


def require_bot(bot: BotRead | None) -> BotRead:
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOT_NOT_FOUND_DETAIL)
    return bot


async def resolve_bot_graph(
    session: AsyncSession,
    definition: CatalogEntry,
    template_id: UUID | None,
) -> NodeGraph | None:
    require_graph_contract(
        definition,
        template_id,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        required_detail=GRAPH_TEMPLATE_REQUIRED_DETAIL,
        forbidden_detail=GRAPH_TEMPLATE_FORBIDDEN_DETAIL,
    )
    if template_id is None:
        return None
    template = await GraphTemplateStore(session).read(template_id)
    return require_graph_template(template).graph


def require_run_revision_contract(definition: CatalogEntry, bot: BotRead) -> None:
    require_graph_contract(
        definition,
        bot.latest_graph_revision,
        status_code=status.HTTP_409_CONFLICT,
        required_detail=GRAPH_REVISION_REQUIRED_DETAIL,
        forbidden_detail=GRAPH_REVISION_FORBIDDEN_DETAIL,
    )


def require_graph_contract(
    definition: CatalogEntry,
    graph_value: object | None,
    *,
    status_code: int,
    required_detail: str,
    forbidden_detail: str,
) -> None:
    try:
        definition.require_graph_value(graph_value)
    except GraphRequirementError as error:
        detail = required_detail if error.graph_required else forbidden_detail
        raise HTTPException(status_code, detail) from error
