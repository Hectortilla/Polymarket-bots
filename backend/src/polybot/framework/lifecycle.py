"""Process shutdown hooks shared by command-line service hosts."""

import asyncio
import signal
from collections.abc import Callable


def install_signal_handlers(
    shutdown: asyncio.Event, *, required: bool = True
) -> Callable[[], None]:
    """Install shutdown hooks and return cleanup for successfully installed hooks."""
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []

    def remove() -> None:
        for signum in installed:
            loop.remove_signal_handler(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, shutdown.set)
            except (NotImplementedError, RuntimeError):
                if required:
                    raise
            else:
                installed.append(signum)
    except BaseException:
        remove()
        raise
    return remove


async def set_event_after_seconds(seconds: int, event: asyncio.Event) -> None:
    await asyncio.sleep(seconds)
    event.set()
