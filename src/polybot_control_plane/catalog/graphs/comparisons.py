"""Single specification for graph comparison typing and evaluation."""

import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from polybot_control_plane.catalog.graphs.values import (
    GraphComparisonOperator,
    GraphScalarType,
)

type Comparison = Callable[[Any, Any], bool]


@dataclass(frozen=True, slots=True)
class GraphComparisonSpec:
    scalar_types: tuple[GraphScalarType, ...]
    compare: Comparison


_ALL_SCALAR_TYPES = tuple(GraphScalarType)
_ORDERED_SCALAR_TYPES = (GraphScalarType.INTEGER, GraphScalarType.DECIMAL)

GRAPH_COMPARISON_SPECS: dict[GraphComparisonOperator, GraphComparisonSpec] = {
    GraphComparisonOperator.EQUAL: GraphComparisonSpec(_ALL_SCALAR_TYPES, operator.eq),
    GraphComparisonOperator.NOT_EQUAL: GraphComparisonSpec(
        _ALL_SCALAR_TYPES,
        operator.ne,
    ),
    GraphComparisonOperator.LESS_THAN: GraphComparisonSpec(
        _ORDERED_SCALAR_TYPES,
        operator.lt,
    ),
    GraphComparisonOperator.LESS_THAN_OR_EQUAL: GraphComparisonSpec(
        _ORDERED_SCALAR_TYPES,
        operator.le,
    ),
    GraphComparisonOperator.GREATER_THAN: GraphComparisonSpec(
        _ORDERED_SCALAR_TYPES,
        operator.gt,
    ),
    GraphComparisonOperator.GREATER_THAN_OR_EQUAL: GraphComparisonSpec(
        _ORDERED_SCALAR_TYPES,
        operator.ge,
    ),
}


def compare_non_null_values(
    comparison_operator: GraphComparisonOperator,
    left: object,
    right: object,
) -> bool:
    return GRAPH_COMPARISON_SPECS[comparison_operator].compare(left, right)
