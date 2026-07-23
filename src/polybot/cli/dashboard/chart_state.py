"""Chart sampling and time-window state transitions."""

from __future__ import annotations

from collections import deque
from math import isfinite, nan

from polybot.cli.charting import (
    MAX_TERMINAL_CHART_POINTS,
    MIN_TERMINAL_CHART_POINTS,
)

from .layout import chart_panel_width

MAX_CHART_HISTORY_POINTS = 720
MIN_TIME_ZOOM_LEVEL = -3
MAX_TIME_ZOOM_LEVEL = 3


def chart_window_points(time_zoom_level: int, width: int) -> int:
    base_points = chart_display_points(width)
    if time_zoom_level < 0:
        return max(
            MIN_TERMINAL_CHART_POINTS,
            base_points // (2 ** (-time_zoom_level)),
        )
    return min(MAX_CHART_HISTORY_POINTS, base_points * (2**time_zoom_level))


def chart_display_points(width: int) -> int:
    return max(
        MIN_TERMINAL_CHART_POINTS,
        min(MAX_TERMINAL_CHART_POINTS, chart_panel_width(width) - 12),
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
    return next((value for value in reversed(values) if isfinite(value)), None)
