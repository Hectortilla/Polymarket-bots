"""Async, fail-open Rich dashboard observer."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import select
import sys
from threading import Event, Lock
from traceback import format_exception

from rich.console import Console
from rich.live import Live
from rich.text import Text

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - non-POSIX terminals do not support cbreak input.
    termios = None
    tty = None

from polybot.cli.dashboard.render import render_dashboard, wallet_lane_capacity
from polybot.async_io import run_blocking
from polybot.cli.dashboard.state import DashboardState
from polybot.cli.observability.events import RuntimeEvent
from polybot.framework.config.models import BotConfig

DASHBOARD_REFRESH_SECONDS = 0.25


class TerminalDashboard:
    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()
        self._state = DashboardState(require_accepted_books=True)
        self._live: Live | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._state_lock = Lock()
        self._input_task: asyncio.Task[None] | None = None
        self._input_stop = Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self, config: BotConfig) -> None:
        self._loop = asyncio.get_running_loop()
        with self._state_lock:
            self._state.book_max_age_ms = config.event_max_age_ms
            self._state.set_wallet_lanes(
                tuple(
                    wallet
                    for rule in config.stream_rules
                    for wallet in rule.wallet_addresses
                )
            )
        self._live = Live(
            console=self._console,
            screen=True,
            auto_refresh=False,
            transient=True,
            redirect_stdout=True,
            redirect_stderr=True,
        )
        try:
            await run_blocking(self._live.start, refresh=True)
            self._task = asyncio.create_task(self._render_loop())
            self._input_stop.clear()
            self._input_task = asyncio.create_task(self._read_keys())
        except Exception as error:
            cleanup_error = await self._close_live()
            self._report_failure(error, cleanup_error)
            raise

    def emit(self, event: RuntimeEvent) -> None:
        with self._state_lock:
            self._state.apply(event)
        self._wake.set()

    async def stop(self) -> None:
        cleanup_task = asyncio.create_task(self._stop_impl())
        cancellation: asyncio.CancelledError | None = None
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError as error:
                # asyncio.run cancels the main task on Ctrl+C. Keep waiting
                # for terminal restoration before allowing that cancellation
                # to tear down the process.
                cancellation = error
        if cancellation is not None:
            await asyncio.gather(cleanup_task, return_exceptions=True)
            raise cancellation
        await cleanup_task

    async def _stop_impl(self) -> None:
        if self._input_task is not None:
            self._input_stop.set()
            input_task = self._input_task
            await asyncio.gather(input_task, return_exceptions=True)
            self._input_task = None
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._live is None:
            return
        render_error: Exception | None = None
        try:
            await run_blocking(self._render)
        except Exception as error:
            render_error = error
        cleanup_error = await self._close_live()
        failure = render_error or cleanup_error
        if failure is not None:
            self._report_failure(failure, cleanup_error if render_error else None)
            raise failure

    async def _render_loop(self) -> None:
        try:
            while self._live is not None:
                try:
                    await asyncio.wait_for(self._wake.wait(), DASHBOARD_REFRESH_SECONDS)
                except TimeoutError:
                    pass
                self._wake.clear()
                await run_blocking(self._render)
        except Exception as error:
            cleanup_error = await self._close_live()
            self._report_failure(error, cleanup_error)

    async def _read_keys(self) -> None:
        if termios is None or tty is None or not sys.stdin.isatty():
            return
        await run_blocking(self._read_terminal_keys)

    def _read_terminal_keys(self) -> None:
        file_descriptor = sys.stdin.fileno()
        settings = termios.tcgetattr(file_descriptor)
        try:
            tty.setcbreak(file_descriptor)
            while self._live is not None and not self._input_stop.is_set():
                ready, _, _ = select.select(
                    (sys.stdin,), (), (), DASHBOARD_REFRESH_SECONDS
                )
                if ready:
                    self._handle_key(sys.stdin.read(1))
        finally:
            termios.tcsetattr(file_descriptor, termios.TCSADRAIN, settings)

    def _handle_key(self, key: str) -> None:
        with self._state_lock:
            if key.lower() == "z":
                changed = self._state.zoom_time(-1)
            elif key.lower() == "x":
                changed = self._state.zoom_time(1)
            elif key.lower() == "r":
                changed = self._state.reset_time_zoom()
            elif key.lower() == "v":
                self._state.toggle_view()
                changed = True
            elif key.lower() == "m":
                self._state.toggle_market_events()
                changed = True
            elif key.lower() == "j":
                changed = self._state.page_wallets(
                    1,
                    wallet_lane_capacity(
                        self._console.size.width,
                        self._console.size.height,
                    ),
                )
            elif key.lower() == "k":
                changed = self._state.page_wallets(
                    -1,
                    wallet_lane_capacity(
                        self._console.size.width,
                        self._console.size.height,
                    ),
                )
            else:
                changed = False
        if changed:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._wake.set)

    def _render(self) -> None:
        live = self._live
        if live is None:
            return
        width = self._console.size.width
        height = self._console.size.height
        with self._state_lock:
            self._state.revalidate_wallet_page(
                wallet_lane_capacity(width, height)
            )
            self._state.record_chart_sample()
            state = deepcopy(self._state)
        live.update(
            render_dashboard(state, width, height),
            refresh=True,
        )

    async def _close_live(self) -> Exception | None:
        live = self._live
        self._live = None
        if live is None:
            return None
        try:
            await run_blocking(live.stop)
        except Exception as error:
            return error
        return None

    def _report_failure(
        self,
        error: Exception,
        cleanup_error: Exception | None = None,
    ) -> None:
        message = Text(
            "Dashboard stopped after an internal error; bot execution continues.\n",
            style="bold red",
        )
        message.append("".join(format_exception(error)), style="red")
        if cleanup_error is not None and cleanup_error is not error:
            message.append("Dashboard cleanup also failed:\n", style="bold red")
            message.append("".join(format_exception(cleanup_error)), style="red")
        self._console.print(message)
