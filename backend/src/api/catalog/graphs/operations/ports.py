from typing import Literal

from api.catalog.graphs.ports import (
    GraphInputDescriptor,
    GraphOutputDescriptor,
)
from api.catalog.graphs.values import (
    GraphPort,
    GraphScalarType,
)

NONNEGATIVE_INPUT_MINIMUM = "0"


def input_port(
    handle_id: str,
    *scalar_types: GraphScalarType | Literal[GraphPort.CONTEXT],
    required: bool = True,
    whole_number: bool = False,
    minimum: str | None = None,
    maximum: str | None = None,
    description: str | None = None,
) -> GraphInputDescriptor:
    return GraphInputDescriptor(
        handle_id=handle_id,
        display_name=handle_id.replace("_", " ").title(),
        scalar_types=scalar_types,
        nullable=True,
        required=required,
        whole_number=whole_number,
        minimum=minimum,
        maximum=maximum,
        description=description,
    )


def output_port(
    handle_id: str, scalar_type: GraphScalarType | Literal[GraphPort.CONTEXT]
) -> GraphOutputDescriptor:
    return GraphOutputDescriptor(
        handle_id=handle_id,
        display_name=handle_id.replace("_", " ").title(),
        scalar_type=scalar_type,
        nullable=True,
    )
