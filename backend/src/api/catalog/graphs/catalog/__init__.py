from __future__ import annotations

from typing import Any, Self

from polybot.framework.base import BaseBot
from polybot.framework.portfolio import PortfolioPosition
from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
)

from api.catalog.graphs._actions import (
    discover_broker_actions,
)
from api.catalog.graphs._triggers import (
    discover_graph_triggers,
)
from api.catalog.graphs._validation import (
    ensure_unique_graph_trigger_hooks,
    ensure_unique_values,
)
from api.catalog.graphs.catalog.functional import (
    GraphBrokerActionDescriptor,
    GraphComparisonDescriptor,
    GraphConstantDescriptor,
)
from api.catalog.graphs.catalog.triggers import GraphTriggerDescriptor
from api.catalog.graphs.operations import operation_descriptors
from api.catalog.graphs.operations.descriptor import GraphOperationDescriptor
from api.catalog.graphs.preview_samples import (
    PREVIEW_SAMPLE_POSITIONS,
)
from api.catalog.graphs.values import (
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphScalarType,
)


class GraphNodeCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_positions: tuple[PortfolioPosition, ...] = PREVIEW_SAMPLE_POSITIONS
    operations: tuple[GraphOperationDescriptor, ...] = ()
    triggers: tuple[GraphTriggerDescriptor, ...]
    constants: tuple[GraphConstantDescriptor, ...]
    comparisons: tuple[GraphComparisonDescriptor, ...]
    broker_actions: tuple[GraphBrokerActionDescriptor, ...]

    @model_validator(mode="after")
    def _validate_unique_entries(self) -> Self:
        ensure_unique_graph_trigger_hooks(
            tuple(trigger.hook_name for trigger in self.triggers),
        )
        ensure_unique_values(
            tuple(constant.scalar_type for constant in self.constants),
            "graph constant scalar type",
        )
        ensure_unique_values(
            tuple(comparison.operator for comparison in self.comparisons),
            "graph comparison operator",
        )
        ensure_unique_values(
            tuple(action.action for action in self.broker_actions),
            "graph broker action",
        )
        return self

    @classmethod
    def from_bot_type(cls, bot_type: type[Any]) -> Self:
        return cls(
            operations=operation_descriptors(),
            triggers=tuple(
                GraphTriggerDescriptor.from_discovered(trigger)
                for trigger in discover_graph_triggers(bot_type)
            ),
            constants=(
                GraphConstantDescriptor.from_scalar_type(
                    GraphScalarType.BOOLEAN,
                    False,
                ),
                GraphConstantDescriptor.from_scalar_type(
                    GraphScalarType.NUMBER,
                    "0",
                ),
                GraphConstantDescriptor.from_scalar_type(
                    GraphScalarType.STRING,
                    "",
                ),
            ),
            comparisons=tuple(
                GraphComparisonDescriptor.from_operator(operator)
                for operator in GraphComparisonOperator
            ),
            broker_actions=tuple(
                GraphBrokerActionDescriptor.from_discovered(action)
                for action in discover_broker_actions()
            ),
        )

    def trigger(self, hook_name: str) -> GraphTriggerDescriptor | None:
        return next(
            (trigger for trigger in self.triggers if trigger.hook_name == hook_name),
            None,
        )

    def constant(self, scalar_type: GraphScalarType) -> GraphConstantDescriptor:
        return next(item for item in self.constants if item.scalar_type is scalar_type)

    def comparison(
        self,
        operator: GraphComparisonOperator,
    ) -> GraphComparisonDescriptor:
        return next(item for item in self.comparisons if item.operator is operator)

    def broker_action(
        self,
        action: GraphBrokerAction,
    ) -> GraphBrokerActionDescriptor:
        return next(item for item in self.broker_actions if item.action is action)


GRAPH_NODE_CATALOG = GraphNodeCatalog.from_bot_type(BaseBot)
