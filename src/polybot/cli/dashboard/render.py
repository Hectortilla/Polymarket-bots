"""Rich renderables for the terminal dashboard."""

from __future__ import annotations

from collections import deque
from math import isnan

import asciichartpy
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from polybot.cli.charting import (
    DIMMED_VALUE_COLOR,
    chart_time_range,
    padded_value_bounds as _padded_bounds,
    render_chart as _chart,
    resample_indices as _resample_indices,
    split_stale_samples as _split_stale_samples,
)
from polybot.framework.events import Side
from polybot.framework.events.books import PRICE_CEILING, PRICE_FLOOR

from .layout import (
    DASHBOARD_NARROW_WIDTH,
    DASHBOARD_STATUS_HEIGHT,
    WALLET_VALUE_CHART_MIN_HEIGHT,
    primary_chart_available_height,
)
from .palette import SERIES_PALETTE, side_chart_color
from .state import DashboardState, DashboardView
from .status import fixed_ms as _fixed_ms
from .status import money as _money
from .status import optional_money as _optional_money
from .status import optional_ms as _optional_ms
from .status import status_panel as _status_panel
from .status import ticker_panel as _ticker_panel
from .wallet_timeline import (
    short_wallet as _short_wallet,
    wallet_bucket_glyph as _wallet_bucket_glyph,
    wallet_lane_summary as _wallet_lane_summary,
    wallet_timeline as _wallet_timeline,
    wallet_timeline_buckets as _wallet_timeline_buckets,
    wallet_timeline_columns as _wallet_timeline_columns,
    wallet_lane_capacity,
)

PRICE_CHART_MIN = float(PRICE_FLOOR)
PRICE_CHART_MAX = float(PRICE_CEILING)
SERIES_COLORS = tuple(chart_color for chart_color, _ in SERIES_PALETTE)
DIMMED_SERIES_COLORS = tuple(f"\033[2m{color}" for color in SERIES_COLORS)
DIMMED_WALLET_VALUE_COLOR = DIMMED_VALUE_COLOR
SERIES_LEGEND_STYLES = tuple(legend_style for _, legend_style in SERIES_PALETTE)


def render_dashboard(state: DashboardState, width: int, height: int) -> Layout:
    chart_panel = _chart_panel(state, width, height)
    ticker_panel = _ticker_panel(state)
    body = Layout(name="body")
    if width >= DASHBOARD_NARROW_WIDTH:
        body.split_row(
            Layout(chart_panel, name="charts", ratio=2),
            Layout(ticker_panel, name="ticker", ratio=1),
        )
    else:
        body.split_column(
            Layout(chart_panel, name="charts", ratio=2),
            Layout(ticker_panel, name="ticker", ratio=1),
        )
    layout = Layout()
    layout.split_column(
        body,
        Layout(_status_panel(state), name="status", size=DASHBOARD_STATUS_HEIGHT),
    )
    return layout


def _chart_panel(state: DashboardState, width: int, height: int) -> Panel:
    primary, title = _primary_chart(state, width, height)
    time_range = _chart_time_range(state, width)
    if height < WALLET_VALUE_CHART_MIN_HEIGHT:
        return Panel(
            Group(primary, time_range),
            title=title,
            border_style="cyan",
        )
    wallet_values, wallet_stale_samples = _visible_chart_samples(
        state.wallet_value_history,
        state.wallet_value_stale_history,
        state,
        width,
    )
    wallet_minimum, wallet_maximum = _padded_bounds(wallet_values)
    wallet_value = _chart(
        _split_stale_samples(wallet_values, wallet_stale_samples),
        (asciichartpy.lightgreen, DIMMED_WALLET_VALUE_COLOR),
        5,
        "Wallet value unavailable",
        minimum=wallet_minimum,
        maximum=wallet_maximum,
    )
    return Panel(
        Group(
            primary,
            Text("Executable wallet value", style="bold green"),
            Text(
                f"green: current · dim green: stale · z/x time zoom ({_time_window_label(state.time_zoom_level)}) · r reset",
                style="bright_green",
            ),
            wallet_value,
            time_range,
        ),
        title=title,
        border_style="cyan",
    )


def _primary_chart(state: DashboardState, width: int, height: int) -> tuple[Group, str]:
    if state.view is DashboardView.WALLET:
        return (
            _wallet_timeline(state, width, height),
            "Followed wallet activity and paper wallet value",
        )
    series, colors = _price_chart_series(state, width)
    legend = _market_legend(state)
    price = _chart(
        series,
        colors,
        _price_chart_height(width, height),
        "No two-sided market prices",
        minimum=PRICE_CHART_MIN,
        maximum=PRICE_CHART_MAX,
    )
    return Group(legend, price), "Market price and paper wallet value"


def _market_legend(state: DashboardState) -> Text:
    legend = Text()
    for index, token_id in enumerate(state.chart_tokens):
        if index:
            legend.append("  ")
        legend.append(
            f"{index + 1}: {state.market_label(token_id)}",
            style=SERIES_LEGEND_STYLES[index],
        )
    if state.chart_tokens:
        legend.append("  green mark: buy", style="bright_green")
        legend.append(" · red mark: sell", style="red")
    return legend


def _price_chart_series(
    state: DashboardState, width: int
) -> tuple[list[list[float]], tuple[str, ...]]:
    series: list[list[float]] = []
    colors: list[str] = []
    for index, token_id in enumerate(state.chart_tokens):
        values, stale = _visible_chart_samples(
            state.price_history[token_id],
            state.price_stale_history.get(token_id, deque()),
            state,
            width,
        )
        series.extend(_split_stale_samples(values, stale))
        colors.extend((SERIES_COLORS[index], DIMMED_SERIES_COLORS[index]))
        marker_series, marker_colors = _visible_trade_marker_series(
            state.trade_marker_history.get(token_id, deque()),
            values,
            state,
            width,
        )
        series.extend(marker_series)
        colors.extend(marker_colors)
    return series, tuple(colors)


def _visible_trade_marker_series(
    markers: deque[tuple[Side, ...]],
    displayed_values: list[float],
    state: DashboardState,
    width: int,
) -> tuple[list[list[float]], list[str]]:
    window = state.chart_window_points(width)
    timestamp_count = min(window, len(state.chart_sample_times))
    source_count = timestamp_count or min(window, len(markers))
    if source_count == 0:
        return [], []
    visible_markers = list(markers)[-source_count:]
    visible_markers = [()] * (source_count - len(visible_markers)) + visible_markers
    indices = _resample_indices(source_count, state.chart_display_points(width))
    result: list[list[float]] = []
    colors: list[str] = []
    for source_index, sides in enumerate(visible_markers):
        if not sides:
            continue
        display_index = _nearest_display_index(indices, source_index)
        line_value = displayed_values[display_index]
        if isnan(line_value):
            continue
        for side in sides:
            series = [float("nan")] * len(indices)
            series[display_index] = line_value
            result.append(series)
            colors.append(side_chart_color(side))
    return result, colors


def _nearest_display_index(indices: list[int], source_index: int) -> int:
    nearest = min(abs(index - source_index) for index in indices)
    matches = [
        display_index
        for display_index, index in enumerate(indices)
        if abs(index - source_index) == nearest
    ]
    return matches[len(matches) // 2]


def _visible_chart_samples(
    values: deque[float],
    stale_samples: deque[bool],
    state: DashboardState,
    width: int,
) -> tuple[list[float], deque[bool]]:
    window = state.chart_window_points(width)
    display_points = state.chart_display_points(width)
    timestamp_count = min(window, len(state.chart_sample_times))
    source_count = timestamp_count or min(window, len(values))
    if source_count == 0:
        return [], deque()
    visible_values = list(values)[-source_count:]
    visible_stale = list(stale_samples)[-source_count:]
    visible_values = [float("nan")] * (
        source_count - len(visible_values)
    ) + visible_values
    visible_stale = [False] * (source_count - len(visible_stale)) + visible_stale
    indices = _resample_indices(source_count, display_points)
    return (
        [visible_values[index] for index in indices],
        deque(visible_stale[index] for index in indices),
    )


def _price_chart_height(width: int, height: int) -> int:
    return max(5, min(18, primary_chart_available_height(width, height) - 3))


def _time_window_label(zoom_level: int) -> str:
    if zoom_level == 0:
        return "normal"
    return f"{2**abs(zoom_level)}x {'closer' if zoom_level < 0 else 'wider'}"


def _chart_time_range(state: DashboardState, width: int) -> Text:
    return chart_time_range(
        state.visible_time_range(width),
        state.chart_display_points(width),
    )
