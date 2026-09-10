"""Saved-bot HTTP validation and error translation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from api.catalog.definitions import (
    CATALOG,
    GraphRequirementError,
)

if TYPE_CHECKING:
    from api.bots.contracts import BotRead
    from api.catalog.definitions import CatalogEntry
    from api.catalog.graphs.contracts import NodeGraph
    from api.catalog.values import DefinitionId
    from api.runs.contracts import PaperRunConfig


BOT_NOT_FOUND_DETAIL = "bot not found"
DEFINITION_NOT_FOUND_DETAIL = "bot definition not found"
GRAPH_REQUIRED_DETAIL = "bot graph is required"
GRAPH_FORBIDDEN_DETAIL = "bot graph is not accepted"
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
    graph: NodeGraph | None,
    body: dict[str, object],
) -> PaperRunConfig:
    try:
        config = definition.parse_config(inputs)
    except ValidationError as error:
        raise RequestValidationError(
            _input_validation_errors(error),
            body=body,
        ) from error

    require_graph_contract(
        definition,
        graph,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        required_detail=GRAPH_REQUIRED_DETAIL,
        forbidden_detail=GRAPH_FORBIDDEN_DETAIL,
    )
    return config.model_copy(update={"graph": graph}, deep=True)


def require_bot(bot: BotRead | None) -> BotRead:
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BOT_NOT_FOUND_DETAIL)
    return bot


def require_run_graph_contract(definition: CatalogEntry, bot: BotRead) -> None:
    require_graph_contract(
        definition,
        bot.config.graph,
        status_code=status.HTTP_409_CONFLICT,
        required_detail=GRAPH_REQUIRED_DETAIL,
        forbidden_detail=GRAPH_FORBIDDEN_DETAIL,
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
