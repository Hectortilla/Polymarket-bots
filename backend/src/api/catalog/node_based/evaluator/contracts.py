"""Evaluation results and per-event state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from polybot.framework.portfolio import PortfolioSnapshot

from api.catalog.graphs.evaluation_reasons import GraphEvaluationReason
from api.catalog.graphs.results import GraphNodeEvaluationRead
from api.catalog.graphs.types import GraphFieldPath
from api.catalog.node_based.evaluator.values import RuntimeValue

if TYPE_CHECKING:
    from polybot.framework.context import BotContext
    from polybot.framework.events import FillEvent, OrderRequest

type OutputKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class GraphActionResult:
    node_id: str
    fill: FillEvent | None = None
    skip_reason: GraphEvaluationReason | None = None
    missing_input_handle_id: str | None = None


@dataclass(frozen=True, slots=True)
class GraphEvaluationResult:
    evaluated_node_ids: tuple[str, ...]
    action_results: tuple[GraphActionResult, ...]
    nodes: tuple[GraphNodeEvaluationRead, ...] = ()
    intended_orders: tuple[OrderRequest, ...] = ()


@dataclass(slots=True)
class EvaluationFrame:
    ctx: BotContext
    payload: object | None
    values: dict[OutputKey, RuntimeValue] = field(default_factory=dict)
    evaluated_node_ids: list[str] = field(default_factory=list)
    action_results: list[GraphActionResult] = field(default_factory=list)
    portfolio: PortfolioSnapshot | None = None
    _payload_values: dict[tuple[str, ...], object | None] = field(default_factory=dict)

    def resolve_payload_value(self, handle_id: str) -> object | None:
        value = self.payload
        path: tuple[str, ...] = ()
        for segment in GraphFieldPath.segments_for_handle(handle_id):
            path += (segment,)
            if path in self._payload_values:
                value = self._payload_values[path]
            elif value is None:
                return None
            else:
                value = getattr(value, segment)
                self._payload_values[path] = value
        return value
