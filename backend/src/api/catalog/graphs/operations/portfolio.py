from api.catalog.graphs.values import (
    GRAPH_CONTEXT_PORT_TYPE,
    GraphOperation,
    GraphPort,
    GraphScalarType,
)

from .descriptor import GraphOperationDescriptor
from .ports import input_port, output_port


def portfolio_descriptors() -> tuple[GraphOperationDescriptor, ...]:
    number = GraphScalarType.NUMBER
    boolean = GraphScalarType.BOOLEAN
    string = GraphScalarType.STRING
    context_input_descriptor = input_port(GraphPort.CONTEXT, GRAPH_CONTEXT_PORT_TYPE)
    descriptors: list[GraphOperationDescriptor] = []
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.POSITION,
            "Portfolio",
            (context_input_descriptor, input_port(GraphPort.TOKEN_ID, string)),
            (
                output_port(GraphPort.SIZE, number),
                output_port(GraphPort.HAS_POSITION, boolean),
                output_port(GraphPort.AVERAGE_ENTRY_PRICE, number),
            ),
        )
    )
    descriptors.append(
        GraphOperationDescriptor.create(
            GraphOperation.BALANCE,
            "Portfolio",
            (context_input_descriptor,),
            (output_port(GraphPort.AVAILABLE_CASH, number),),
        )
    )
    return tuple(descriptors)
