"""Async, fail-open Rich dashboard observer."""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.live import Live

from polybot.cli.dashboard.render import render_dashboard
from polybot.cli.dashboard.state import DashboardState
from polybot.cli.observability.events import RuntimeEvent
from polybot.framework.config import BotConfig

DASHBOARD_REFRESH_SECONDS = 0.25


class TerminalDashboard:
    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()
        self._state = DashboardState(require_accepted_books=True)
        self._live: Live | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    async def start(self, config: BotConfig) -> None:
        self._state.book_max_age_ms = config.book_max_age_ms
        self._live = Live(
            console=self._console,
            screen=True,
            auto_refresh=False,
            transient=True,
            redirect_stdout=True,
            redirect_stderr=True,
        )
        try:
            await asyncio.to_thread(self._live.start, refresh=True)
            self._task = asyncio.create_task(self._render_loop())
        except Exception:
            if self._live is not None:
                await asyncio.to_thread(self._live.stop)
                self._live = None
            raise

    def emit(self, event: RuntimeEvent) -> None:
        self._state.apply(event)
        self._wake.set()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._live is not None:
            try:
                await asyncio.to_thread(self._render)
            finally:
                await asyncio.to_thread(self._live.stop)
                self._live = None

    async def _render_loop(self) -> None:
        try:
            while self._live is not None:
                try:
                    await asyncio.wait_for(self._wake.wait(), DASHBOARD_REFRESH_SECONDS)
                except TimeoutError:
                    pass
                self._wake.clear()
                await asyncio.to_thread(self._render)
        except Exception:
            if self._live is not None:
                await asyncio.to_thread(self._live.stop)
                self._live = None

    def _render(self) -> None:
        if self._live is None:
            return
        width = self._console.size.width
        height = self._console.size.height
        self._state.sample(width)
        self._live.update(
            render_dashboard(self._state, width, height),
            refresh=True,
        )
