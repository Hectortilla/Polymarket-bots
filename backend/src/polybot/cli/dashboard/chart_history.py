"""Terminal chart navigation layered over shared dashboard history."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.dashboard.history import DashboardHistory

from .chart_state import (
    MAX_TIME_ZOOM_LEVEL,
    MIN_TIME_ZOOM_LEVEL,
    chart_display_points,
    chart_window_points,
    visible_epoch_seconds_range,
)


@dataclass(slots=True)
class DashboardCharts(DashboardHistory):
    time_zoom_level: int = 0

    def chart_window_points(self, width: int) -> int:
        return chart_window_points(self.time_zoom_level, width)

    @staticmethod
    def chart_display_points(width: int) -> int:
        return chart_display_points(width)

    def visible_epoch_seconds_range(self, width: int) -> tuple[float, float] | None:
        return visible_epoch_seconds_range(
            self.chart_sample_epoch_seconds,
            self.time_zoom_level,
            width,
        )

    def zoom(self, direction: int) -> bool:
        updated_level = min(
            MAX_TIME_ZOOM_LEVEL,
            max(MIN_TIME_ZOOM_LEVEL, self.time_zoom_level + direction),
        )
        if updated_level == self.time_zoom_level:
            return False
        self.time_zoom_level = updated_level
        return True

    def reset_zoom(self) -> bool:
        if self.time_zoom_level == 0:
            return False
        self.time_zoom_level = 0
        return True
