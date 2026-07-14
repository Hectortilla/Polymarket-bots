"""Async adapters for short blocking operations owned by the package."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from threading import Event, Thread
from typing import TypeVar

BLOCKING_POLL_INTERVAL_SECONDS = 0.01


ResultT = TypeVar("ResultT")


async def run_blocking(
    function: Callable[..., ResultT],
    *args: object,
    **kwargs: object,
) -> ResultT:
    """Run one blocking operation without occupying the event-loop thread."""

    completed = Event()
    result: list[ResultT] = []
    error: list[BaseException] = []

    def invoke() -> None:
        try:
            result.append(partial(function, *args, **kwargs)())
        except BaseException as exception:
            error.append(exception)
        finally:
            completed.set()

    Thread(target=invoke, name="polybot-io", daemon=True).start()
    while not completed.is_set():
        await asyncio.sleep(BLOCKING_POLL_INTERVAL_SECONDS)
    if error:
        raise error[0]
    return result[0]
