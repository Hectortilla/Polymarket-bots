"""Rich renderables for the terminal dashboard."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from decimal import Decimal
from math import isnan

import asciichartpy
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from polybot.cli.streams import StreamKind

from .palette import SERIES_PALETTE
from .state import DashboardState, short_token

MISSING_METRIC = "N/A"
PRICE_CHART_MIN = 0.0
PRICE_CHART_MAX = 1.0
WALLET_VALUE_CHART_MARGIN_RATIO = 0.15
WALLET_VALUE_FLAT_CHART_MARGIN_RATIO = 0.001
MIN_WALLET_VALUE_CHART_MARGIN = 0.01
CHART_Y_AXIS_WIDTH = 10
SERIES_COLORS = tuple(chart_color for chart_color, _ in SERIES_PALETTE)
DIMMED_SERIES_COLORS = tuple(f"\033[2m{color}" for color in SERIES_COLORS)
DIMMED_WALLET_VALUE_COLOR = f"\033[2m{asciichartpy.lightgreen}"
SERIES_LEGEND_STYLES = tuple(legend_style for _, legend_style in SERIES_PALETTE)


def render_dashboard(state: DashboardState, width: int, height: int) -> Layout:
    chart_panel = _chart_panel(state, width, height)
    ticker_panel = _ticker_panel(state)
    body = Layout(name="body")
    if width >= 110:
        body.split_row(
            Layout(chart_panel, name="charts", ratio=2),
            Layout(ticker_panel, name="ticker", ratio=1),
        )
    else:
        body.split_column(Layout(chart_panel, name="charts", ratio=2), Layout(ticker_panel, name="ticker", ratio=1))
    layout = Layout()
    layout.split_column(body, Layout(_status_panel(state), name="status", size=5))
    return layout


def _chart_panel(state: DashboardState, width: int, height: int) -> Panel:
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
    time_range = _chart_time_range(state, width)
    if height < 30:
        return Panel(
            Group(legend, price, time_range),
            title="Market price",
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
            legend,
            price,
            Text("Executable wallet value", style="bold green"),
            Text(
                f"green: current · dim green: stale · z/x time zoom ({_time_window_label(state.time_zoom_level)}) · r reset",
                style="bright_green",
            ),
            wallet_value,
            time_range,
        ),
        title="Market price and paper wallet value",
        border_style="cyan",
    )


def _market_legend(state: DashboardState) -> Text:
    legend = Text()
    for index, token_id in enumerate(state.chart_tokens):
        if index:
            legend.append("  ")
        legend.append(
            f"{index + 1}: {state.market_label(token_id)}",
            style=SERIES_LEGEND_STYLES[index],
        )
    return legend


def _chart(
    series: list[list[float]],
    colors: tuple[str, ...],
    chart_height: int,
    empty_message: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Text:
    if not series or not any(
        values and any(not isnan(value) for value in values) for values in series
    ):
        return Text(empty_message, style="dim")
    config: dict[str, object] = {"height": chart_height, "colors": list(colors)}
    if minimum is not None:
        config["min"] = minimum
    if maximum is not None:
        config["max"] = maximum
    chart = asciichartpy.plot(series if len(series) > 1 else series[0], config)
    return Text.from_ansi(chart)


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
    return series, tuple(colors)


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
    visible_values = [float("nan")] * (source_count - len(visible_values)) + visible_values
    visible_stale = [False] * (source_count - len(visible_stale)) + visible_stale
    indices = _resample_indices(source_count, display_points)
    return (
        [visible_values[index] for index in indices],
        deque(visible_stale[index] for index in indices),
    )


def _resample_indices(source_points: int, display_points: int) -> list[int]:
    if source_points == 0:
        return []
    if display_points == 1:
        return [source_points - 1]
    return [
        round(index * (source_points - 1) / (display_points - 1))
        for index in range(display_points)
    ]


def _split_stale_samples(
    values: list[float], stale_samples: deque[bool],
) -> list[list[float]]:
    stale = [*stale_samples]
    stale.extend(False for _ in range(len(values) - len(stale)))
    current = [value if not is_stale else float("nan") for value, is_stale in zip(values, stale)]
    dimmed = [value if is_stale else float("nan") for value, is_stale in zip(values, stale)]
    return [current, dimmed]


def _padded_bounds(values: list[float]) -> tuple[float | None, float | None]:
    displayed_values = [value for value in values if not isnan(value)]
    if not displayed_values:
        return None, None
    minimum = min(displayed_values)
    maximum = max(displayed_values)
    value_range = maximum - minimum
    margin = max(
        value_range * WALLET_VALUE_CHART_MARGIN_RATIO,
        MIN_WALLET_VALUE_CHART_MARGIN,
    )
    if value_range == 0:
        margin = max(
            margin,
            max(abs(minimum), abs(maximum)) * WALLET_VALUE_FLAT_CHART_MARGIN_RATIO,
        )
    return minimum - margin, maximum + margin


def _price_chart_height(width: int, height: int) -> int:
    available_height = height - 5  # Persistent status row.
    if width < 110:
        available_height = available_height * 2 // 3  # Chart/activity split.
    wallet_height = 8 if height >= 30 else 0
    return max(5, min(18, available_height - wallet_height - 3))


def _time_window_label(zoom_level: int) -> str:
    if zoom_level == 0:
        return "normal"
    return f"{2**abs(zoom_level)}x {'closer' if zoom_level < 0 else 'wider'}"


def _chart_time_range(state: DashboardState, width: int) -> Text:
    visible_range = state.visible_time_range(width)
    if visible_range is None:
        return Text("time range unavailable", style="dim", justify="center")
    started_at, ended_at = visible_range
    label = Text(style="dim cyan")
    label.append(" " * CHART_Y_AXIS_WIDTH)
    label.append(datetime.fromtimestamp(started_at).strftime("%H:%M:%S"))
    label.append(" " * max(1, state.chart_display_points(width) - 16))
    label.append(datetime.fromtimestamp(ended_at).strftime("%H:%M:%S"))
    return label


def _ticker_panel(state: DashboardState) -> Panel:
    rows = [
        Text(_ticker_message(row.message, row.count), style=row.style, overflow="ellipsis")
        for row in state.ticker
    ]
    return Panel(
        Group(*rows) if rows else Text("Waiting for runtime events", style="dim"),
        title="Activity",
        border_style="bright_magenta",
    )


def _ticker_message(message: str, count: int) -> str:
    return message if count == 1 else f"{message} x{count}"


def _status_panel(state: DashboardState) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    portfolio = state.portfolio
    cash = "-" if portfolio is None else _money(portfolio.cash_usdc)
    fees = "-" if portfolio is None else _money(portfolio.cumulative_fees_usdc)
    equity = _optional_money(state.executable_equity())
    pnl = _optional_money(state.executable_pnl())
    books = state.stream_counts.get(StreamKind.BOOK, 0)
    wallets = state.stream_counts.get(StreamKind.WALLET, 0)
    positions = 0 if portfolio is None else len(portfolio.positions)
    table.add_row(
        Text(f"{state.lifecycle.value.upper()} · {state.mode} · {state.name}", style="bold white"),
        Text(f"{state.uptime_seconds()}s · {state.event_rate():.1f} ev/s", style="bright_cyan"),
        Text(f"books {books} · follows {wallets} · skip {state.skipped_dispatches}", style="yellow"),
        Text(f"fills {state.fill_count} · rejects {state.rejected_count}", style="green"),
    )
    table.add_row(
        Text(f"cash {cash} · equity {equity} · PnL {pnl}", style="bold green"),
        Text(f"fees {fees} · positions {positions}", style="white"),
        Text(
            f"book lag {_fixed_ms(state.latest_book_lag_ms())} · "
            f"p95 {_fixed_ms(state.book_lag_percentile(0.95))} · "
            f"max {_fixed_ms(state.maximum_book_lag_ms())} · "
            f"q {state.queue_depth}/{state.peak_queue_depth} · stale {state.stale_ratio():.0%}",
            style="yellow",
        ),
        Text(f"broker {_optional_ms(state.average_broker_latency_ms())}", style="cyan"),
    )
    return Panel(table, border_style="bright_blue")


def _money(value: Decimal) -> str:
    return f"${value:.2f}"


def _optional_money(value: Decimal | None) -> str:
    return MISSING_METRIC if value is None else _money(value)


def _optional_ms(value: int | None) -> str:
    return MISSING_METRIC if value is None else f"{value}ms"


def _fixed_ms(value: int | None) -> str:
    return f"{value:6d}ms" if value is not None else f"{MISSING_METRIC:>8}"
