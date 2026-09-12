"""Assembly of the code-owned graph operation catalog."""

from .descriptor import GraphOperationDescriptor
from .diagnostics import diagnostics_descriptors
from .event_controls import event_controls_descriptors
from .logic import logic_descriptors
from .math import math_descriptors
from .portfolio import portfolio_descriptors


def operation_descriptors() -> tuple[GraphOperationDescriptor, ...]:
    return (
        *logic_descriptors(),
        *math_descriptors(),
        *event_controls_descriptors(),
        *portfolio_descriptors(),
        *diagnostics_descriptors(),
    )


OPERATION_DESCRIPTORS = {item.operation: item for item in operation_descriptors()}
