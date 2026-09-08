"""Shared graph input and output descriptions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.catalog.graphs.types import GraphHandleId
from api.catalog.graphs.values import (
    GRAPH_CONTEXT_PORT_TYPE,
    MIN_GRAPH_INPUT_SCALAR_TYPES,
    GraphScalarType,
)


class GraphOutputDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    handle_id: GraphHandleId
    display_name: str
    scalar_type: GraphScalarType | Literal[GRAPH_CONTEXT_PORT_TYPE]
    nullable: bool = False


class GraphInputDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    handle_id: GraphHandleId
    display_name: str
    scalar_types: tuple[GraphScalarType | Literal[GRAPH_CONTEXT_PORT_TYPE], ...] = (
        Field(min_length=MIN_GRAPH_INPUT_SCALAR_TYPES)
    )
    nullable: bool
    required: bool
    whole_number: bool = False
    minimum: str | None = None
    maximum: str | None = None
    description: str | None = None
