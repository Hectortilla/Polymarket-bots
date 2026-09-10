"""Explicit runtime capability gate, checked before any hook can execute."""

from api.catalog.graphs.values import GraphOperation
from api.catalog.node_based.evaluator.context_operations import (
    DIAGNOSTIC_OPERATIONS,
    PORTFOLIO_OPERATIONS,
)
from api.catalog.node_based.evaluator.event_controls import (
    EVENT_CONTROL_OPERATIONS,
)
from api.catalog.node_based.evaluator.pure import PURE_OPERATIONS

EXECUTABLE_OPERATIONS: frozenset[GraphOperation] = (
    PURE_OPERATIONS
    | PORTFOLIO_OPERATIONS
    | DIAGNOSTIC_OPERATIONS
    | EVENT_CONTROL_OPERATIONS
    | {GraphOperation.RANDOM_NUMBER}
)


class UnsupportedGraphOperation(ValueError):
    pass
