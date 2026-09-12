from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.catalog.graphs.ports import (
    GraphInputDescriptor,
    GraphOutputDescriptor,
)
from api.catalog.graphs.values import (
    GraphNodeType,
    GraphOperation,
)


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

    @classmethod
    def create(
        cls,
        op: GraphOperation,
        category: str,
        inputs: tuple[GraphInputDescriptor, ...],
        outputs: tuple[GraphOutputDescriptor, ...],
        **options: bool | int,
    ) -> "GraphOperationDescriptor":
        return cls(
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
