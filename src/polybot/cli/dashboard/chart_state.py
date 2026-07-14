"""Chart sampling and time-window state transitions."""

from __future__ import annotations

from collections import deque
from math import isnan, nan
from time import time
from typing import TYPE_CHECKING

from .layout import chart_panel_width

if TYPE_CHECKING:
    from .state import DashboardState

MAX_CHART_HISTORY_POINTS = 720
MIN_CHART_WINDOW_POINTS = 12
MAX_CHART_WINDOW_POINTS = 120
MIN_TIME_ZOOM_LEVEL = -3
MAX_TIME_ZOOM_LEVEL = 3


def record_sample(state: DashboardState, now_ms: int | None = None) -> None:
    state.chart_sample_times.append(time() if now_ms is None else now_ms / 1000)
    trim(state.chart_sample_times, MAX_CHART_HISTORY_POINTS)
    for token_id in state.chart_tokens:
        history = state.price_history[token_id]
        stale_history = state.price_stale_history[token_id]
        marker_history = state.trade_marker_history[token_id]
        resolved_price = state.resolved_prices.get(token_id)
        book = state._current_book(token_id, now_ms)
        midpoint = None if book is None else book.midpoint()
        if resolved_price is not None:
            value = float(resolved_price)
            is_stale = True
        elif midpoint is not None:
            value = float(midpoint)
            is_stale = False
        elif book is None:
            value = last_chart_value(history)
            is_stale = value is not None
        else:
            value = None
            is_stale = False
        history.append(nan if value is None else value)
        stale_history.append(is_stale)
        marker_history.append(tuple(state.pending_trade_markers.pop(token_id, ())))
        trim(history, MAX_CHART_HISTORY_POINTS)
        trim(stale_history, MAX_CHART_HISTORY_POINTS)
        trim(marker_history, MAX_CHART_HISTORY_POINTS)
    wallet_value = state.executable_equity(now_ms)
    if wallet_value is not None:
        value = float(wallet_value)
        is_stale = False
    else:
        value = last_chart_value(state.wallet_value_history)
        is_stale = value is not None
    state.wallet_value_history.append(nan if value is None else value)
    state.wallet_value_stale_history.append(is_stale)
    trim(state.wallet_value_history, MAX_CHART_HISTORY_POINTS)
    trim(state.wallet_value_stale_history, MAX_CHART_HISTORY_POINTS)


def chart_window_points(time_zoom_level: int, width: int) -> int:
    base_points = chart_display_points(width)
    if time_zoom_level < 0:
        return max(
            MIN_CHART_WINDOW_POINTS,
            base_points // (2 ** (-time_zoom_level)),
        )
    return min(MAX_CHART_HISTORY_POINTS, base_points * (2**time_zoom_level))


def chart_display_points(width: int) -> int:
    return max(
        MIN_CHART_WINDOW_POINTS,
        min(MAX_CHART_WINDOW_POINTS, chart_panel_width(width) - 12),
    )


def visible_time_range(
    sample_times: deque[float], time_zoom_level: int, width: int
) -> tuple[float, float] | None:
    timestamps = list(sample_times)[-chart_window_points(time_zoom_level, width) :]
    if not timestamps:
        return None
    return timestamps[0], timestamps[-1]


def trim(values: deque[object], limit: int) -> None:
    while len(values) > limit:
        values.popleft()


def last_chart_value(values: deque[float]) -> float | None:
    return next((value for value in reversed(values) if not isnan(value)), None)
