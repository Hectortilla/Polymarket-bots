"""Chart sampling and time-window state transitions."""

from __future__ import annotations

from collections import deque
from math import nan

from polybot.cli.charting import (
    MAX_TERMINAL_CHART_POINTS,
    MIN_TERMINAL_CHART_POINTS,
)
from polybot.dashboard.contracts import MAX_CHART_HISTORY_POINTS
from polybot.dashboard.history import last_chart_value, trim

from .layout import chart_panel_width

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
