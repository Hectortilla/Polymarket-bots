from api.catalog.graphs.values import (
    GRAPH_CONTEXT_PORT_TYPE,
    GraphOperation,
    GraphPort,
    GraphScalarType,
)

from .descriptor import GraphOperationDescriptor
from .ports import input_port


def diagnostics_descriptors() -> tuple[GraphOperationDescriptor, ...]:
    all_scalar_types = tuple(GraphScalarType)
    context_input_descriptor = input_port(GraphPort.CONTEXT, GRAPH_CONTEXT_PORT_TYPE)
    descriptors: list[GraphOperationDescriptor] = []
    for op in (GraphOperation.INSPECT, GraphOperation.LOG):
        descriptors.append(
            GraphOperationDescriptor.create(
                op,
                "Diagnostics",
                (
                    context_input_descriptor,
                    input_port(GraphPort.VALUE, *all_scalar_types),
                ),
                (),
                terminal=True,
            )
        )
    return tuple(descriptors)
