"""One-pass evaluation of validated node graphs."""

from polybot.framework.context import BotContext
from polybot.framework.events.books import BookGapEvent, BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot_control_plane.catalog.graphs.comparisons import compare_non_null_values
from polybot_control_plane.catalog.graphs.contracts import (
    GraphBrokerActionNode,
    GraphComparisonNode,
    GraphConstantNode,
    GraphTriggerNode,
    NodeGraph,
)
from polybot_control_plane.catalog.graphs.values import (
    GRAPH_COMPARISON_LEFT_HANDLE_ID,
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GRAPH_COMPARISON_RIGHT_HANDLE_ID,
    GRAPH_VALUE_HANDLE_ID,
)
from polybot_control_plane.catalog.graphs.types import GraphHookName
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


class GraphEvaluator:
    """Compile a validated graph once and evaluate one matching branch per event."""

    def __init__(self, graph: NodeGraph) -> None:
        self._compiled_graph = CompiledGraph.from_graph(graph)

    async def evaluate_and_execute(
        self,
        hook_name: GraphHookName,
        ctx: BotContext,
        payload: object | None = None,
    ) -> GraphEvaluationResult:
        branch = self._compiled_graph.branches.get(hook_name)
        if branch is None:
            return GraphEvaluationResult((), ())

        frame = EvaluationFrame(ctx, payload)
        for node in branch:
            if isinstance(node, GraphTriggerNode):
                self._evaluate_trigger(node, frame)
            elif isinstance(node, GraphConstantNode):
                frame.values[(node.id, GRAPH_VALUE_HANDLE_ID)] = (
                    self._compiled_graph.constant_values[node.id]
                )
            elif isinstance(node, GraphComparisonNode):
                self._evaluate_comparison(node, frame)
            elif isinstance(node, GraphBrokerActionNode):
                await self._execute_action(node, frame)
            frame.evaluated_node_ids.append(node.id)
        return GraphEvaluationResult(
            tuple(frame.evaluated_node_ids),
            tuple(frame.action_results),
        )

    def _evaluate_trigger(
        self,
        node: GraphTriggerNode,
        frame: EvaluationFrame,
    ) -> None:
        for edge in self._compiled_graph.outgoing.get(node.id, ()):
            key = node.id, edge.source_handle
            if key not in frame.values:
                frame.values[key] = frame.resolve_payload_value(edge.source_handle)

    def _evaluate_comparison(
        self,
        node: GraphComparisonNode,
        frame: EvaluationFrame,
    ) -> None:
        left = self._input_value(node.id, GRAPH_COMPARISON_LEFT_HANDLE_ID, frame)
        right = self._input_value(node.id, GRAPH_COMPARISON_RIGHT_HANDLE_ID, frame)
        frame.values[(node.id, GRAPH_COMPARISON_RESULT_HANDLE_ID)] = (
            False
            if left is None or right is None
            else compare_non_null_values(node.data.operator, left, right)
        )

    async def _execute_action(
        self,
        node: GraphBrokerActionNode,
        frame: EvaluationFrame,
    ) -> None:
        event_skip_reason = self._event_skip_reason(frame)
        if event_skip_reason is not None:
            frame.action_results.append(
                GraphActionResult(node.id, skip_reason=event_skip_reason)
            )
            return
        decision = GraphActionResolver(
            node=node,
            descriptor=self._compiled_graph.action_descriptors[node.id],
            resolve_input_value=lambda handle_id: self._input_value(
                node.id,
                handle_id,
                frame,
            ),
        ).resolve()
        if isinstance(decision, GraphActionResult):
            frame.action_results.append(decision)
            return
        fill = await frame.ctx.broker.submit(decision.order)
        frame.action_results.append(GraphActionResult(node.id, fill=fill))

    @staticmethod
    def _event_skip_reason(
        frame: EvaluationFrame,
    ) -> GraphActionSkipReason | None:
        if isinstance(frame.payload, BookGapEvent):
            return GraphActionSkipReason.BOOK_GAP
        if isinstance(frame.payload, BookSnapshot) and not frame.ctx.is_book_current(
            frame.payload
        ):
            return GraphActionSkipReason.BOOK_STALE
        if isinstance(frame.payload, WalletTradeEvent):
            issue = frame.payload.freshness_issue(
                frame.ctx.clock.now_ms(),
                frame.ctx.config.event_max_age_ms,
            )
            if issue is not None:
                return GraphActionSkipReason(issue.value)
        return None

    def _input_value(
        self,
        node_id: str,
        handle_id: str,
        frame: EvaluationFrame,
    ) -> object | None:
        source = self._compiled_graph.incoming.get(node_id, {}).get(handle_id)
        return None if source is None else frame.values[source]
