"""Evaluation results and per-event state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from polybot.framework.events.book_validation import BookValidationIssue
from polybot.framework.events.wallet_trades import WalletTradeValidationIssue
from polybot_control_plane.catalog.graphs.types import GraphFieldPath

if TYPE_CHECKING:
    from polybot.framework.context import BotContext
    from polybot.framework.events import FillEvent

type OutputKey = tuple[str, str]


class GraphActionSkipReason(StrEnum):
    DISABLED = "disabled"
    REQUIRED_INPUT_UNAVAILABLE = "required_input_unavailable"
    BOOK_GAP = "book_gap"
    BOOK_STALE = BookValidationIssue.STALE.value
    WALLET_TRADE_INVALID = WalletTradeValidationIssue.INVALID.value
    WALLET_TRADE_FUTURE_DATED = WalletTradeValidationIssue.FUTURE_DATED.value
    WALLET_TRADE_STALE = WalletTradeValidationIssue.STALE.value


@dataclass(frozen=True, slots=True)
class GraphActionResult:
    node_id: str
    fill: FillEvent | None = None
    skip_reason: GraphActionSkipReason | None = None
    missing_input_handle_id: str | None = None


@dataclass(frozen=True, slots=True)
class GraphEvaluationResult:
    evaluated_node_ids: tuple[str, ...]
    action_results: tuple[GraphActionResult, ...]


@dataclass(slots=True)
class EvaluationFrame:
    ctx: BotContext
    payload: object | None
    values: dict[OutputKey, object | None] = field(default_factory=dict)
    evaluated_node_ids: list[str] = field(default_factory=list)
    action_results: list[GraphActionResult] = field(default_factory=list)
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
