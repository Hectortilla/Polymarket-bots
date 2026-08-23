"""Bounded chart history shared by dashboard renderers."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from math import isfinite
from typing import TYPE_CHECKING

from .contracts import MAX_CHART_HISTORY_POINTS, MAX_CHART_TOKENS

if TYPE_CHECKING:
    from polybot.framework.events import Side
    from polybot.framework.events.books import BookSnapshot


@dataclass(slots=True)
class DashboardHistory:
    chart_tokens: deque[str] = field(default_factory=deque)
    price_history: dict[str, deque[float]] = field(default_factory=dict)
    price_stale_history: dict[str, deque[bool]] = field(default_factory=dict)
    trade_marker_history: dict[str, deque[tuple[Side, ...]]] = field(
        default_factory=dict
    )
    pending_trade_markers: dict[str, list[Side]] = field(default_factory=dict)
    executable_equity_history: deque[float] = field(default_factory=deque)
    executable_equity_stale_history: deque[bool] = field(default_factory=deque)
    chart_sample_epoch_seconds: deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        for token_id in self.chart_tokens:
            self._ensure_token_history(token_id)

    def activate_token(self, token_id: str) -> bool:
        if token_id not in self.chart_tokens:
            if len(self.chart_tokens) >= MAX_CHART_TOKENS:
                return False
            self.chart_tokens.append(token_id)
        self._ensure_token_history(token_id)
        return True

    def record_trade(self, token_id: str, side: Side) -> None:
        if self.activate_token(token_id):
            self.pending_trade_markers.setdefault(token_id, []).append(side)

    def remove_tokens(self, token_ids: Iterable[str]) -> None:
        for token_id in token_ids:
            self.price_history.pop(token_id, None)
            self.price_stale_history.pop(token_id, None)
            self.trade_marker_history.pop(token_id, None)
            self.pending_trade_markers.pop(token_id, None)
            try:
                self.chart_tokens.remove(token_id)
            except ValueError:
                pass

    def record_sample(
        self,
        sampled_at_ms: int,
        *,
        current_book: Callable[[str, int], BookSnapshot | None],
        executable_equity: Decimal | None,
    ) -> None:
        self.chart_sample_epoch_seconds.append(sampled_at_ms / 1_000)
        trim(self.chart_sample_epoch_seconds, MAX_CHART_HISTORY_POINTS)
        for token_id in self.chart_tokens:
            history, stale_history, marker_history = self._token_histories(token_id)
            book = current_book(token_id, sampled_at_ms)
            midpoint = None if book is None else book.midpoint()
            if midpoint is not None:
                value = float(midpoint)
                is_stale = False
            elif book is None:
                value = last_chart_value(history)
                is_stale = value is not None
            else:
                value = None
                is_stale = False
            history.append(float("nan") if value is None else value)
            stale_history.append(is_stale)
            marker_history.append(tuple(self.pending_trade_markers.pop(token_id, ())))
            trim(history, MAX_CHART_HISTORY_POINTS)
            trim(stale_history, MAX_CHART_HISTORY_POINTS)
            trim(marker_history, MAX_CHART_HISTORY_POINTS)
        self._record_executable_equity(executable_equity)

    def _record_executable_equity(self, executable_equity: Decimal | None) -> None:
        if executable_equity is not None:
            value = float(executable_equity)
            is_stale = False
        else:
            value = last_chart_value(self.executable_equity_history)
            is_stale = value is not None
        self.executable_equity_history.append(
            float("nan") if value is None else value
        )
        self.executable_equity_stale_history.append(is_stale)
        trim(self.executable_equity_history, MAX_CHART_HISTORY_POINTS)
        trim(self.executable_equity_stale_history, MAX_CHART_HISTORY_POINTS)

    def _token_histories(
        self, token_id: str
    ) -> tuple[deque[float], deque[bool], deque[tuple[Side, ...]]]:
        self._ensure_token_history(token_id)
        return (
            self.price_history[token_id],
            self.price_stale_history[token_id],
            self.trade_marker_history[token_id],
        )

    def _ensure_token_history(self, token_id: str) -> None:
        self.price_history.setdefault(token_id, deque())
        self.price_stale_history.setdefault(token_id, deque())
        self.trade_marker_history.setdefault(token_id, deque())


def trim(values: deque[object], limit: int) -> None:
    while len(values) > limit:
        values.popleft()


def last_chart_value(values: deque[float]) -> float | None:
    return next((value for value in reversed(values) if isfinite(value)), None)
