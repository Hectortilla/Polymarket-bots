"""Code-owned operations and their discoverable graph ports."""

from typing import Literal
from pydantic import BaseModel, ConfigDict
from polybot_control_plane.catalog.graphs.numbers import MAX_ROUND_DECIMAL_PLACES
from polybot_control_plane.catalog.graphs.ports import (
    GraphInputDescriptor,
    GraphOutputDescriptor,
)
from polybot_control_plane.catalog.graphs.values import (
    GraphPort,
    GraphOperation,
    GraphScalarType,
    GraphNodeType,
    GRAPH_CONTEXT_PORT_TYPE,
)

DEFAULT_BOOLEAN_INPUT_IDS = ("input_1", "input_2")
MIN_BOOLEAN_INPUTS = len(DEFAULT_BOOLEAN_INPUT_IDS)
MAX_BOOLEAN_INPUTS = 16


class GraphOperationDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_type: Literal[GraphNodeType.OPERATION] = GraphNodeType.OPERATION
    operation: GraphOperation
    display_name: str
    category: str
    inputs: tuple[GraphInputDescriptor, ...]
    outputs: tuple[GraphOutputDescriptor, ...]
    expandable: bool = False
    terminal: bool = False
    selectable_scalar_type: bool = False
    minimum_inputs: int | None = None
    maximum_inputs: int | None = None


def input_port(
    name: str,
    *types: GraphScalarType | Literal[GraphPort.CONTEXT],
    required: bool = True,
    whole_number: bool = False,
    minimum: str | None = None,
    maximum: str | None = None,
    description: str | None = None,
) -> GraphInputDescriptor:
    return GraphInputDescriptor(
        handle_id=name,
        display_name=name.replace("_", " ").title(),
        scalar_types=types,
        nullable=True,
        required=required,
        whole_number=whole_number,
        minimum=minimum,
        maximum=maximum,
        description=description,
    )


def output_port(
    name: str, kind: GraphScalarType | Literal[GraphPort.CONTEXT]
) -> GraphOutputDescriptor:
    return GraphOutputDescriptor(
        handle_id=name,
        display_name=name.replace("_", " ").title(),
        scalar_type=kind,
        nullable=True,
    )


def operation_descriptors() -> tuple[GraphOperationDescriptor, ...]:
    number, boolean, string = (
        GraphScalarType.NUMBER,
        GraphScalarType.BOOLEAN,
        GraphScalarType.STRING,
    )
    scalar = tuple(GraphScalarType)
    context = input_port(GraphPort.CONTEXT, GRAPH_CONTEXT_PORT_TYPE)
    result = (output_port(GraphPort.RESULT, boolean),)
    value = (output_port(GraphPort.VALUE, number),)
    descriptors: list[GraphOperationDescriptor] = []

    def add(
        op: GraphOperation,
        category: str,
        inputs: tuple,
        outputs: tuple,
        **options: bool | int,
    ) -> None:
        descriptors.append(
            GraphOperationDescriptor(
                operation=op,
                display_name={
                    GraphOperation.AND: "AND",
                    GraphOperation.OR: "OR",
                    GraphOperation.NOT: "NOT",
                    GraphOperation.SELECT: "Select Value",
                    GraphOperation.ONCE: "Once Per Key",
                    GraphOperation.DEDUPLICATE: "Deduplicate Event",
                    GraphOperation.BALANCE: "Available Balance",
                    GraphOperation.INSPECT: "Inspect Value",
                    GraphOperation.LOG: "Log / Explain Decision",
                }.get(op, op.value.replace("_", " ").title()),
                category=category,
                inputs=inputs,
                outputs=outputs,
                **options,
            )
        )

    for op in (GraphOperation.AND, GraphOperation.OR):
        add(
            op,
            "Logic",
            tuple(input_port(name, boolean) for name in DEFAULT_BOOLEAN_INPUT_IDS),
            result,
            expandable=True,
            minimum_inputs=MIN_BOOLEAN_INPUTS,
            maximum_inputs=MAX_BOOLEAN_INPUTS,
        )
    add(GraphOperation.NOT, "Logic", (input_port(GraphPort.VALUE, boolean),), result)
    add(
        GraphOperation.IS_PRESENT,
        "Logic",
        (input_port(GraphPort.VALUE, *scalar),),
        result,
    )
    add(
        GraphOperation.BETWEEN,
        "Logic",
        tuple(
            input_port(name, number)
            for name in (GraphPort.VALUE, GraphPort.MINIMUM, GraphPort.MAXIMUM)
        ),
        result,
    )
    add(
        GraphOperation.SELECT,
        "Logic",
        (
            input_port(GraphPort.CONDITION, boolean),
            input_port(GraphPort.WHEN_TRUE, *scalar),
            input_port(GraphPort.WHEN_FALSE, *scalar),
        ),
        (output_port(GraphPort.VALUE, number),),
        selectable_scalar_type=True,
    )
    for op in (
        GraphOperation.ADD,
        GraphOperation.SUBTRACT,
        GraphOperation.MULTIPLY,
        GraphOperation.DIVIDE,
        GraphOperation.MIN,
        GraphOperation.MAX,
    ):
        add(
            op,
            "Math",
            (input_port(GraphPort.LEFT, number), input_port(GraphPort.RIGHT, number)),
            value,
        )
    add(
        GraphOperation.CLAMP,
        "Math",
        tuple(
            input_port(name, number)
            for name in (GraphPort.VALUE, GraphPort.MINIMUM, GraphPort.MAXIMUM)
        ),
        value,
    )
    add(
        GraphOperation.ROUND,
        "Math",
        (
            input_port(GraphPort.VALUE, number),
            input_port(
                GraphPort.PLACES,
                number,
                whole_number=True,
                minimum="0",
                maximum=str(MAX_ROUND_DECIMAL_PLACES),
                description="Nonnegative decimal places; ties round away from zero.",
            ),
        ),
        value,
    )
    for op in (
        GraphOperation.COOLDOWN,
        GraphOperation.ONCE,
        GraphOperation.DEDUPLICATE,
    ):
        inputs = (
            context,
            input_port(GraphPort.ENABLED, boolean),
            input_port(GraphPort.KEY, string),
        )
        if op is GraphOperation.COOLDOWN:
            inputs += (
                input_port(
                    GraphPort.DURATION_MS,
                    number,
                    whole_number=True,
                    minimum="0",
                    description="Nonnegative cooldown duration in milliseconds.",
                ),
            )
        if op is GraphOperation.ONCE:
            inputs += (input_port(GraphPort.RESET, boolean, required=False),)
        add(op, "Event controls", inputs, result)
    add(
        GraphOperation.POSITION,
        "Portfolio",
        (context, input_port(GraphPort.TOKEN_ID, string)),
        (
            output_port(GraphPort.SIZE, number),
            output_port(GraphPort.HAS_POSITION, boolean),
            output_port(GraphPort.AVERAGE_ENTRY_PRICE, number),
        ),
    )
    add(
        GraphOperation.BALANCE,
        "Portfolio",
        (context,),
        (output_port(GraphPort.AVAILABLE_CASH, number),),
    )
    for op in (GraphOperation.INSPECT, GraphOperation.LOG):
        add(
            op,
            "Diagnostics",
            (context, input_port(GraphPort.VALUE, *scalar)),
            (),
            terminal=True,
        )
    return tuple(descriptors)


OPERATION_DESCRIPTORS = {item.operation: item for item in operation_descriptors()}
