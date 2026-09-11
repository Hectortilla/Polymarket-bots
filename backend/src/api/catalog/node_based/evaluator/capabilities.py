"""Explicit runtime capability gate, checked before any hook can execute."""

from api.catalog.graphs.values import GraphOperation

from .arithmetic import BINARY_ARITHMETIC

PORTFOLIO_OPERATIONS = frozenset((GraphOperation.POSITION, GraphOperation.BALANCE))
DIAGNOSTIC_OPERATIONS = frozenset((GraphOperation.INSPECT, GraphOperation.LOG))
EVENT_CONTROL_OPERATIONS = frozenset(
    (GraphOperation.COOLDOWN, GraphOperation.ONCE, GraphOperation.DEDUPLICATE)
)
PURE_OPERATIONS = frozenset(
    (
        *BINARY_ARITHMETIC,
        GraphOperation.AND,
        GraphOperation.OR,
        GraphOperation.NOT,
        GraphOperation.IS_PRESENT,
        GraphOperation.SELECT,
        GraphOperation.BETWEEN,
        GraphOperation.CLAMP,
        GraphOperation.ROUND,
    )
)

EXECUTABLE_OPERATIONS: frozenset[GraphOperation] = (
    PURE_OPERATIONS
    | PORTFOLIO_OPERATIONS
    | DIAGNOSTIC_OPERATIONS
    | EVENT_CONTROL_OPERATIONS
    | {GraphOperation.RANDOM_NUMBER}
)


class UnsupportedGraphOperation(ValueError):
    pass
