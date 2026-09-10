"""Dispatch deterministic books through the real framework and event projection."""

import asyncio
from time import monotonic

from polybot.cli.observability.events import (
    DispatchCompleted,
    StreamHealth,
    StreamReceived,
)
from polybot.cli.streams.contracts import BookStreamEvent
from polybot.cli.streams.kinds import StreamKind

from control_plane.onboarding_policy import FIXTURE_TICK_SECONDS


async def dispatch_books(runner, market_data, observer):
    book_received_count = 0
    while True:
        book = await market_data.latest(market_data.market.token_ids[0])
        item = BookStreamEvent(StreamKind.BOOK, book)
        observer.emit(StreamReceived(item, monotonic()))
        outcome = await runner.dispatch_book(book)
        observer.emit(DispatchCompleted(item, outcome, monotonic()))
        book_received_count += 1
        observer.emit(StreamHealth(0, 0, 0, book_received_count=book_received_count))
        await asyncio.sleep(FIXTURE_TICK_SECONDS)
