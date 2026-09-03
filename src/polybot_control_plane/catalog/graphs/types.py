"""Validated scalar types for graph catalogs and node contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from polybot_control_plane.catalog.graphs.values import (
    GRAPH_FIELD_HANDLE_PREFIX,
    GRAPH_FIELD_PATH_SEPARATOR,
    GRAPH_FIELD_PATH_SEGMENT_PATTERN,
    GRAPH_HOOK_NAME_PATTERN,
    MAX_GRAPH_EDGE_IDENTIFIER_LENGTH,
    MAX_GRAPH_IDENTIFIER_LENGTH,
    MIN_GRAPH_FIELD_PATH_SEGMENTS,
    MIN_GRAPH_IDENTIFIER_LENGTH,
    NODE_GRAPH_COORDINATE_LIMIT,
)

type GraphElementId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=MIN_GRAPH_IDENTIFIER_LENGTH,
        max_length=MAX_GRAPH_IDENTIFIER_LENGTH,
    ),
]
type GraphHandleId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=MIN_GRAPH_IDENTIFIER_LENGTH,
        max_length=MAX_GRAPH_IDENTIFIER_LENGTH,
    ),
]
type GraphEdgeId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=MIN_GRAPH_IDENTIFIER_LENGTH,
        max_length=MAX_GRAPH_EDGE_IDENTIFIER_LENGTH,
    ),
]
type GraphHookName = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        pattern=GRAPH_HOOK_NAME_PATTERN,
        max_length=MAX_GRAPH_IDENTIFIER_LENGTH,
    ),
]
type GraphFieldPathSegment = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=GRAPH_FIELD_PATH_SEGMENT_PATTERN,
        max_length=MAX_GRAPH_IDENTIFIER_LENGTH,
    ),
]
type GraphCoordinate = Annotated[
    float,
    Field(
        strict=True,
        allow_inf_nan=False,
        ge=-NODE_GRAPH_COORDINATE_LIMIT,
        le=NODE_GRAPH_COORDINATE_LIMIT,
    ),
]


class GraphFieldPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segments: tuple[GraphFieldPathSegment, ...] = Field(
        min_length=MIN_GRAPH_FIELD_PATH_SEGMENTS
    )

    @model_validator(mode="after")
    def _require_persistable_handle(self) -> "GraphFieldPath":
        if len(self.handle_id) > MAX_GRAPH_IDENTIFIER_LENGTH:
            raise ValueError("graph field handle exceeds the identifier limit")
        return self

    @property
    def dotted(self) -> str:
        return GRAPH_FIELD_PATH_SEPARATOR.join(self.segments)

    @property
    def handle_id(self) -> GraphHandleId:
        return f"{GRAPH_FIELD_HANDLE_PREFIX}{self.dotted}"

    @staticmethod
    def segments_for_handle(handle_id: str) -> tuple[str, ...]:
        return tuple(
            handle_id.removeprefix(GRAPH_FIELD_HANDLE_PREFIX).split(
                GRAPH_FIELD_PATH_SEPARATOR
            )
        )
