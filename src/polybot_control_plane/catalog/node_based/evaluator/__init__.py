"""Deterministic event-by-event execution of validated paper strategy graphs."""

import asyncio
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest
from polybot_control_plane.catalog.graphs.comparisons import compare_non_null_values
from polybot_control_plane.catalog.graphs.contracts import (
    GraphBrokerActionNode,
    GraphComparisonNode,
    GraphConstantNode,
    GraphParameterNode,
    GraphOperationNode,
    GraphTriggerNode,
    NodeGraph,
)
from polybot_control_plane.catalog.graphs.results import (
    GraphNodeEvaluationRead,
    GraphReason,
    GraphValueStatus,
)
from polybot_control_plane.catalog.graphs.values import (
    GraphPort,
    GRAPH_CONTEXT_HANDLE_ID,
    GRAPH_VALUE_HANDLE_ID,
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GraphOperation,
)
from polybot_control_plane.catalog.node_based.evaluator.actions import (
    GraphActionResolver,
)
from polybot_control_plane.catalog.node_based.evaluator.compiler import CompiledGraph
from polybot_control_plane.catalog.node_based.evaluator.contracts import (
    EvaluationFrame,
    GraphActionResult,
    GraphActionSkipReason,
    GraphEvaluationResult,
)
from polybot_control_plane.catalog.node_based.evaluator.context_operations import (
    PORTFOLIO_OPERATIONS,
    DIAGNOSTIC_OPERATIONS,
    portfolio_outputs,
)
from polybot_control_plane.catalog.node_based.evaluator.diagnostics import (
    GraphDiagnostics,
)
from polybot_control_plane.catalog.node_based.evaluator.eligibility import (
    event_skip_reason,
)
from polybot_control_plane.catalog.node_based.evaluator.event_controls import (
    EVENT_CONTROL_OPERATIONS,
    EventControlState,
)
from polybot_control_plane.catalog.node_based.evaluator.pure import (
    PURE_OPERATIONS,
    evaluate_pure,
)
from polybot_control_plane.catalog.node_based.evaluator.values import RuntimeValue


class GraphEvaluator:
    def __init__(self, graph: NodeGraph, *, preview: bool = False) -> None:
        self._compiled_graph = CompiledGraph.from_graph(graph)
        self._preview = preview
        self._state = EventControlState()
        self._diagnostics = GraphDiagnostics()
        self._lock = asyncio.Lock()

    async def evaluate_and_execute(
        self, hook_name: str, ctx: BotContext, payload: object | None = None
    ) -> GraphEvaluationResult:
        async with self._lock:
            return await self._evaluate(hook_name, ctx, payload)

    async def _evaluate(
        self, hook_name: str, ctx: BotContext, payload: object | None
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
                left, right = self._input(node.id, GraphPort.LEFT, frame), self._input(
                    node.id, GraphPort.RIGHT, frame
                )
                result = (
                    left
                    if not left.available
                    else (
                        right
                        if not right.available
                        else RuntimeValue(
                            compare_non_null_values(
                                node.data.operator, left.value, right.value
                            )
                        )
                    )
                )
                outputs = {GRAPH_COMPARISON_RESULT_HANDLE_ID: result}
            elif isinstance(node, GraphOperationNode):
                outputs = await self._operation(node, frame)
            elif isinstance(node, GraphBrokerActionNode):
                outputs = await self._action(node, frame, intended)
            else:
                raise AssertionError(f"Unsupported compiled node: {node}")
            for name, result in outputs.items():
                frame.values[node.id, name] = result
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
                    outputs={name: value.read() for name, value in outputs.items()},
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
                f"{value.value if value.available else value.status.value}: {value.reason or ''}".rstrip(
                    ": "
                ),
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
                lambda name: self._available_input(node.id, name, frame),
            ).resolve()
            if isinstance(decision, GraphActionResult):
                result = decision
            elif self._preview:
                intended.append(decision.order)
                frame.action_results.append(
                    GraphActionResult(node.id, skip_reason=GraphReason.PLANNED)
                )
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
        return {
            GraphPort.STATUS: RuntimeValue(
                fill.status.value
                if fill is not None
                else GraphValueStatus.SKIPPED.value
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
