"""Dashboard ticker and runtime-status renderables."""

from __future__ import annotations

from decimal import Decimal

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Group

from polybot.cli.observability.events import BootstrapPhase
from polybot.cli.streams.contracts import StreamKind

from .state import DashboardState

MISSING_METRIC = "N/A"


def ticker_panel(state: DashboardState) -> Panel:
    rows = [
        Text(
            ticker_message(row.message, row.count),
            style=row.style,
            overflow="ellipsis",
        )
        for row in state.ticker
    ]
    progress_rows = []
    if state.wallets_total is not None:
        progress_rows.append(
            progress_line(
                BootstrapPhase.WALLETS.value,
                state.wallets_loaded,
                state.wallets_total,
                "cyan",
            )
        )
    if state.markets_total is not None:
        progress_rows.append(
            progress_line(
                BootstrapPhase.MARKETS.value,
                state.markets_loaded,
                state.markets_total,
                "magenta",
            )
        )
    content = [*progress_rows, *rows]
    return Panel(
        Group(*content) if content else Text("Waiting for runtime events", style="dim"),
        title="Activity",
        border_style="bright_magenta",
    )


def ticker_message(message: str, count: int) -> str:
    return message if count == 1 else f"{message} x{count}"


def progress_line(label: str, completed: int, total: int, style: str) -> Text:
    bar_width = 12
    filled = filled_progress_width(completed, total, bar_width=bar_width)
    bar = "#" * filled + "-" * (bar_width - filled)
    return Text(f"{label:<8} [{bar}] {completed}/{total}", style=style)


def filled_progress_width(completed: int, total: int, *, bar_width: int) -> int:
    if total == 0:
        return 0
    if completed == total:
        return bar_width
    return int(bar_width * completed / total)


def status_panel(state: DashboardState) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    portfolio = state.portfolio
    cash = "-" if portfolio is None else money(portfolio.cash_usdc)
    fees = "-" if portfolio is None else money(portfolio.cumulative_fees_usdc)
    valuation = state.portfolio_valuation()
    equity = optional_money(valuation.equity, stale=valuation.is_stale)
    pnl = optional_money(valuation.pnl, stale=valuation.is_stale)
    books = state.stream_counts.get(StreamKind.BOOK, 0)
    wallets = state.stream_counts.get(StreamKind.WALLET, 0)
    positions = 0 if portfolio is None else len(portfolio.positions)
    table.add_row(
        Text(
            f"{state.lifecycle.value.upper()} · "
            f"{state.mode.value if state.mode is not None else '-'} · {state.name}",
            style="bold white",
        ),
        Text(
            f"{state.uptime_seconds()}s · {state.event_rate():.1f} ev/s",
            style="bright_cyan",
        ),
        Text(
            f"books {books} · follows {wallets} · skip {state.skipped_dispatches} · "
            f"resolved {state.resolved_market_count}",
            style="yellow",
        ),
        Text(
            f"fills {state.fill_count} · rejects {state.rejected_count}",
            style="green",
        ),
    )
    table.add_row(
        Text(f"cash {cash} · equity {equity} · PnL {pnl}", style="bold green"),
        Text(f"fees {fees} · positions {positions}", style="white"),
        Text(
            f"book lag {fixed_ms(state.latest_book_lag_ms())} · "
            f"p95 {fixed_ms(state.book_lag_percentile(0.95))} · "
            f"max {fixed_ms(state.maximum_book_lag_ms())} · "
            f"q {state.queue_depth}/{state.peak_queue_depth} · "
            f"stale {state.stale_ratio():.0%}",
            style="yellow",
        ),
        Text(
            f"broker {optional_ms(state.average_broker_latency_ms())}",
            style="cyan",
        ),
    )
    return Panel(table, border_style="bright_blue")


def money(value: Decimal) -> str:
    return f"${value:.2f}"


def optional_money(value: Decimal | None, *, stale: bool = False) -> str:
    if value is None:
        return MISSING_METRIC
    return f"{money(value)} (stale)" if stale else money(value)


def optional_ms(value: int | None) -> str:
    return MISSING_METRIC if value is None else f"{value}ms"


def fixed_ms(value: int | None) -> str:
    return f"{value:6d}ms" if value is not None else f"{MISSING_METRIC:>8}"
