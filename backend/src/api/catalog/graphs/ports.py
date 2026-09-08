"""Shared graph input and output descriptions."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from api.catalog.graphs.types import GraphHandleId
from api.catalog.graphs.values import (
    GraphScalarType,
    MIN_GRAPH_INPUT_SCALAR_TYPES,
)


class GraphOutputDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    handle_id: GraphHandleId
    display_name: str
    scalar_type: GraphScalarType | Literal["context"]
    nullable: bool = False


class GraphInputDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    handle_id: GraphHandleId
    display_name: str
    scalar_types: tuple[GraphScalarType | Literal["context"], ...] = Field(
        min_length=MIN_GRAPH_INPUT_SCALAR_TYPES
    )
    nullable: bool
    required: bool
    whole_number: bool = False
    minimum: str | None = None
    maximum: str | None = None
    description: str | None = None
