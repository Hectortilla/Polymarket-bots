"""Broker-action resolution and order construction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from polybot.execution.order_validation import validate_order
from polybot.framework.events import OrderRequest

from api.catalog.graphs.evaluation_reasons import GraphActionSkipReason
from api.catalog.graphs.values import GRAPH_ACTION_ENABLED_HANDLE_ID
from api.catalog.node_based.evaluator.contracts import GraphActionResult

if TYPE_CHECKING:
    from api.catalog.graphs.catalog.functional import GraphBrokerActionDescriptor
    from api.catalog.graphs.contracts.nodes import GraphBrokerActionNode
    from api.catalog.graphs.ports import GraphInputDescriptor

type InputValueResolver = Callable[[str], object | None]


@dataclass(frozen=True, slots=True)
class _ActionInputs:
    descriptor: GraphBrokerActionDescriptor
    enabled: bool
    order_values: dict[str, Any]
    missing_required_input_handle_id: str | None


@dataclass(frozen=True, slots=True)
class ResolvedOrder:
    order: OrderRequest


type ActionDecision = ResolvedOrder | GraphActionResult


@dataclass(frozen=True, slots=True)
class GraphActionResolver:
    node: GraphBrokerActionNode
    descriptor: GraphBrokerActionDescriptor
    resolve_input_value: InputValueResolver

    def resolve(self) -> ActionDecision:
        inputs = self._resolve_inputs()
        if not inputs.enabled:
            return GraphActionResult(
                self.node.id,
                skip_reason=GraphActionSkipReason.DISABLED,
            )
        if inputs.missing_required_input_handle_id is not None:
            return GraphActionResult(
                self.node.id,
                skip_reason=GraphActionSkipReason.REQUIRED_INPUT_UNAVAILABLE,
                missing_input_handle_id=inputs.missing_required_input_handle_id,
            )
        order = OrderRequest(side=inputs.descriptor.side, **inputs.order_values)
        rejection = validate_order(order)
        if rejection is not None:
            return GraphActionResult(self.node.id, skip_reason=rejection[0])
        return ResolvedOrder(order)

    def _resolve_inputs(self) -> _ActionInputs:
        input_values = {
            input_.handle_id: self.resolve_input_value(input_.handle_id)
            for input_ in self.descriptor.inputs
        }
        enabled = input_values.pop(GRAPH_ACTION_ENABLED_HANDLE_ID) is True
        missing_handle_id = self._first_missing_required_input_handle_id(input_values)
        return _ActionInputs(
            self.descriptor,
            enabled,
            input_values,
            missing_handle_id,
        )

    def _first_missing_required_input_handle_id(
        self,
        input_values: dict[str, Any],
    ) -> str | None:
        return next(
            (
                input_.handle_id
                for input_ in self.descriptor.inputs
                if self._required_input_is_missing(input_, input_values)
            ),
            None,
        )

    @staticmethod
    def _required_input_is_missing(
        input_: GraphInputDescriptor,
        input_values: dict[str, Any],
    ) -> bool:
        return (
            input_.required
            and input_.handle_id != GRAPH_ACTION_ENABLED_HANDLE_ID
            and input_values[input_.handle_id] is None
        )
