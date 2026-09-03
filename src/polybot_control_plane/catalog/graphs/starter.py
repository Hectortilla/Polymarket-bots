"""Code-owned starter graph snapshot for node-based launches."""

from polybot.framework.base import BaseBot
from polybot_control_plane.catalog.graphs.contracts import (
    GraphPosition,
    GraphTriggerNode,
    GraphTriggerNodeData,
    NodeGraph,
)
from polybot_control_plane.catalog.graphs.values import GraphNodeType

STARTER_TRIGGER_HOOK_NAME = BaseBot.on_book.__name__
STARTER_TRIGGER_NODE_ID = "on-book-trigger"

STARTER_NODE_GRAPH = NodeGraph(
    nodes=(
        GraphTriggerNode(
            id=STARTER_TRIGGER_NODE_ID,
            type=GraphNodeType.TRIGGER,
            position=GraphPosition(x=80, y=80),
            data=GraphTriggerNodeData(hook_name=STARTER_TRIGGER_HOOK_NAME),
        ),
    ),
)
