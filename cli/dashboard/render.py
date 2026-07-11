"""Rich renderables for the terminal dashboard."""

from __future__ import annotations

from decimal import Decimal
from math import isnan

import asciichartpy
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from bots.cli.streams import StreamKind

from .palette import SERIES_PALETTE
from .state import DashboardState, short_token

MISSING_METRIC = "N/A"
SERIES_COLORS = tuple(chart_color for chart_color, _ in SERIES_PALETTE)
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
    series = [list(state.price_history[token_id]) for token_id in state.chart_tokens]
    legend = Text()
    for index, token_id in enumerate(state.chart_tokens):
        if index:
            legend.append("  ")
        legend.append(short_token(token_id), style=SERIES_LEGEND_STYLES[index])
    price = _chart(
        series,
        SERIES_COLORS,
        max(5, min(12, height // 3)),
        "No two-sided market prices",
    )
    if height < 30:
        return Panel(Group(legend, price), title="Market price", border_style="cyan")
    pnl = _chart([list(state.pnl_history)], (asciichartpy.lightgreen,), 5, "PnL unavailable")
    return Panel(
        Group(legend, price, Text("Executable PnL", style="bold green"), pnl),
        title="Market price and paper PnL",
        border_style="cyan",
    )


def _chart(
    series: list[list[float]],
    colors: tuple[str, ...],
    chart_height: int,
    empty_message: str,
) -> Text:
    if not series or not any(
        values and any(not isnan(value) for value in values) for values in series
    ):
        return Text(empty_message, style="dim")
    chart = asciichartpy.plot(
        series if len(series) > 1 else series[0],
        {"height": chart_height, "colors": list(colors)},
    )
    return Text.from_ansi(chart)


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
