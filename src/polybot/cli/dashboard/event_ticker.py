"""Deduplicated activity rows shown by the terminal dashboard."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from polybot.framework.activity import ActivitySeverity
from polybot.framework.events import Side

from .palette import side_text_style

MAX_TICKER_ROWS = 40


@dataclass(frozen=True, slots=True)
class TickerRow:
    style: str
    message: str
    count: int = 1


@dataclass(slots=True)
class DashboardTicker:
    """Keeps ordinary and high-frequency market activity independently."""

    ticker: deque[TickerRow] = field(
        default_factory=lambda: deque(maxlen=MAX_TICKER_ROWS)
    )
    market_ticker: deque[TickerRow] = field(
        default_factory=lambda: deque(maxlen=MAX_TICKER_ROWS)
    )
    show_market_events: bool = False

    def add(self, style: str, message: str) -> None:
        self._append(self.ticker, style, message)

    def add_market_event(self, style: str, message: str) -> None:
        self._append(self.market_ticker, style, message)

    def rows(self) -> list[TickerRow]:
        if not self.show_market_events:
            return list(self.ticker)
        return [*self.market_ticker, *self.ticker]

    def toggle_market_events(self) -> None:
        self.show_market_events = not self.show_market_events

    @staticmethod
    def side_style(side: Side) -> str:
        return side_text_style(side, bold=True)

    @staticmethod
    def activity_style(severity: ActivitySeverity) -> str:
        return {
            ActivitySeverity.INFO: "white",
            ActivitySeverity.SUCCESS: "bold green",
            ActivitySeverity.WARNING: "bold yellow",
            ActivitySeverity.ERROR: "bold red",
        }[severity]

    @staticmethod
    def _append(ticker: deque[TickerRow], style: str, message: str) -> None:
        safe_message = "".join(
            character if character.isprintable() else " " for character in message
        )
        if ticker and ticker[0].message == safe_message:
            previous = ticker[0]
            ticker[0] = TickerRow(previous.style, safe_message, previous.count + 1)
            return
        ticker.appendleft(TickerRow(style, safe_message))
