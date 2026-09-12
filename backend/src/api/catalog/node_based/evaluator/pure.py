"""Pure scalar operations with numeric preconditions checked before formulas."""

from decimal import Decimal, DecimalException, localcontext

from api.catalog.graphs.numbers import (
    GRAPH_NUMBER_CONTEXT,
    GRAPH_ROUND_MODE,
    MAX_ROUND_DECIMAL_PLACES,
    whole_number,
)
from api.catalog.graphs.reasons import GraphReason
from api.catalog.graphs.value_status import GraphValueStatus
from api.catalog.graphs.values import GraphOperation, GraphPort
from api.catalog.node_based.evaluator.values import RuntimeValue

from .arithmetic import BINARY_ARITHMETIC


def evaluate_pure(
    operation: GraphOperation, inputs: dict[str, RuntimeValue]
) -> RuntimeValue:
    if operation is GraphOperation.IS_PRESENT:
        value = inputs[GraphPort.VALUE]
        if value.status is GraphValueStatus.MISSING:
            return RuntimeValue(False)
        return RuntimeValue(True) if value.available else value
    if operation is GraphOperation.SELECT:
        return _select_value(inputs)
    unavailable = next(
        (value for value in inputs.values() if not value.available), None
    )
    if unavailable is not None:
        return unavailable
    values = {input_handle_id: value.value for input_handle_id, value in inputs.items()}
    issue = _numeric_precondition(operation, values)
    if issue is not None:
        return issue
    try:
        with localcontext(GRAPH_NUMBER_CONTEXT):
            return RuntimeValue.from_value(_calculate(operation, values))
    except DecimalException:
        return RuntimeValue.invalid(GraphReason.INVALID_NUMBER)


def _numeric_precondition(
    operation: GraphOperation, values: dict
) -> RuntimeValue | None:
    if operation is GraphOperation.DIVIDE and values[GraphPort.RIGHT] == 0:
        return RuntimeValue.invalid(
            GraphReason.DIVISION_BY_ZERO,
            input_handle_id=GraphPort.RIGHT,
            message="Divisor must be nonzero.",
        )
    if (
        operation in (GraphOperation.BETWEEN, GraphOperation.CLAMP)
        and values[GraphPort.MINIMUM] > values[GraphPort.MAXIMUM]
    ):
        return RuntimeValue.invalid(
            GraphReason.INVALID_BOUNDS,
            input_handle_id=GraphPort.MINIMUM,
            message="Minimum cannot exceed maximum.",
        )
    if operation is GraphOperation.ROUND:
        try:
            places = whole_number(values[GraphPort.PLACES], "Decimal places")
        except ValueError as error:
            return RuntimeValue.invalid(
                GraphReason.WHOLE_NUMBER_REQUIRED,
                input_handle_id=GraphPort.PLACES,
                message=str(error),
            )
        if places > MAX_ROUND_DECIMAL_PLACES:
            return RuntimeValue.invalid(
                GraphReason.INVALID_NUMBER,
                input_handle_id=GraphPort.PLACES,
                message=f"Decimal places must be at most {MAX_ROUND_DECIMAL_PLACES}.",
            )
    return None


def _calculate(operation: GraphOperation, values: dict) -> object:
    if operation in BINARY_ARITHMETIC:
        return BINARY_ARITHMETIC[operation](
            values[GraphPort.LEFT], values[GraphPort.RIGHT]
        )
    if operation is GraphOperation.AND:
        return all(values.values())
    if operation is GraphOperation.OR:
        return any(values.values())
    if operation is GraphOperation.NOT:
        return not values[GraphPort.VALUE]
    if operation is GraphOperation.BETWEEN:
        return (
            values[GraphPort.MINIMUM]
            <= values[GraphPort.VALUE]
            <= values[GraphPort.MAXIMUM]
        )
    if operation is GraphOperation.CLAMP:
        return min(
            max(values[GraphPort.VALUE], values[GraphPort.MINIMUM]),
            values[GraphPort.MAXIMUM],
        )
    if operation is GraphOperation.ROUND:
        return values[GraphPort.VALUE].quantize(
            Decimal(1).scaleb(-int(values[GraphPort.PLACES])), rounding=GRAPH_ROUND_MODE
        )
    raise AssertionError(f"Missing pure operation: {operation}")


def _select_value(inputs: dict[str, RuntimeValue]) -> RuntimeValue:
    condition = inputs[GraphPort.CONDITION]
    if not condition.available:
        return condition
    if condition.value is True:
        return inputs[GraphPort.WHEN_TRUE]
    return inputs[GraphPort.WHEN_FALSE]
