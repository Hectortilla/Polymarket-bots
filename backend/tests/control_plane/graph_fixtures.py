from copy import deepcopy
import json
from pathlib import Path


THRESHOLD_BUY_GRAPH_PATH = (
    Path(__file__).parents[1] / "fixtures" / "control_plane" / "threshold_buy_graph.json"
)
THRESHOLD_BUY_GRAPH = json.loads(THRESHOLD_BUY_GRAPH_PATH.read_text())


def threshold_buy_graph() -> dict[str, object]:
    return deepcopy(THRESHOLD_BUY_GRAPH)
