"""Chart sampling and time-window state transitions."""

from __future__ import annotations

from collections import deque
from math import nan

from polybot.cli.dashboard.chart_contracts import (
    MAX_TERMINAL_CHART_POINTS,
    MIN_TERMINAL_CHART_POINTS,
)
from polybot.dashboard.contracts import (
    MAX_CHART_HISTORY_POINTS,
    MAX_TIME_ZOOM_LEVEL,
    MIN_TIME_ZOOM_LEVEL,
    scaled_chart_window_points,
)
from polybot.dashboard.history import last_chart_value, trim

from .layout import chart_panel_width

def chart_window_points(time_zoom_level: int, width: int) -> int:
    base_points = chart_display_points(width)
    return scaled_chart_window_points(
        base_points,
        time_zoom_level,
        MIN_TERMINAL_CHART_POINTS,
        MAX_CHART_HISTORY_POINTS,
    )


def chart_display_points(width: int) -> int:
    return max(
        MIN_TERMINAL_CHART_POINTS,
        min(MAX_TERMINAL_CHART_POINTS, chart_panel_width(width) - 12),
    )


def visible_epoch_seconds_range(
    sample_epoch_seconds: deque[float],
    time_zoom_level: int,
    width: int,
) -> tuple[float, float] | None:
    timestamps = list(sample_epoch_seconds)[
        -chart_window_points(time_zoom_level, width) :
    ]
    if not timestamps:
        return None
    return timestamps[0], timestamps[-1]
