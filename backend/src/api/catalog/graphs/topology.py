"""Shared indexes and branch analysis for validated directed graphs."""

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


class DirectedEdge(Protocol):
    source: str
    target: str


EdgeT = TypeVar("EdgeT", bound=DirectedEdge)


@dataclass(frozen=True, slots=True)
class GraphTopology(Generic[EdgeT]):
    topological_order: tuple[str, ...]
    incoming: dict[str, tuple[EdgeT, ...]]
    outgoing: dict[str, tuple[EdgeT, ...]]
    ancestor_ids: dict[str, frozenset[str]]
    descendant_ids: dict[str, frozenset[str]]

    @classmethod
    def from_edges(
        cls,
        node_ids: Iterable[str],
        edges: Iterable[EdgeT],
    ) -> "GraphTopology[EdgeT]":
        node_ids = tuple(node_ids)
        edges = tuple(edges)
        incoming_lists: dict[str, list[EdgeT]] = defaultdict(list)
        outgoing_lists: dict[str, list[EdgeT]] = defaultdict(list)
        for edge in edges:
            incoming_lists[edge.target].append(edge)
            outgoing_lists[edge.source].append(edge)
        incoming = {
            node_id: tuple(incoming_lists[node_id]) for node_id in node_ids
        }
        outgoing = {
            node_id: tuple(outgoing_lists[node_id]) for node_id in node_ids
        }
        ordered_node_ids = topological_order(
            node_ids,
            ((edge.source, edge.target) for edge in edges),
        )
        ancestor_ids: dict[str, frozenset[str]] = {}
        for node_id in ordered_node_ids:
            ancestor_ids[node_id] = frozenset({node_id}).union(
                *(ancestor_ids[edge.source] for edge in incoming[node_id])
            )
        descendant_ids: dict[str, frozenset[str]] = {}
        for node_id in reversed(ordered_node_ids):
            descendant_ids[node_id] = frozenset({node_id}).union(
                *(descendant_ids[edge.target] for edge in outgoing[node_id])
            )
        return cls(
            ordered_node_ids,
            incoming,
            outgoing,
            ancestor_ids,
            descendant_ids,
        )

    def branch_node_ids(self, trigger_id: str) -> frozenset[str]:
        descendants = self.descendant_ids[trigger_id]
        # Constants and other prerequisites can feed a downstream branch without
        # themselves being reachable in the trigger's forward traversal.
        return frozenset().union(
            *(self.ancestor_ids[node_id] for node_id in descendants)
        )


def topological_order(
    node_ids: Iterable[str],
    edges: Iterable[tuple[str, str]],
) -> tuple[str, ...]:
    node_ids = tuple(node_ids)
    incoming_count = dict.fromkeys(node_ids, 0)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        incoming_count[target] += 1
        outgoing[source].append(target)

    ready = deque(node_id for node_id in node_ids if incoming_count[node_id] == 0)
    ordered: list[str] = []
    while ready:
        node_id = ready.popleft()
        ordered.append(node_id)
        for target in outgoing[node_id]:
            incoming_count[target] -= 1
            if incoming_count[target] == 0:
                ready.append(target)

    if len(ordered) != len(node_ids):
        raise ValueError("graph must be acyclic")
    return tuple(ordered)
