"""Reusable Rich and asciichartpy terminal-chart primitives."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from math import isfinite, nan

import asciichartpy
from rich.text import Text


VALUE_CHART_MARGIN_RATIO = 0.15
VALUE_FLAT_CHART_MARGIN_RATIO = 0.001
MIN_VALUE_CHART_MARGIN = 0.01
CHART_Y_AXIS_WIDTH = 10
DIMMED_VALUE_COLOR = f"\033[2m{asciichartpy.lightgreen}"
MIN_TERMINAL_CHART_POINTS = 12
MAX_TERMINAL_CHART_POINTS = 120


def render_chart(
    series: list[list[float]],
    colors: tuple[str, ...],
    chart_height: int,
    empty_message: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Text:
    sanitized_series = _sanitized_series(series)
    if not _has_plottable_samples(sanitized_series):
        return Text(empty_message, style="dim")
    config: dict[str, object] = {"height": chart_height, "colors": list(colors)}
    if minimum is not None and isfinite(minimum):
        config["min"] = minimum
    if maximum is not None and isfinite(maximum):
        config["max"] = maximum
    chart = asciichartpy.plot(
        sanitized_series if len(sanitized_series) > 1 else sanitized_series[0],
        config,
    )
    return Text.from_ansi(chart)


def padded_value_bounds(values: Sequence[float]) -> tuple[float | None, float | None]:
    displayed_values = [value for value in values if isfinite(value)]
    if not displayed_values:
        return None, None
    minimum = min(displayed_values)
    maximum = max(displayed_values)
    value_range = maximum - minimum
    margin = max(
        value_range * VALUE_CHART_MARGIN_RATIO,
        MIN_VALUE_CHART_MARGIN,
    )
    if value_range == 0:
        margin = max(
            margin,
            max(abs(minimum), abs(maximum)) * VALUE_FLAT_CHART_MARGIN_RATIO,
        )
    return minimum - margin, maximum + margin


def resample_indices(source_points: int, display_points: int) -> list[int]:
    if source_points < 0:
        raise ValueError("source chart point count must be nonnegative")
    if display_points <= 0:
        raise ValueError("display chart point count must be positive")
    return _resample_indices(source_points, display_points)


def _resample_indices(source_points: int, display_points: int) -> list[int]:
    if source_points == 0:
        return []
    if display_points == 1:
        return [source_points - 1]
    return [
        round(index * (source_points - 1) / (display_points - 1))
        for index in range(display_points)
    ]


def split_stale_samples(
    values: Sequence[float],
    stale_samples: Sequence[bool],
) -> list[list[float]]:
    stale = [*stale_samples]
    stale.extend(False for _ in range(len(values) - len(stale)))
    current = [
        _finite_chart_value(value) if not is_stale else nan
        for value, is_stale in zip(values, stale)
    ]
    dimmed = [
        _finite_chart_value(value) if is_stale else nan
        for value, is_stale in zip(values, stale)
    ]
    return [current, dimmed]


def chart_time_range(
    visible_range: tuple[float, float] | None,
    display_points: int,
) -> Text:
    if visible_range is None:
        return Text("time range unavailable", style="dim", justify="center")
    started_at, ended_at = visible_range
    label = Text(style="dim cyan")
    label.append(" " * CHART_Y_AXIS_WIDTH)
    label.append(datetime.fromtimestamp(started_at).strftime("%H:%M:%S"))
    label.append(" " * max(1, display_points - 16))
    label.append(datetime.fromtimestamp(ended_at).strftime("%H:%M:%S"))
    return label


def _has_plottable_samples(series: Sequence[Sequence[float]]) -> bool:
    return any(_contains_finite_sample(values) for values in series)


def _contains_finite_sample(values: Sequence[float]) -> bool:
    return bool(values) and any(isfinite(value) for value in values)


def _sanitized_series(series: Sequence[Sequence[float]]) -> list[list[float]]:
    return [
        [_finite_chart_value(value) for value in values]
        for values in series
    ]


def _finite_chart_value(value: float) -> float:
    return value if isfinite(value) else nan
