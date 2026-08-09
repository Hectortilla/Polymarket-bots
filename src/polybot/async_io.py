"""Async adapters for short blocking operations owned by the package."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

ResultT = TypeVar("ResultT")


async def run_blocking(
    function: Callable[..., ResultT],
    *args: object,
    **kwargs: object,
) -> ResultT:
    """Run one blocking operation without occupying the event-loop thread."""

    return await asyncio.to_thread(function, *args, **kwargs)
