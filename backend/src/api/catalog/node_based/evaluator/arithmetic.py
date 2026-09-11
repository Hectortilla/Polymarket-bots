"""Dependency-light binary arithmetic operation table."""

import operator

from api.catalog.graphs.values import GraphOperation

BINARY_ARITHMETIC = {
    GraphOperation.ADD: operator.add,
    GraphOperation.SUBTRACT: operator.sub,
    GraphOperation.MULTIPLY: operator.mul,
    GraphOperation.DIVIDE: operator.truediv,
    GraphOperation.MIN: min,
    GraphOperation.MAX: max,
}
