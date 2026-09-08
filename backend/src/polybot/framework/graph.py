"""Opt-in metadata for event values that are safe to expose to graphs."""

from collections.abc import Callable
from typing import Any, TypeVar


GRAPH_OUTPUT_MARKER = "__polybot_graph_output__"
GraphOutputFunctionT = TypeVar("GraphOutputFunctionT", bound=Callable[..., Any])


def graph_output(function: GraphOutputFunctionT) -> GraphOutputFunctionT:
    """Mark one computed event property as a graph-safe output."""
    setattr(function, GRAPH_OUTPUT_MARKER, True)
    return function


def is_graph_output(value: object) -> bool:
    return isinstance(value, property) and bool(
        value.fget and getattr(value.fget, GRAPH_OUTPUT_MARKER, False)
    )
