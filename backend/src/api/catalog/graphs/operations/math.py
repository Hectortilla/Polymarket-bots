from api.catalog.graphs.numbers import MAX_ROUND_DECIMAL_PLACES
from api.catalog.graphs.values import (
    GRAPH_CONTEXT_PORT_TYPE,
    GraphOperation,
    GraphPort,
    GraphScalarType,
)

from .descriptor import GraphOperationDescriptor
from .ports import NONNEGATIVE_INPUT_MINIMUM, input_port, output_port


def math_descriptors() -> tuple[GraphOperationDescriptor, ...]:
    number = GraphScalarType.NUMBER
    boolean = GraphScalarType.BOOLEAN
    context_input_descriptor = input_port(GraphPort.CONTEXT, GRAPH_CONTEXT_PORT_TYPE)
    value_output_descriptors = (output_port(GraphPort.VALUE, number),)
    descriptors: list[GraphOperationDescriptor] = []
    for op in (
        GraphOperation.ADD,
        GraphOperation.SUBTRACT,
        GraphOperation.MULTIPLY,
        GraphOperation.DIVIDE,
        GraphOperation.MIN,
        GraphOperation.MAX,
    ):
        descriptors.append(
            GraphOperationDescriptor.create(
                op,
                "Math",
                (
                    input_port(GraphPort.LEFT, number),
                    input_port(GraphPort.RIGHT, number),
                ),
                value_output_descriptors,
            )
        )
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.CLAMP,
            "Math",
            tuple(
                (
                    input_port(input_handle_id, number)
                    for input_handle_id in (
                        GraphPort.VALUE,
                        GraphPort.MINIMUM,
                        GraphPort.MAXIMUM,
                    )
                )
            ),
            value_output_descriptors,
        )
    )
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.ROUND,
            "Math",
            (
                input_port(GraphPort.VALUE, number),
                input_port(
                    GraphPort.PLACES,
                    number,
                    whole_number=True,
                    minimum=NONNEGATIVE_INPUT_MINIMUM,
                    maximum=str(MAX_ROUND_DECIMAL_PLACES),
                    description="Nonnegative decimal places; ties round away from zero.",
                ),
            ),
            value_output_descriptors,
        )
    )
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.RANDOM_NUMBER,
            "Math",
            (
                context_input_descriptor,
                input_port(
                    GraphPort.ENABLED,
                    boolean,
                    description="Draw once when enabled: 0 inclusive to 1 exclusive. Uses the run random source.",
                ),
            ),
            value_output_descriptors,
        )
    )
    return tuple(descriptors)
