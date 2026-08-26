"""Dependency-light public types for graph catalogs and node contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


MAX_GRAPH_IDENTIFIER_LENGTH = 64
NODE_GRAPH_COORDINATE_LIMIT = 10_000
GRAPH_ACTION_ENABLED_HANDLE_ID = "enabled"
GRAPH_BROKER_SUBMIT_METHOD_NAME = "submit"
GRAPH_CONTEXT_HANDLE_ID = "context"
GRAPH_CONTEXT_TYPE_NAME = "BotContext"
GRAPH_FIELD_HANDLE_PREFIX = "field:"
GRAPH_VALUE_HANDLE_ID = "value"
GRAPH_COMPARISON_LEFT_HANDLE_ID = "left"
GRAPH_COMPARISON_RIGHT_HANDLE_ID = "right"
GRAPH_COMPARISON_RESULT_HANDLE_ID = "result"
GRAPH_TRIGGER_HOOK_PREFIX = "on_"
GRAPH_HOOK_NAME_PATTERN = rf"^{GRAPH_TRIGGER_HOOK_PREFIX}[a-z][a-z0-9_]*$"

type GraphElementId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_GRAPH_IDENTIFIER_LENGTH,
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
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
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


class GraphNodeType(StrEnum):
    TRIGGER = "trigger"
    CONSTANT = "constant"
    COMPARISON = "comparison"
    BROKER_ACTION = "broker_action"


class GraphComparisonOperator(StrEnum):
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"


class GraphBrokerAction(StrEnum):
    SUBMIT_BUY = "submit_buy"
    SUBMIT_SELL = "submit_sell"

    @classmethod
    def from_method_and_side(
        cls,
        method_name: str,
        side_value: str,
    ) -> Self:
        return cls(f"{method_name}_{side_value.lower()}")


class GraphScalarType(StrEnum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    STRING = "string"


class GraphFieldPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segments: tuple[GraphFieldPathSegment, ...] = Field(min_length=1)

    @property
    def dotted(self) -> str:
        return ".".join(self.segments)

    @property
    def handle_id(self) -> str:
        return f"{GRAPH_FIELD_HANDLE_PREFIX}{self.dotted}"
