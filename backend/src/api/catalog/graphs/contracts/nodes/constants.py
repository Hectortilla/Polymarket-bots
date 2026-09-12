from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
)

from api.catalog.graphs.numbers import number_from_text
from api.catalog.graphs.types import (
    GraphElementId,
)
from api.catalog.graphs.values import (
    GraphNodeType,
    GraphScalarType,
)

from .position import GraphPosition


class GraphBooleanConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scalar_type: Literal[GraphScalarType.BOOLEAN]
    value: StrictBool


class GraphNumberConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scalar_type: Literal[GraphScalarType.NUMBER]
    value: StrictStr

    @field_validator("value")
    @classmethod
    def _validate_number(cls, value: str) -> str:
        number_from_text(value)
        return value


class GraphStringConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scalar_type: Literal[GraphScalarType.STRING]
    value: StrictStr


type GraphConstantNodeData = Annotated[
    GraphBooleanConstantData | GraphNumberConstantData | GraphStringConstantData,
    Field(discriminator="scalar_type"),
]


class GraphConstantNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.CONSTANT]
    position: GraphPosition
    data: GraphConstantNodeData

    def runtime_value(self) -> object:
        return (
            Decimal(self.data.value)
            if self.data.scalar_type is GraphScalarType.NUMBER
            else self.data.value
        )
