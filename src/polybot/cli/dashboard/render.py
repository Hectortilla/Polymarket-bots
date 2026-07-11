"""Rich renderables for the terminal dashboard."""

from __future__ import annotations

from collections import deque
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
MIN_WALLET_VALUE_CHART_MARGIN = 1.0
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
    series, colors = _price_chart_series(state)
    legend = _market_legend(state)
    price = _chart(
        series,
        colors,
        max(5, min(12, height // 3)),
        "No two-sided market prices",
        minimum=PRICE_CHART_MIN,
        maximum=PRICE_CHART_MAX,
    )
    if height < 30:
        return Panel(Group(legend, price), title="Market price", border_style="cyan")
    wallet_values = list(state.wallet_value_history)
    wallet_minimum, wallet_maximum = _padded_bounds(wallet_values)
    wallet_value = _chart(
        _split_stale_samples(wallet_values, state.wallet_value_stale_history),
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
            Text("green: current · dim green: stale", style="bright_green"),
            wallet_value,
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


def _price_chart_series(state: DashboardState) -> tuple[list[list[float]], tuple[str, ...]]:
    series: list[list[float]] = []
    colors: list[str] = []
    for index, token_id in enumerate(state.chart_tokens):
        values = list(state.price_history[token_id])
        stale = state.price_stale_history.get(token_id, deque())
        series.extend(_split_stale_samples(values, stale))
        colors.extend((SERIES_COLORS[index], DIMMED_SERIES_COLORS[index]))
    return series, tuple(colors)


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
    margin = max(
        (maximum - minimum) * WALLET_VALUE_CHART_MARGIN_RATIO,
        max(abs(minimum), abs(maximum)) * WALLET_VALUE_CHART_MARGIN_RATIO,
        MIN_WALLET_VALUE_CHART_MARGIN,
    )
    return minimum - margin, maximum + margin


def _ticker_panel(state: DashboardState) -> Panel:
    rows = [Text(row.message, style=row.style, overflow="ellipsis") for row in state.ticker]
    return Panel(
        Group(*rows) if rows else Text("Waiting for runtime events", style="dim"),
        title="Activity",
        border_style="bright_magenta",
    )


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
        Text(f"wallet lag {_optional_ms(state.average_wallet_lag_ms())}", style="magenta"),
        Text(f"broker {_optional_ms(state.average_broker_latency_ms())}", style="cyan"),
    )
    return Panel(table, border_style="bright_blue")


def _money(value: Decimal) -> str:
    return f"${value:.2f}"


def _optional_money(value: Decimal | None) -> str:
    return MISSING_METRIC if value is None else _money(value)


def _optional_ms(value: int | None) -> str:
    return MISSING_METRIC if value is None else f"{value}ms"
