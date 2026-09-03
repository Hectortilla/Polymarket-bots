"""Shared one-based bot graph-revision policy."""

from typing import Annotated

from pydantic import Field, StrictInt


FIRST_GRAPH_REVISION_NUMBER = 1

type GraphRevisionNumber = Annotated[
    StrictInt,
    Field(ge=FIRST_GRAPH_REVISION_NUMBER),
]


def next_graph_revision_number(latest_revision_number: int | None) -> int:
    if latest_revision_number is None:
        return FIRST_GRAPH_REVISION_NUMBER
    return latest_revision_number + 1
