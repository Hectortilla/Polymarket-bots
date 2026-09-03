"""Broker-action resolution and order construction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from polybot.framework.events import OrderRequest
from polybot_control_plane.catalog.graphs.values import GRAPH_ACTION_ENABLED_HANDLE_ID
from polybot_control_plane.catalog.node_based.evaluator.contracts import (
    GraphActionResult,
    GraphActionSkipReason,
)

if TYPE_CHECKING:
    from polybot_control_plane.catalog.graphs.catalog import (
        GraphBrokerActionDescriptor,
        GraphInputDescriptor,
    )
    from polybot_control_plane.catalog.graphs.contracts import GraphBrokerActionNode

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
        return ResolvedOrder(
            OrderRequest(side=inputs.descriptor.side, **inputs.order_values)
        )

    def _resolve_inputs(self) -> _ActionInputs:
        input_values = {
            input_.handle_id: self.resolve_input_value(input_.handle_id)
            for input_ in self.descriptor.inputs
        }
        enabled = input_values.pop(GRAPH_ACTION_ENABLED_HANDLE_ID) is True
        missing_handle_id = self._first_missing_required_input_handle_id(
            input_values
        )
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
