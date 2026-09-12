from api.catalog.graphs.values import (
    GraphOperation,
    GraphPort,
    GraphScalarType,
)

from .descriptor import GraphOperationDescriptor
from .ports import input_port, output_port

DEFAULT_BOOLEAN_INPUT_IDS = ("input_1", "input_2")
MIN_BOOLEAN_INPUTS = len(DEFAULT_BOOLEAN_INPUT_IDS)
MAX_BOOLEAN_INPUTS = 16


def logic_descriptors() -> tuple[GraphOperationDescriptor, ...]:
    number = GraphScalarType.NUMBER
    boolean = GraphScalarType.BOOLEAN
    all_scalar_types = tuple(GraphScalarType)
    result_output_descriptors = (output_port(GraphPort.RESULT, boolean),)
    descriptors: list[GraphOperationDescriptor] = []
    for op in (GraphOperation.AND, GraphOperation.OR):
        descriptors.append(
            GraphOperationDescriptor.create(
                op,
                "Logic",
                tuple(
                    (
                        input_port(input_handle_id, boolean)
                        for input_handle_id in DEFAULT_BOOLEAN_INPUT_IDS
                    )
                ),
                result_output_descriptors,
                expandable=True,
                minimum_inputs=MIN_BOOLEAN_INPUTS,
                maximum_inputs=MAX_BOOLEAN_INPUTS,
            )
        )
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.NOT,
            "Logic",
            (input_port(GraphPort.VALUE, boolean),),
            result_output_descriptors,
        )
    )
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.IS_PRESENT,
            "Logic",
            (input_port(GraphPort.VALUE, *all_scalar_types),),
            result_output_descriptors,
        )
    )
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.BETWEEN,
            "Logic",
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
            result_output_descriptors,
        )
    )
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.SELECT,
            "Logic",
            (
                input_port(GraphPort.CONDITION, boolean),
                input_port(GraphPort.WHEN_TRUE, *all_scalar_types),
                input_port(GraphPort.WHEN_FALSE, *all_scalar_types),
            ),
            (output_port(GraphPort.VALUE, number),),
            selectable_scalar_type=True,
        )
    )
    return tuple(descriptors)
