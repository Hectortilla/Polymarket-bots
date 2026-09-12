"""Deterministic event-by-event execution of validated paper strategy graphs."""

import asyncio
from dataclasses import replace
from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest

from api.catalog.graphs.catalog import GRAPH_NODE_CATALOG
from api.catalog.graphs.comparisons import compare_non_null_values
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.graphs.contracts.nodes.actions import GraphBrokerActionNode
from api.catalog.graphs.contracts.nodes.comparisons import GraphComparisonNode
from api.catalog.graphs.contracts.nodes.constants import GraphConstantNode
from api.catalog.graphs.contracts.nodes.operations import GraphOperationNode
from api.catalog.graphs.contracts.nodes.parameters import GraphParameterNode
from api.catalog.graphs.contracts.nodes.triggers import GraphTriggerNode
from api.catalog.graphs.evaluation_reasons import GraphActionSkipReason
from api.catalog.graphs.reasons import GraphReason
from api.catalog.graphs.results import GraphNodeEvaluationRead, GraphValueRead
from api.catalog.graphs.types import GraphHookName
from api.catalog.graphs.value_status import GraphValueStatus
from api.catalog.graphs.values import (
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GRAPH_CONTEXT_HANDLE_ID,
    GRAPH_VALUE_HANDLE_ID,
    GraphComparisonOperator,
    GraphOperation,
    GraphPort,
)
from api.catalog.node_based.evaluator.actions import (
    GraphActionResolver,
)
from api.catalog.node_based.evaluator.capabilities import (
    DIAGNOSTIC_OPERATIONS,
    EVENT_CONTROL_OPERATIONS,
    PORTFOLIO_OPERATIONS,
    PURE_OPERATIONS,
)
from api.catalog.node_based.evaluator.compiler import CompiledGraph
from api.catalog.node_based.evaluator.context_operations import portfolio_outputs
from api.catalog.node_based.evaluator.contracts import (
    EvaluationFrame,
    GraphActionResult,
    GraphEvaluationResult,
)
from api.catalog.node_based.evaluator.diagnostics import (
    GraphDiagnostics,
)
from api.catalog.node_based.evaluator.eligibility import (
    event_skip_reason,
)
from api.catalog.node_based.evaluator.event_controls import EventControlState
from api.catalog.node_based.evaluator.pure import evaluate_pure
from api.catalog.node_based.evaluator.values import RuntimeValue


class GraphEvaluator:
    def __init__(self, graph: NodeGraph, *, preview: bool = False) -> None:
        self._compiled_graph = CompiledGraph.from_graph(graph)
        self._preview = preview
        self._state = EventControlState()
        self._diagnostics = GraphDiagnostics()
        self._lock = asyncio.Lock()

    async def evaluate_and_execute(
        self, hook_name: GraphHookName, ctx: BotContext, payload: object | None = None
    ) -> GraphEvaluationResult:
        if not any(
            trigger.hook_name == hook_name for trigger in GRAPH_NODE_CATALOG.triggers
        ):
            raise ValueError(f"Unknown graph hook: {hook_name}")
        async with self._lock:
            return await self._evaluate(hook_name, ctx, payload)

    async def _evaluate(
        self, hook_name: GraphHookName, ctx: BotContext, payload: object | None
    ) -> GraphEvaluationResult:
        branch = self._compiled_graph.branches.get(hook_name, ())
        frame = EvaluationFrame(ctx, payload)
        if (
            any(
                isinstance(node, GraphOperationNode)
                and node.data.operation in PORTFOLIO_OPERATIONS
                for node in branch
            )
            and ctx.portfolio is not None
        ):
            frame.portfolio = ctx.portfolio.snapshot()
        reads: list[GraphNodeEvaluationRead] = []
        intended: list[OrderRequest] = []
        for node in branch:
            if isinstance(node, GraphTriggerNode):
                outputs = {
                    edge.source_handle: RuntimeValue.from_value(
                        ctx
                        if edge.source_handle == GRAPH_CONTEXT_HANDLE_ID
                        else frame.resolve_payload_value(edge.source_handle)
                    )
                    for edge in self._compiled_graph.outgoing.get(node.id, ())
                }
            elif isinstance(node, (GraphConstantNode, GraphParameterNode)):
                outputs = {
                    GRAPH_VALUE_HANDLE_ID: RuntimeValue.from_value(
                        self._compiled_graph.constant_values[node.id]
                    )
                }
            elif isinstance(node, GraphComparisonNode):
                left, right = (
                    self._input(node.id, GraphPort.LEFT, frame),
                    self._input(node.id, GraphPort.RIGHT, frame),
                )
                result = _comparison_result(node.data.operator, left, right)
                outputs = {GRAPH_COMPARISON_RESULT_HANDLE_ID: result}
            elif isinstance(node, GraphOperationNode):
                outputs = await self._operation(node, frame)
            elif isinstance(node, GraphBrokerActionNode):
                outputs = await self._action(node, frame, intended)
            else:
                raise AssertionError(f"Unsupported compiled node: {node}")
            for output_handle_id, result in outputs.items():
                frame.values[node.id, output_handle_id] = result
            frame.evaluated_node_ids.append(node.id)
            unavailable = next(
                (value for value in outputs.values() if not value.available), None
            )
            status = unavailable.status if unavailable else GraphValueStatus.AVAILABLE
            reason = unavailable.reason if unavailable else None
            if isinstance(node, GraphBrokerActionNode):
                action_status = outputs[GraphPort.STATUS].value
                status = (
                    GraphValueStatus(action_status)
                    if action_status
                    in (GraphValueStatus.SKIPPED, GraphValueStatus.PLANNED)
                    else GraphValueStatus.AVAILABLE
                )
                reason = (
                    outputs[GraphPort.SKIP_REASON].value
                    or outputs[GraphPort.REJECT_REASON].value
                )
            reads.append(
                GraphNodeEvaluationRead(
                    node_id=node.id,
                    outputs={
                        output_handle_id: _read_value(value)
                        for output_handle_id, value in outputs.items()
                    },
                    status=status,
                    reason=reason,
                )
            )
        return GraphEvaluationResult(
            tuple(frame.evaluated_node_ids),
            tuple(frame.action_results),
            tuple(reads),
            tuple(intended),
        )

    async def _operation(
        self, node: GraphOperationNode, frame: EvaluationFrame
    ) -> dict[str, RuntimeValue]:
        inputs = {
            port.handle_id: self._input(node.id, port.handle_id, frame)
            for port in node.inputs()
            if port.required
            or port.handle_id in self._compiled_graph.incoming.get(node.id, {})
        }
        operation = node.data.operation
        if operation in PURE_OPERATIONS:
            return {node.outputs()[0].handle_id: evaluate_pure(operation, inputs)}
        if operation in PORTFOLIO_OPERATIONS:
            return portfolio_outputs(operation, inputs, frame.portfolio)
        if operation is GraphOperation.RANDOM_NUMBER:
            issue = event_skip_reason(frame.ctx, frame.payload)
            unavailable = next(
                (value for value in inputs.values() if not value.available), None
            )
            if issue:
                result = RuntimeValue.skipped(issue)
            elif unavailable is not None:
                result = unavailable
            elif inputs[GraphPort.ENABLED].value is not True:
                result = RuntimeValue.skipped(GraphReason.DISABLED)
            else:
                result = RuntimeValue(Decimal(str(frame.ctx.rng.random())))
            return {GraphPort.VALUE: result}
        if operation in EVENT_CONTROL_OPERATIONS:
            issue = event_skip_reason(frame.ctx, frame.payload)
            result = (
                RuntimeValue.skipped(issue)
                if issue
                else self._state.evaluate(
                    node.id, operation, inputs, frame.ctx.clock.now_ms()
                )
            )
            return {node.outputs()[0].handle_id: result}
        if operation in DIAGNOSTIC_OPERATIONS:
            value = inputs[GraphPort.VALUE]
            await self._diagnostics.emit(
                frame.ctx,
                node.id,
                _diagnostic_message(value),
            )
            # Diagnostic values appear in traces but are not connectable outputs.
            return {"inspected": value}
        raise AssertionError(f"Unsupported operation: {operation}")

    async def _action(
        self,
        node: GraphBrokerActionNode,
        frame: EvaluationFrame,
        intended: list[OrderRequest],
    ) -> dict[str, RuntimeValue]:
        issue = event_skip_reason(frame.ctx, frame.payload)
        enabled = self._input(node.id, GraphPort.ENABLED, frame)
        if issue is not None:
            result = GraphActionResult(
                node.id,
                skip_reason=(
                    GraphActionSkipReason(issue)
                    if issue in GraphActionSkipReason
                    else issue
                ),
            )
        elif not enabled.available:
            result = GraphActionResult(
                node.id,
                skip_reason=enabled.reason
                or GraphActionSkipReason.REQUIRED_INPUT_UNAVAILABLE,
            )
        else:
            decision = GraphActionResolver(
                node,
                self._compiled_graph.action_descriptors[node.id],
                lambda input_handle_id: self._available_input(
                    node.id, input_handle_id, frame
                ),
            ).resolve()
            if isinstance(decision, GraphActionResult):
                result = decision
            elif self._preview:
                intended.append(decision.order)
                result = GraphActionResult(node.id, skip_reason=GraphReason.PLANNED)
                frame.action_results.append(result)
                return _action_outputs(result)
            else:
                try:
                    fill = await frame.ctx.broker.submit(decision.order)
                except Exception as error:
                    await self._diagnostics.emit(
                        frame.ctx,
                        node.id,
                        f"Execution failed: {type(error).__name__}: {error}",
                    )
                    raise
                result = GraphActionResult(node.id, fill=fill)
        frame.action_results.append(result)
        fill = result.fill
        if result.skip_reason is not None:
            await self._diagnostics.emit(
                frame.ctx, node.id, f"Skipped: {result.skip_reason}"
            )
        elif fill is not None and fill.reject_reason is not None:
            await self._diagnostics.emit(
                frame.ctx, node.id, f"Rejected: {fill.reject_reason}"
            )
        return _action_outputs(result)

    def _input(
        self, node_id: str, handle_id: str, frame: EvaluationFrame
    ) -> RuntimeValue:
        source = self._compiled_graph.incoming.get(node_id, {}).get(handle_id)
        return RuntimeValue.from_value(None) if source is None else frame.values[source]

    def _available_input(
        self, node_id: str, handle_id: str, frame: EvaluationFrame
    ) -> object | None:
        result = self._input(node_id, handle_id, frame)
        return result.value if result.available else None


def _read_value(value: RuntimeValue):
    if isinstance(value.value, BotContext):
        value = replace(value, value="Context")
    return GraphValueRead.from_runtime(value)


def _comparison_result(
    operator: GraphComparisonOperator, left: RuntimeValue, right: RuntimeValue
) -> RuntimeValue:
    if not left.available:
        return left
    if not right.available:
        return right
    return RuntimeValue(compare_non_null_values(operator, left.value, right.value))


def _diagnostic_message(value: RuntimeValue) -> str:
    displayed = value.value if value.available else value.status.value
    return f"{displayed}: {value.reason or ''}".rstrip(": ")


def _action_outputs(result: GraphActionResult) -> dict[str, RuntimeValue]:
    if result.skip_reason is GraphReason.PLANNED:
        return {
            GraphPort.STATUS: RuntimeValue(GraphValueStatus.PLANNED.value),
            GraphPort.FILLED_SIZE: RuntimeValue(
                None, GraphValueStatus.PLANNED, GraphReason.PLANNED
            ),
            GraphPort.AVERAGE_PRICE: RuntimeValue(
                None, GraphValueStatus.PLANNED, GraphReason.PLANNED
            ),
            GraphPort.SKIP_REASON: RuntimeValue.from_value(None),
            GraphPort.REJECT_REASON: RuntimeValue.from_value(None),
        }
    fill = result.fill
    return {
        GraphPort.STATUS: RuntimeValue(
            fill.status.value if fill is not None else GraphValueStatus.SKIPPED.value
        ),
        GraphPort.FILLED_SIZE: RuntimeValue.from_value(
            fill.filled_size if fill is not None else None
        ),
        GraphPort.AVERAGE_PRICE: RuntimeValue.from_value(
            fill.average_price if fill is not None else None
        ),
        GraphPort.SKIP_REASON: RuntimeValue.from_value(result.skip_reason),
        GraphPort.REJECT_REASON: RuntimeValue.from_value(
            fill.reject_reason if fill is not None else None
        ),
    }
