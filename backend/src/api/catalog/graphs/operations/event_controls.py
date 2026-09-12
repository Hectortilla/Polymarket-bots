from api.catalog.graphs.values import (
    GRAPH_CONTEXT_PORT_TYPE,
    GraphOperation,
    GraphPort,
    GraphScalarType,
)

from .descriptor import GraphOperationDescriptor
from .ports import NONNEGATIVE_INPUT_MINIMUM, input_port, output_port


def event_controls_descriptors() -> tuple[GraphOperationDescriptor, ...]:
    number = GraphScalarType.NUMBER
    boolean = GraphScalarType.BOOLEAN
    string = GraphScalarType.STRING
    context_input_descriptor = input_port(GraphPort.CONTEXT, GRAPH_CONTEXT_PORT_TYPE)
    result_output_descriptors = (output_port(GraphPort.RESULT, boolean),)
    descriptors: list[GraphOperationDescriptor] = []
    for op in (
        GraphOperation.COOLDOWN,
        GraphOperation.ONCE,
        GraphOperation.DEDUPLICATE,
    ):
        inputs = (
            context_input_descriptor,
            input_port(GraphPort.ENABLED, boolean),
            input_port(GraphPort.KEY, string),
        )
        if op is GraphOperation.COOLDOWN:
            inputs += (
                input_port(
                    GraphPort.DURATION_MS,
                    number,
                    whole_number=True,
                    minimum=NONNEGATIVE_INPUT_MINIMUM,
                    description="Nonnegative cooldown duration in milliseconds.",
                ),
            )
        if op is GraphOperation.ONCE:
            inputs += (input_port(GraphPort.RESET, boolean, required=False),)
        descriptors.append(
            GraphOperationDescriptor.create(
                op, "Event controls", inputs, result_output_descriptors
            )
        )
    return tuple(descriptors)
